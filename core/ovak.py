"""Read-side access to the OVAK external API for the exports that are not
(yet) ingested into Scorpio.

The hybrid source decision keeps four exports on the OVAK API directly:
``idojarasi_hatas_bio_reszecskek`` (#3), ``idojarassal_korrigalt_forgalom``
(#4), ``meteorologiai_kontextus`` (#8) and ``pollen_es_bio_reszecskek`` (#9).
Everything else reads Scorpio (ADR-003). The plan's ``pipelines.yaml`` can
flip an export to ``source: scorpio`` once ingestion catches up — the export
modules only see :class:`core.pipeline.ExportContext` and never the backend.

Paging mirrors the legacy scripts (stop when a page is shorter than
``page_size``). A duplicate-page guard breaks out when the OVAK server ignores
``PageNumber`` (SZTE-style endpoints return everything on page 1).
"""

from __future__ import annotations

import logging
import time
import urllib.parse
from datetime import datetime
from typing import Any, Optional

import httpx

from .config import Settings
from .ngsilib import api_time

log = logging.getLogger(__name__)

MAX_PAGES = 100000


class OVAKBackend:
    def __init__(self, settings: Settings):
        self._settings = settings
        self._client = httpx.Client(
            verify=False,
            timeout=settings.timeout,
            headers={
                "X-Api-Key": settings.ovak_key or "",
                "Accept": "application/ld+json",
                "User-Agent": "STiDS-CKAN-Exports/1.0",
            },
        )

    @property
    def base_url(self) -> str:
        return self._settings.ovak_source

    def close(self) -> None:
        self._client.close()

    def _get_json(self, url: str) -> list[dict]:
        last_error: Optional[Exception] = None
        for attempt in range(1, 5):
            try:
                resp = self._client.get(url)
            except Exception as e:
                last_error = e
                if attempt < 4:
                    time.sleep(attempt)
                    continue
                raise RuntimeError(f"OVAK kapcsolati hiba: {e}") from e
            if resp.is_success:
                try:
                    payload = resp.json()
                except ValueError:
                    raise RuntimeError(f"OVAK nem JSON válasz (HTTP {resp.status_code})")
                if isinstance(payload, list):
                    return payload
                if isinstance(payload, dict):
                    for key in ("items", "data", "results", "records"):
                        if isinstance(payload.get(key), list):
                            return payload[key]
                    # some endpoints (e.g. a single organization) return one
                    # record as a bare dict — wrap it like the legacy scripts
                    if "id" in payload:
                        return [payload]
                    raise RuntimeError("Az API válasza nem tartalmaz feldolgozható rekordlistát.")
                return []
            if 500 <= resp.status_code < 600 and attempt < 4:
                last_error = RuntimeError(f"OVAK HTTP {resp.status_code}")
                time.sleep(attempt * 2)
                continue
            raise RuntimeError(f"OVAK HTTP {resp.status_code}: {resp.text[:300]}")
        raise RuntimeError(f"OVAK request failed: {last_error}")

    def _paginate(self, path: str, query: dict[str, str], cap: Optional[int] = None) -> list[dict]:
        records: list[dict] = []
        page_size = self._settings.page_size
        if cap and cap < page_size:
            page_size = cap
        page = 1
        seen_first: Optional[set] = None
        while page <= MAX_PAGES:
            if cap is not None and len(records) >= cap:
                break
            params = dict(query)
            params.update({"PageNumber": str(page), "PageSize": str(page_size)})
            url = f"{self.base_url}{path}?{urllib.parse.urlencode(params)}"
            try:
                items = self._get_json(url)
            except RuntimeError as e:
                log.warning("OVAK %s page %d failed: %s", path, page, e)
                raise
            items = [item for item in items if isinstance(item, dict)]
            ids = {str(item.get("id", "")) for item in items}
            if page == 1:
                seen_first = ids
            elif seen_first is not None and ids and ids == seen_first:
                log.warning("OVAK %s: server ignores paging, deduplicating", path)
                break
            records.extend(items)
            if len(items) < page_size:
                break
            page += 1
            time.sleep(0.05)
        return records

    def _time_query(self, from_param: str, to_param: str, date_from: datetime, date_to: datetime) -> dict[str, str]:
        return {from_param: api_time(date_from), to_param: api_time(date_to)}

    def _fetch_org_devices(
        self,
        endpoint: str,
        organization_kind: str,
        data_path: str,
        date_from: datetime,
        date_to: datetime,
        cap: Optional[int] = None,
    ) -> list[dict]:
        orgs = self._paginate(f"/api/v1/{organization_kind}/organizations", {})
        records: list[dict] = []
        for org in orgs:
            if cap is not None and len(records) >= cap:
                break
            org_id = org.get("id")
            if not org_id:
                continue
            org_path = urllib.parse.quote(str(org_id), safe="")
            devices = self._paginate(
                f"/api/v1/{organization_kind}/organizations/{org_path}/devices", {}
            )
            for device in devices:
                if cap is not None and len(records) >= cap:
                    break
                device_id = device.get("id")
                if not device_id:
                    continue
                device_path = urllib.parse.quote(str(device_id), safe="")
                path = (
                    f"/api/v1/{organization_kind}/organizations/{org_path}"
                    f"/devices/{device_path}/{data_path}"
                )
                query = self._time_query("timeFrom", "timeTo", date_from, date_to)
                for item in self._paginate(path, query):
                    item = dict(item)
                    item["_deviceId"] = device_id
                    item["_orgId"] = org_id
                    records.append(item)
                    if cap is not None and len(records) >= cap:
                        break
        return records

    def _fetch_stoptimes(self, stream: Any, cap: Optional[int] = None) -> list[dict]:
        """Fetch ``gtfs/stoptimes`` per stop (StopId query), annotating ``_stopId``.

        Mirrors the legacy ``megallok_es_jaratsuruseg`` script: stops are listed
        once, then each stop's stop-times are fetched individually because the
        full ``gtfs/stoptimes`` set is too large for a single paginated call.
        """
        stops_path = (
            getattr(stream, "list_endpoint", "") or "/api/v1/gtfs/stops"
        )
        stops = self._paginate(stops_path, {})
        endpoint = getattr(stream, "endpoint", "")
        records: list[dict] = []
        for stop in stops:
            if cap is not None and len(records) >= cap:
                break
            stop_id = stop.get("id")
            if not stop_id:
                continue
            remaining = (cap - len(records)) if cap is not None else None
            for item in self._paginate(endpoint, {"StopId": str(stop_id)}, cap=remaining):
                item = dict(item)
                item["_stopId"] = stop_id
                records.append(item)
                if cap is not None and len(records) >= cap:
                    break
        return records

    def fetch_stream(
        self,
        stream: Any,
        date_from: datetime,
        date_to: datetime,
        cap: Optional[int] = None,
    ) -> list[dict]:
        kind = getattr(stream, "kind", "time")
        endpoint = getattr(stream, "endpoint", "")

        if kind == "org_devices":
            return self._fetch_org_devices(
                endpoint,
                getattr(stream, "organization_kind", "urbanalytics"),
                getattr(stream, "data_path", ""),
                date_from,
                date_to,
                cap=cap,
            )
        if kind == "org_devices_plain":
            return self._fetch_org_devices(
                endpoint,
                getattr(stream, "organization_kind", "urbanalytics"),
                getattr(stream, "data_path", ""),
                date_from,
                date_to,
                cap=cap,
            )
        if kind == "stoptimes":
            return self._fetch_stoptimes(stream, cap=cap)
        if kind in ("time", "time_span"):
            from_param = "DateFrom" if kind == "time" else "timeFrom"
            to_param = "DateTo" if kind == "time" else "timeTo"
            query = self._time_query(from_param, to_param, date_from, date_to)
            return self._paginate(endpoint, query, cap=cap)
        if kind == "list":
            return self._paginate(endpoint, {}, cap=cap)
        raise NotImplementedError(f"OVAK stream kind {kind!r} not supported")

    def fetch_streams(
        self,
        streams: list[Any],
        date_from: datetime,
        date_to: datetime,
        cap: Optional[int] = None,
    ) -> dict[str, list[dict]]:
        result: dict[str, list[dict]] = {}
        for stream in streams:
            name = getattr(stream, "name", None) or getattr(stream, "endpoint", "")
            records = self.fetch_stream(stream, date_from, date_to, cap=cap)
            result[name] = records
            log.info("OVAK %s: %d records", name, len(records))
        return result
