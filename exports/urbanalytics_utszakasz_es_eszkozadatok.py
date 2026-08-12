"""#11 Urbanalytics útszakasz- és eszközadatok (legacy: export_urbanalytics_utszakasz_es_eszkozadatok_csv.py)."""

from core.config import ChartSpec, ExportSpec, TypeSpec
from core.context import attr
from core.ngsilib import display_identifier

from ._shared import entity_map

SPEC = ExportSpec(
    slug="urbanalytics_utszakasz_es_eszkozadatok",
    title="Urbanalytics útszakasz- és eszközadatok",
    dataset="urbanalytics-utszakasz-es-eszkozadatok",
    resource_title="Urbanalytics útszakasz- és eszközadatok",
    fields=[
        "commuterId", "anonymizedId", "originRoadId", "originRoadName",
        "destinationRoadId", "destinationRoadName", "deviceId", "deviceName",
        "organizationId", "organizationName",
    ],
    charts=[
        ChartSpec(
            title="Forgalmi kapcsolatok kiinduló útszakaszonként",
            x="originRoadName", y="commuterId", type="Bar",
            x_label="Kiinduló útszakasz", y_label="Anonim áthaladások száma",
        ),
    ],
    source="scorpio",
    types=[
        TypeSpec(name="Organization", type="Organization"),
        TypeSpec(name="Device", type="Device"),
        TypeSpec(name="RoadSegment", type="RoadSegment"),
        TypeSpec(name="AnonymousCommuterId", type="AnonymousCommuterId"),
    ],
    window="all",
    sort_key="anonymizedId",
    description="Anonim ingázási kapcsolatok útszakasz- és eszközadatokkal (Urbanalytics).",
)


def build_rows(ctx) -> list[dict]:
    devices = entity_map(ctx.records("Device"))
    roads = entity_map(ctx.records("RoadSegment"))
    orgs = entity_map(ctx.records("Organization"))
    rows = []
    for commuter in ctx.records("AnonymousCommuterId"):
        origin_id = attr(commuter, "orig")
        destination_id = attr(commuter, "dest")
        origin = roads.get(origin_id, {})
        destination = roads.get(destination_id, {})
        device_id = attr(origin, "refDevice") or attr(destination, "refDevice")
        device = devices.get(device_id, {})
        org = orgs.get(attr(device, "owner"), {})
        rows.append({
            "commuterId": display_identifier(commuter.get("id")),
            "anonymizedId": display_identifier(attr(commuter, "anonymizedId")),
            "originRoadId": display_identifier(origin_id),
            "originRoadName": attr(origin, "name"),
            "destinationRoadId": display_identifier(destination_id),
            "destinationRoadName": attr(destination, "name"),
            "deviceId": display_identifier(device_id),
            "deviceName": attr(device, "name"),
            "organizationId": display_identifier(attr(device, "owner")),
            "organizationName": attr(org, "name"),
        })
    return rows
