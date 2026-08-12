"""#1 Anonimizált ingázási útvonalak – SZTE (legacy: export_anonimizalt_ingazasi_utvonalak_csv.py)."""

import json

from core.config import ChartSpec, ExportSpec, TypeSpec
from core.context import attr
from core.ngsilib import display_identifier

from ._shared import commuter_organization, entity_map, road_fields

SPEC = ExportSpec(
    slug="anonimizalt_ingazasi_utvonalak",
    title="Anonimizált ingázási útvonalak – SZTE",
    dataset="anonimizalt-ingazasi-utvonalak-szte",
    resource_title="Anonimizált ingázási útvonalak – SZTE",
    fields=[
        "commuterId", "anonymizedId", "originRoadSegmentId", "originRoadName",
        "originDeviceId", "originDeviceName",
        "destinationRoadSegmentId", "destinationRoadName",
        "destinationDeviceId", "destinationDeviceName",
        "organizationId", "organizationName",
    ],
    charts=[
        ChartSpec(
            title="Anonim ingázások induló útszakaszonként",
            x="originRoadName", y="commuterId", type="Bar",
            x_label="Induló útszakasz", y_label="Anonim utazások száma",
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
    description="Anonimizált ingázási útvonalak (SZTE), útszakasz- és eszközadatokkal kiegészítve.",
)


def build_rows(ctx) -> list[dict]:
    devices = entity_map(ctx.records("Device"))
    roads = entity_map(ctx.records("RoadSegment"))
    orgs = entity_map(ctx.records("Organization"))
    rows = []
    for commuter in ctx.records("AnonymousCommuterId"):
        origin_id = attr(commuter, "orig")
        destination_id = attr(commuter, "dest")
        org_id = commuter_organization(origin_id, destination_id, roads, devices)
        row = {
            "commuterId": display_identifier(commuter.get("id")),
            "anonymizedId": display_identifier(attr(commuter, "anonymizedId")),
            "originRoadSegmentId": display_identifier(origin_id),
            "destinationRoadSegmentId": display_identifier(destination_id),
            "organizationId": display_identifier(org_id),
            "organizationName": attr(orgs.get(org_id, {}), "name"),
        }
        row.update(road_fields("origin", roads.get(origin_id), devices))
        row.update(road_fields("destination", roads.get(destination_id), devices))
        rows.append(row)
    return rows
