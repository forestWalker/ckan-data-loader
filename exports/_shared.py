"""Shared row-building helpers used by several export modules.

Behavioural ports of the corresponding blocks of the legacy scripts
(``normalize_weather``/``normalize_bio``/``join_nearest`` from
``export_idojarasi_hatas_bio_reszecskekre_csv.py`` and the ``road_fields``
helper from ``export_anonimizalt_ingazasi_utvonalak_csv.py``). The ``attr``
lookups keep the modules source-agnostic (Scorpio stores attributes under
expanded IRIs; the OVAK API returns short names).
"""

from __future__ import annotations

from collections import Counter
from typing import Any, Optional

from core.context import attr
from core.ngsilib import display_identifier, iso_datetime


def normalize_weather(entities: list[dict]) -> list[dict]:
    """Flatten a lumbara weather list into the shared weather-row shape."""
    rows = []
    for entity in entities:
        rainfall = attr(entity, "rainfall")
        if rainfall is None:
            rainfall = attr(entity, "precipitation")
        rows.append({
            "weatherDateObserved": attr(entity, "dateObserved"),
            "windSpeed_m_s": attr(entity, "windSpeed"),
            "windDirection_degrees": attr(entity, "windDirection"),
            "rainfall_L_m2": rainfall,
            "uVIndexMax": attr(entity, "uVIndexMax"),
            "relativeHumidity_percent": attr(entity, "relativeHumidity"),
            "temperature_Celsius": attr(entity, "temperature"),
            "pressure_hPa": attr(entity, "pressure"),
            "illuminance_lux": attr(entity, "illuminance"),
        })
    return rows


def normalize_bio(entities: list[dict]) -> list[dict]:
    """Expand the nested ``BioParticlesObserved`` array into one row per particle."""
    rows = []
    for entity in entities:
        particles = attr(entity, "BioParticlesObserved")
        if not isinstance(particles, list):
            continue
        for particle in particles:
            if not isinstance(particle, dict):
                continue
            rows.append({
                "dateObserved": attr(entity, "dateObserved"),
                "particleName": particle.get("name"),
                "particleType": (
                    particle.get("particleType")
                    or particle.get("type")
                    or particle.get("@type")
                ),
                "particleCount_count": particle.get("count"),
            })
    return rows


def join_nearest(
    left: list[dict],
    right: list[dict],
    max_gap_minutes: float,
    left_time_col: str,
    right_time_col: str,
) -> list[dict]:
    """Join every left row to the temporally nearest right row (legacy semantics).

    Mirrors the legacy ``join_nearest``: for each left row the right record
    whose ``right_time_col`` is closest to the left row's ``left_time_col`` is
    merged into the row; rows whose nearest gap exceeds ``max_gap_minutes`` are
    dropped. ``timeDifferenceMinutes`` is the rounded absolute gap.
    """
    right_times = [
        (iso_datetime(row[right_time_col]), row)
        for row in right
        if row.get(right_time_col)
    ]
    output = []
    for left_row in left:
        if not left_row.get(left_time_col) or not right_times:
            continue
        left_time = iso_datetime(left_row[left_time_col])
        right_time, right_row = min(
            right_times, key=lambda item: abs(item[0] - left_time)
        )
        gap = abs((right_time - left_time).total_seconds()) / 60
        if gap > max_gap_minutes:
            continue
        row = dict(left_row)
        row.update(right_row)
        row["timeDifferenceMinutes"] = round(gap, 2)
        output.append(row)
    return output


def entity_map(records: list[dict]) -> dict[str, dict]:
    """Index records by their ``id`` (as the legacy ``{item.get("id"): item}``)."""
    return {item.get("id"): item for item in records if item.get("id")}


def road_fields(prefix: str, road: Optional[dict], devices: dict[str, dict]) -> dict[str, Any]:
    """Origin/destination road + device fields for the commuter exports."""
    if not road:
        return {f"{prefix}RoadName": None}
    device_id = attr(road, "refDevice")
    device = devices.get(device_id, {})
    return {
        f"{prefix}RoadName": attr(road, "name"),
        f"{prefix}DeviceId": display_identifier(device_id),
        f"{prefix}DeviceName": attr(device, "name"),
    }


def commuter_organization(
    origin_id: Any,
    destination_id: Any,
    roads: dict[str, dict],
    devices: dict[str, dict],
) -> Any:
    """Organization of a commuter via its road segments -> device -> owner.

    The Scorpio model links commuters to a device only indirectly: a commuter
    references road segments (``orig``/``dest``), a road segment references a
    device (``refDevice``) and the device references the organization
    (``owner``). This mirrors what the legacy scripts got for free from the
    per-organization fetch loop.
    """
    for road_id in (origin_id, destination_id):
        road = roads.get(road_id)
        if not road:
            continue
        owner = attr(devices.get(attr(road, "refDevice"), {}), "owner")
        if owner:
            return owner
    return None


def count_by_trip(
    stoptimes: list[dict],
    trip_to_route: dict[str, Any],
    stop_attr: str = "_stopId",
) -> dict[Any, Counter]:
    """Group stoptime rows by stop id, counting trips per route (legacy #7).

    ``stop_attr`` selects the stop reference: the OVAK ``gtfs/stoptimes``
    stream annotates ``_stopId`` on each row, while Scorpio ``GtfsStopTime``
    entities carry the ``hasStop`` relationship.
    """
    stop_counts: dict[Any, Counter] = {}
    for item in stoptimes:
        stop_id = attr(item, stop_attr)
        route_id = trip_to_route.get(attr(item, "hasTrip"))
        stop_counts.setdefault(stop_id, Counter())[route_id] += 1
    return stop_counts
