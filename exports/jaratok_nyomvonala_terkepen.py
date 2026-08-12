"""#5 Járatok nyomvonala térképen (legacy: export_jaratok_nyomvonala_terkepen_csv.py)."""

import json

from core.config import ChartSpec, ExportSpec, TypeSpec
from core.context import attr
from core.ngsilib import display_identifier

from ._shared import entity_map

SPEC = ExportSpec(
    slug="jaratok_nyomvonala_terkepen",
    title="Járatok nyomvonala térképen",
    dataset="jaratok-nyomvonala-terkepen",
    resource_title="Járatok nyomvonala térképen",
    fields=[
        "tripId", "headSign", "direction", "routeId", "routeShortName", "routeType",
        "agencyId", "shapeId", "shapeGeoJson", "shapePointCount",
    ],
    charts=[
        ChartSpec(
            title="Indulások járatonként",
            x="routeShortName", y="tripId", type="Bar",
            x_label="Járat", y_label="Indulások száma",
        ),
    ],
    source="scorpio",
    types=[
        TypeSpec(name="GtfsTrip", type="GtfsTrip"),
        TypeSpec(name="GtfsRoute", type="GtfsRoute"),
        TypeSpec(name="GtfsShape", type="GtfsShape"),
    ],
    window="all",
    sort_tuple=("routeShortName", "tripId"),
    description="GTFS járatok nyomvonalai térképen (trip -> route -> shape).",
)


def build_rows(ctx) -> list[dict]:
    route_map = entity_map(ctx.records("GtfsRoute"))
    shape_map = entity_map(ctx.records("GtfsShape"))
    rows = []
    for trip in ctx.records("GtfsTrip"):
        route_id = attr(trip, "hasRoute")
        shape_id = attr(trip, "hasShape")
        shape = shape_map.get(shape_id)
        if not shape:
            continue
        route = route_map.get(route_id, {})
        geometry = attr(shape, "location")
        coordinates = geometry.get("coordinates", []) if isinstance(geometry, dict) else []
        rows.append({
            "tripId": display_identifier(trip.get("id")),
            "headSign": attr(trip, "headSign"),
            "direction": attr(trip, "direction"),
            "routeId": display_identifier(route_id),
            "routeShortName": attr(route, "shortName"),
            "routeType": attr(route, "routeType"),
            "agencyId": display_identifier(attr(route, "operatedBy")),
            "shapeId": display_identifier(shape_id),
            "shapeGeoJson": json.dumps(geometry, ensure_ascii=False, separators=(",", ":")),
            "shapePointCount": len(coordinates),
        })
    return rows
