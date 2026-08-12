"""#6 Járműforgalom – Urbanalytics (legacy: export_jarmuforgalom_urbanalytics_csv.py)."""

from core.config import ChartSpec, ExportSpec, TypeSpec
from core.context import attr
from core.ngsilib import chart_time, display_time

from ._shared import entity_map

SPEC = ExportSpec(
    slug="jarmuforgalom_urbanalytics",
    title="Járműforgalom – Urbanalytics",
    dataset="jarmuforgalom-urbanalytics",
    resource_title="Járműforgalom – Urbanalytics",
    fields=[
        "dateObserved", "chartTime", "intensity_vehicles", "vehicleType", "deviceName",
        "roadSegment", "organizationName",
    ],
    charts=[
        ChartSpec(
            title="Járműforgalom időbeli alakulása",
            x="chartTime", y="intensity_vehicles", type="Line",
            x_label="Időpont (óra:perc)", y_label="Észlelt járművek száma",
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
    description="Járműforgalmi mérések eszköz-, útszakasz- és szervezetadatokkal.",
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
        origin_name = attr(roads.get(origin_id, {}), "name")
        destination_name = attr(roads.get(destination_id, {}), "name")
        road_segment = " → ".join(
            name for name in (origin_name, destination_name) if name
        )
        device = devices.get(attr(entity, "refDevice"), {})
        org = orgs.get(attr(device, "owner"), {})
        rows.append({
            "dateObserved": display_time(attr(entity, "dateObserved")),
            "chartTime": chart_time(attr(entity, "dateObserved")),
            "intensity_vehicles": attr(entity, "intensity"),
            "vehicleType": attr(entity, "vehicleType"),
            "deviceName": attr(device, "name"),
            "roadSegment": road_segment,
            "organizationName": attr(org, "name"),
        })
    return rows
