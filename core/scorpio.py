"""Read-side access to the Scorpio NGSI-LD broker for the export pipeline.

Mirrors ``apps/push_ovak_data/core/scorpio.py`` for type resolution and
counting, and adds the read-side paging that the exports need
(:meth:`ScorpioBackend.get_entities`).

Correctness notes (learned live against ``stids-scorpio.ovakszeged.hu``):

- Types are stored *expanded*: a short type such as ``GtfsRoute`` is stored as
  ``https://smartdatamodels.org/dataModel.UrbanMobility/GtfsRoute``; attributes
  are likewise stored under full IRIs. Always resolve short names through
  :meth:`resolve_stored_type` and read attribute values through
  :func:`core.context.attr`.
- Server-side ``timerel=between`` filtering is *unreliable*: the broker ignores
  the parameter for ``AirQualityObserved``/``TrafficFlowObserved`` and returns
  the full set. The authoritative window filter is therefore applied
  client-side on the stored ``dateObserved`` attribute (:meth:`_in_window`).
- For the same reason no ``attrs`` projection is sent: passing short attribute
  names (which do not match the stored IRIs) would make Scorpio drop every
  attribute and silently empty the export. Full entities are fetched.
- Paging is offset-based with ``limit`` pages; the loop stops on an empty or
  short page, or when a ``Link`` header no longer advertises ``rel="next"``.
  The ``ngsild-results-count`` header is read only for diagnostics — the broker
  can serve a stale (replica-lagging) count, so it is never used to stop.
"""

from __future__ import annotations

import logging
import time
import urllib.parse
from urllib.parse import quote
from datetime import datetime
from typing import Any, Iterable, Optional

import httpx

from .config import Settings
from .context import attr, has_attr
from .ngsilib import iso_datetime

log = logging.getLogger(__name__)

MAX_PAGES = 400


