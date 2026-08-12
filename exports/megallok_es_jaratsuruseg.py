"""#7 Megállók és járatsűrűség (legacy: export_megallok_es_jaratsuruseg_csv.py).

Reads the GTFS static model from Scorpio: every ``GtfsStopTime`` is grouped by
its ``hasStop``/``hasTrip`` relationship and each trip is attributed to the
route it belongs to (``GtfsTrip.hasRoute``), so the row count equals the number
of trips serving a stop per route. Stop/route display names come from
``GtfsStop``/``GtfsRoute``.
"""

from core.config import ChartSpec, ExportSpec, TypeSpec
from core.context import attr
from core.ngsilib import display_identifier

from ._shared import count_by_trip, entity_map

SPEC = ExportSpec(
    slug="megallok_es_jaratsuruseg",
    title="Megállók és járatsűrűség",
    dataset="megallok-es-jaratsuruseg",
    resource_title="Megállók és járatsűrűség",
    fields=[
        "stopId", "stopName", "routeId",
        "routeShortName", "routeType", "agencyId", "tripCount",
    ],
    charts=[
        ChartSpec(
            title="Járatsűrűség megállónként",
            x="stopName", y="tripCount", type="Bar",
            x_label="Megálló", y_label="Napi járatszám",
        ),
    ],
    source="scorpio",
    types=[
        TypeSpec(name="GtfsStop", type="GtfsStop"),
        TypeSpec(name="GtfsTrip", type="GtfsTrip"),
        TypeSpec(name="GtfsRoute", type="GtfsRoute"),
        TypeSpec(name="GtfsStopTime", type="GtfsStopTime"),
    ],
    window="all",
    sort_tuple=("stopName", "routeShortName"),
    description="Napi járatszám megállónként és járatonként (GTFS stop-time számlálás).",
)


def build_rows(ctx) -> list[dict]:
    stops = entity_map(ctx.records("GtfsStop"))
    routes = entity_map(ctx.records("GtfsRoute"))
    trip_to_route = {
        item.get("id"): attr(item, "hasRoute")
        for item in ctx.records("GtfsTrip")
    }
    stop_counts = count_by_trip(ctx.records("GtfsStopTime"), trip_to_route, stop_attr="hasStop")
    rows = []
    for stop_id, counts in stop_counts.items():
        stop = stops.get(stop_id, {})
        for route_id, count in counts.items():
            route = routes.get(route_id, {})
            rows.append({
                "stopId": display_identifier(stop_id),
                "stopName": attr(stop, "name"),
                "routeId": display_identifier(route_id),
                "routeShortName": attr(route, "shortName"),
                "routeType": attr(route, "routeType"),
                "agencyId": display_identifier(attr(route, "operatedBy")),
                "tripCount": count,
            })
    return rows
