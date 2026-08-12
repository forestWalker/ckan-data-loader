"""#10 Forgalom útszakaszadatokkal – Urbanalytics (legacy: export_urbanalytics_forgalom_utszakaszokkal_csv.py)."""

from core.config import ChartSpec, ExportSpec, TypeSpec
from core.context import attr
from core.ngsilib import chart_time, display_identifier

from ._shared import entity_map

SPEC = ExportSpec(
    slug="urbanalytics_forgalom_utszakaszokkal",
    title="Forgalom útszakaszadatokkal – Urbanalytics",
    dataset="forgalom-utszakaszadatokkal-urbanalytics",
    resource_title="Forgalom útszakaszadatokkal – Urbanalytics",
    fields=[
        "dateObserved", "chartTime", "intensity", "vehicleType", "trafficId", "commuterId",
        "originRoadId", "originRoadName", "destinationRoadId", "destinationRoadName",
        "refDevice", "deviceName",
        "organizationId", "organizationName",
    ],
    charts=[
        ChartSpec(
            title="Forgalmi intenzitás útszakaszonként",
            x="originRoadName", y="intensity", type="Bar",
            x_label="Kiinduló útszakasz", y_label="Forgalmi intenzitás",
        ),
    ],
    source="scorpio",
    types=[
        TypeSpec(name="Organization", type="Organization"),
        TypeSpec(name="Device", type="Device"),
        TypeSpec(name="RoadSegment", type="RoadSegment"),
        TypeSpec(name="AnonymousCommuterId", type="AnonymousCommuterId"),
        TypeSpec(name="TrafficFlowObserved", type="TrafficFlowObserved"),
    ],
    window="today",
    sort_key="dateObserved",
    description="Forgalmi mérések commuter-, útszakasz-, eszköz- és szervezetadatokkal.",
)


def build_rows(ctx) -> list[dict]:
    commuters = entity_map(ctx.records("AnonymousCommuterId"))
    roads = entity_map(ctx.records("RoadSegment"))
    devices = entity_map(ctx.records("Device"))
    orgs = entity_map(ctx.records("Organization"))
    rows = []
    for entity in ctx.records("TrafficFlowObserved"):
        commuter = commuters.get(attr(entity, "seeAlso"), {})
        origin_id = attr(commuter, "orig")
        destination_id = attr(commuter, "dest")
        device = devices.get(attr(entity, "refDevice"), {})
        org = orgs.get(attr(device, "owner"), {})
        rows.append({
            "dateObserved": attr(entity, "dateObserved"),
            "chartTime": chart_time(attr(entity, "dateObserved")),
            "intensity": attr(entity, "intensity"),
            "vehicleType": attr(entity, "vehicleType"),
            "trafficId": display_identifier(entity.get("id")),
            "commuterId": display_identifier(commuter.get("id")),
            "originRoadId": display_identifier(origin_id),
            "originRoadName": attr(roads.get(origin_id, {}), "name"),
            "destinationRoadId": display_identifier(destination_id),
            "destinationRoadName": attr(roads.get(destination_id, {}), "name"),
            "refDevice": display_identifier(attr(entity, "refDevice")),
            "deviceName": attr(device, "name"),
            "organizationId": display_identifier(attr(device, "owner")),
            "organizationName": attr(org, "name"),
        })
    return rows