class ScorpioBackend:
    def __init__(self, settings: Settings):
        self._settings = settings
        self._client = httpx.Client(
            verify=False,
            timeout=settings.timeout,
            headers={
                "NGSILD-Tenant": settings.scorpio_tenant,
                "User-Agent": "STiDS-CKAN-Exports/1.0",
            },
        )
        self._type_list_cache: Optional[list[str]] = None

    @property
    def base_url(self) -> str:
        return self._settings.scorpio_url

    def close(self) -> None:
        self._client.close()

    # ---- type resolution -------------------------------------------------

    def _type_list(self) -> list[str]:
        if self._type_list_cache is None:
            try:
                resp = self._client.get(
                    f"{self.base_url}/ngsi-ld/v1/types",
                    headers={"Accept": "application/json"},
                )
                if resp.is_success and resp.text:
                    data = resp.json()
                    if isinstance(data, dict) and isinstance(data.get("typeList"), list):
                        self._type_list_cache = data["typeList"]
            except Exception as e:
                log.debug("Scorpio type list unavailable: %s", e)
            self._type_list_cache = self._type_list_cache or []
        return self._type_list_cache

    def resolve_stored_type(self, entity_type: str) -> str:
        """Short type -> stored (expanded) type string; IRIs pass through."""
        if "//" in entity_type:
            return entity_type
        for stored in self._type_list():
            if stored == entity_type or stored.endswith(f"/{entity_type}") or stored.endswith(f"#{entity_type}"):
                return stored
        return entity_type

    def count_by_type(self, entity_type: str) -> int:
        """Total entities of a type via ``count=true`` (exact even over limit)."""
        stored = self.resolve_stored_type(entity_type)
        try:
            resp = self._client.get(
                f"{self.base_url}/ngsi-ld/v1/entities",
                params={"type": stored, "limit": 1, "count": "true"},
                headers={"Accept": "application/json"},
            )
            if resp.is_success:
                total = resp.headers.get("ngsild-results-count")
                if total is not None:
                    try:
                        return int(total)
                    except (TypeError, ValueError):
                        pass
                entities = resp.json()
                if isinstance(entities, list):
                    return len(entities)
            return -1
        except Exception as e:
            log.debug("count_by_type(%s) failed: %s", entity_type, e)
            return -1

    # ---- entity fetch ------------------------------------------------------

    def get_entities(
        self,
        entity_type: str,
        *,
        time_from: Optional[datetime] = None,
        time_to: Optional[datetime] = None,
        require_attr: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> list[dict]:
        """Fetch entities of a type with offset paging.

        ``time_from``/``time_to`` apply the client-side ``dateObserved`` window
        filter; entities without a parseable date attribute are kept when no
        window is requested. ``require_attr`` keeps only entities carrying the
        named attribute. ``limit`` is a hard cap on the number of *kept*
        entities (page size shrinks to match), used for smoke tests.
        """
        stored = self.resolve_stored_type(entity_type)
        page_size = min(limit, self._settings.page_size) if limit else self._settings.page_size
        total: Optional[int] = None
        entities: list[dict] = []
        offset = 0

        # Server-side window filter: when a date window is requested, push it to
        # Scorpio via the `q` query param so the broker filters instead of
        # returning the whole type (e.g. AirQualityObserved ~382k entities) for
        # client-side filtering. This is what keeps `window="today"` exports from
        # stalling on huge types. The client-side `_in_window` check below stays
        # as a safety net.
        q_filter = None
        if time_from is not None and time_to is not None:
            _ge = quote(f"dateObserved>={time_from.isoformat()}")
            _le = quote(f"dateObserved<={time_to.isoformat()}")
            q_filter = f"{_ge};{_le}"

        while offset < MAX_PAGES * page_size:
            params: dict[str, Any] = {
                "type": stored,
                "limit": page_size,
                "offset": offset,
                "count": "true",
            }
            if q_filter is not None:
                params["q"] = q_filter
            resp = None
            for attempt in range(1, 5):
                try:
                    resp = self._client.get(
                        f"{self.base_url}/ngsi-ld/v1/entities",
                        params=params,
                        headers={"Accept": "application/json"},
                    )
                except Exception as e:
                    if attempt < 4:
                        log.debug("Scorpio retry %d (%s@offset %d): %s", attempt, entity_type, offset, e)
                        time.sleep(attempt)
                        continue
                    raise RuntimeError(
                        f"Scorpio kapcsolati hiba ({entity_type}@offset {offset}): {e}"
                    ) from e
                if not resp.is_success:
                    if 500 <= resp.status_code < 600 and attempt < 4:
                        log.debug("Scorpio retry %d (%s@offset %d): HTTP %d", attempt, entity_type, offset, resp.status_code)
                        time.sleep(attempt * 2)
                        continue
                    raise RuntimeError(
                        f"Scorpio HTTP {resp.status_code} ({entity_type}@offset {offset})"
                    )
                break
            if resp is None:
                raise RuntimeError(f"Scorpio válasz nélkül ({entity_type}@offset {offset})")

            if total is None:
                raw = resp.headers.get("ngsild-results-count")
                if raw is not None:
                    try:
                        total = int(raw)
                    except (TypeError, ValueError):
                        total = None
                if total is not None:
                    log.debug("Scorpio %s total=%d", entity_type, total)

            try:
                page = resp.json()
            except Exception:
                log.warning("Scorpio fetch %s@%d: non-JSON response", entity_type, offset)
                break
            if not isinstance(page, list):
                break
            page = [e for e in page if isinstance(e, dict)]

            kept = 0
            for entity in page:
                if require_attr and not has_attr(entity, require_attr):
                    continue
                if time_from is not None and time_to is not None and not self._in_window(entity, time_from, time_to):
                    continue
                entities.append(entity)
                kept += 1

            if not page:
                break
            if limit is not None and len(entities) >= limit:
                break
            link = resp.headers.get("Link")
            has_link = bool(link)
            has_next = has_link and 'rel="next"' in link
            if len(page) < page_size or (has_link and not has_next):
                break
            offset += len(page)
            time.sleep(0.05)

        return entities

    @staticmethod
    def _in_window(entity: dict, time_from: datetime, time_to: datetime) -> bool:
        """True when the entity's ``dateObserved`` overlaps [time_from, time_to]."""
        raw = attr(entity, "dateObserved", "observedAt", "observationDateTime")
        if raw in (None, ""):
            return False
        try:
            text = str(attr(entity, "dateObserved") or raw)
        except Exception:
            return False
        parts = [part for part in text.split("/") if part]
        if not parts:
            return False
        try:
            start = iso_datetime(parts[0])
            end = iso_datetime(parts[1]) if len(parts) > 1 else start
        except (TypeError, ValueError):
            return False
        return start <= time_to and end >= time_from

    # ---- per-spec fetch ----------------------------------------------------

    def fetch_types(
        self,
        types: Iterable[Any],
        *,
        time_from: Optional[datetime] = None,
        time_to: Optional[datetime] = None,
        require_attr: Optional[str] = None,
        cap: Optional[int] = None,
    ) -> dict[str, list[dict]]:
        """Fetch every type of an export spec -> {short type: entities}."""
        result: dict[str, list[dict]] = {}
        for type_spec in types:
            name = getattr(type_spec, "name", None) or getattr(type_spec, "type", None)
            entities = self.get_entities(
                name,
                time_from=time_from,
                time_to=time_to,
                require_attr=require_attr,
                limit=cap,
            )
            result[name] = entities
            log.info("Scorpio %s: %d entities", name, len(entities))
        return result

    def verify_type(self, entity_type: str) -> tuple[str, int]:
        return self.resolve_stored_type(entity_type), self.count_by_type(entity_type)
