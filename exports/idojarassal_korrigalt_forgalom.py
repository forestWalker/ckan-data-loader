"""#4 Időjárással korrigált forgalom – Urbanalytics (legacy: export_idojarassal_korrigalt_forgalom_csv.py).

Kept on the OVAK API: the join needs per-minute weather and the urbanalytics
traffic feed; the resulting comparison rows are not ingested into Scorpio.
"""

from core.config import ChartSpec, ExportSpec, OvakStream
from core.context import attr
from core.ngsilib import api_time, display_identifier, iso_datetime, traffic_time

SPEC = ExportSpec(
    slug="idojarassal_korrigalt_forgalom",
    title="Időjárással korrigált forgalom – Urbanalytics",
    dataset="idojarassal-korrigalt-forgalom-urbanalytics",
    resource_title="Időjárással korrigált forgalom – Urbanalytics",
    fields=[
        "dateObserved", "trafficTime", "chartTime", "weatherDateObserved", "timeDifferenceMinutes",
        "intensity", "vehicleType", "trafficDevice",
        "temperature", "relativeHumidity", "pressure", "windSpeed", "windDirection",
        "uVIndexMax", "illuminance", "weatherDevice",
        "comparisonScope",
    ],
    charts=[
        ChartSpec(
            title="Hőmérséklet és forgalmi intenzitás",
            x="temperature", y="intensity", type="Scatter",
            x_label="Hőmérséklet (°C)", y_label="Forgalmi intenzitás",
        ),
    ],
    source="ovak",
    ovak_streams=[
        OvakStream(name="weather", kind="time",
                   endpoint="/api/v1/lumbara/weatherobserveds"),
        OvakStream(name="traffic", kind="org_devices",
                   endpoint="trafficFlowObserveds",
                   organization_kind="urbanalytics",
                   data_path="trafficFlowObserveds"),
    ],
    window="today",
    max_gap_minutes=120.0,
    sort_key="trafficTime",
    description="Forgalmi intenzitás párosítva a legközelebbi időjárásméréssel.",
)


def build_rows(ctx) -> list[dict]:
    weather = ctx.records("weather")
    traffic = ctx.records("traffic")
    weather_times = [
        (iso_datetime(attr(item, "dateObserved")), item)
        for item in weather
        if attr(item, "dateObserved")
    ]
    rows = []
    for entity in traffic:
        observed = attr(entity, "dateObserved")
        if not observed or not weather_times:
            continue
        midpoint = traffic_time(observed)
        weather_dt, weather_entity = min(
            weather_times, key=lambda pair: abs(pair[0] - midpoint)
        )
        gap = abs((weather_dt - midpoint).total_seconds()) / 60
        if gap > ctx.spec.max_gap_minutes:
            continue
        rows.append({
            "dateObserved": observed,
            "trafficTime": api_time(midpoint),
            "chartTime": midpoint.strftime("%H:%M"),
            "weatherDateObserved": attr(weather_entity, "dateObserved"),
            "timeDifferenceMinutes": round(gap, 2),
            "intensity": attr(entity, "intensity"),
            "vehicleType": attr(entity, "vehicleType"),
            "trafficDevice": display_identifier(attr(entity, "_deviceId")),
            "temperature": attr(weather_entity, "temperature"),
            "relativeHumidity": attr(weather_entity, "relativeHumidity"),
            "pressure": attr(weather_entity, "pressure"),
            "windSpeed": attr(weather_entity, "windSpeed"),
            "windDirection": attr(weather_entity, "windDirection"),
            "uVIndexMax": attr(weather_entity, "uVIndexMax"),
            "illuminance": attr(weather_entity, "illuminance"),
            "weatherDevice": display_identifier(attr(weather_entity, "refDevice")),
            "comparisonScope": "nearest time; different measurement locations",
        })
    return rows
