"""NGSI-LD value helpers shared by every export.

These mirror the behaviour of the legacy ``export_*_csv.py`` scripts (same
``unwrap``/``point``/``display_identifier``/date-formatting semantics) so that
the standardized pipeline produces byte-identical CSV rows.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any


def unwrap(value: Any, depth: int = 4) -> Any:
    """Unwrap NGSI-LD ``Property``/``Relationship`` wrappers down to the value.

    Mirrors the legacy helper: a list unwraps its single element (or every
    element), a dict unwraps through ``value``/``object``/``@value`` keys.
    """
    for _ in range(depth):
        if isinstance(value, list):
            if not value:
                return None
            return unwrap(value[0]) if len(value) == 1 else [unwrap(item) for item in value]
        if isinstance(value, dict):
            for key in ("value", "object", "@value"):
                if key in value:
                    value = value[key]
                    break
            else:
                break
        else:
            break
    return value


def point(value: Any) -> tuple[Any, Any]:
    """Extract ``(longitude, latitude)`` from a GeoProperty value."""
    value = unwrap(value)
    coordinates = value.get("coordinates", []) if isinstance(value, dict) else []
    return (coordinates[0], coordinates[1]) if len(coordinates) >= 2 else (None, None)


def display_identifier(value: Any) -> str:
    """Human-readable tail of an NGSI/URN identifier."""
    value = unwrap(value)
    if value is None:
        return ""
    text = str(value)
    return text.rsplit(":", 1)[-1] if text.lower().startswith("urn:") else text


def iso_datetime(value: Any) -> datetime:
    """Parse an ISO-8601 string (with ``Z``) into a tz-aware datetime."""
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _interval_parts(value: Any) -> list[str]:
    text = str(value)
    return text.split("/", 1)


def display_time(value: Any) -> str:
    """Format a date as ``%Y.%m.%d %H:%M`` (intervals joined with `` - ``)."""
    if not value:
        return ""
    parts = _interval_parts(unwrap(value))
    return " - ".join(iso_datetime(part).strftime("%Y.%m.%d %H:%M") for part in parts)


def chart_time(value: Any) -> str:
    """Format the interval start (or the single instant) as ``%H:%M``."""
    if not value:
        return ""
    start = _interval_parts(unwrap(value))[0]
    return iso_datetime(start).strftime("%H:%M")


def traffic_time(value: Any) -> datetime:
    """Midpoint of a ``start/end`` interval, or the instant itself."""
    parts = _interval_parts(unwrap(value))
    if len(parts) < 2:
        return iso_datetime(parts[0])
    start, end = (iso_datetime(part) for part in parts)
    return start + (end - start) / 2


def api_time(value: datetime) -> str:
    """Serialize a datetime to an ISO-8601 UTC string ending in ``Z``."""
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def record_key(row: dict, fields: list[str]) -> str:
    """Deterministic SHA-256 over the row's field values (idempotency key)."""
    payload = json.dumps(
        {name: row.get(name, "") for name in fields},
        ensure_ascii=False,
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def infer_field_types(rows: list[dict], fields: list[str]) -> dict[str, str]:
    """Infer CKAN DataStore field types: ``numeric`` when every value is a float."""
    types: dict[str, str] = {}
    for name in fields:
        values = [
            str(row.get(name, "")).strip()
            for row in rows
            if str(row.get(name, "")).strip()
        ]
        field_type = "text"
        if values:
            try:
                for value in values:
                    float(value)
                field_type = "numeric"
            except ValueError:
                pass
        types[name] = field_type
    return types


def convert_record(row: dict, field_types: dict[str, str], fields: list[str]) -> dict:
    """Convert a CSV row to the CKAN DataStore record (with ``recordKey``)."""
    record: dict[str, Any] = {"recordKey": record_key(row, fields)}
    for name in fields:
        value = row.get(name, "")
        if value in (None, ""):
            record[name] = None
        elif field_types.get(name) == "numeric":
            record[name] = float(value)
        else:
            record[name] = str(value)
    return record
