"""#2 AQI, PM és gázkomponensek (legacy: export_aqi_pm_gazkomponensek_csv.py).

Reads ``AirQualityObserved`` from Scorpio (the ritek AQI ingest). The legacy
script kept the CKAN resource retention timestamp under a non-standard extra
field (``retention_test_created``), which is why ``created_key`` chains both.
"""

from core.config import ChartSpec, ExportSpec, TypeSpec
from core.context import attr
from core.ngsilib import chart_time, display_time

SPEC = ExportSpec(
    slug="aqi_pm_gazkomponensek",
    title="AQI, PM és gázkomponensek",
    dataset="aqi-pm1-pm25-pm10-gazkomponensek",
    resource_title="AQI, PM és gázkomponensek",
    fields=[
        "dateObserved", "chartTime",
        "pm1_ug_m3", "pm25_ug_m3", "pm10_ug_m3", "NOx_ug_m3",
        "temperature_Celsius", "relativeHumidity_fraction",
        "atmosphericPressure_A97",
    ],
    charts=[
        ChartSpec("PM1-koncentráció alakulása", "chartTime", "pm1_ug_m3", "Line",
                  "Időpont", "PM1 koncentráció (µg/m³)"),
        ChartSpec("PM2.5-koncentráció alakulása", "chartTime", "pm25_ug_m3", "Line",
                  "Időpont", "PM2.5 koncentráció (µg/m³)"),
        ChartSpec("PM10-koncentráció alakulása", "chartTime", "pm10_ug_m3", "Line",
                  "Időpont", "PM10 koncentráció (µg/m³)"),
        ChartSpec("NOx-koncentráció alakulása", "chartTime", "NOx_ug_m3", "Line",
                  "Időpont", "NOx koncentráció (µg/m³)"),
    ],
    source="scorpio",
    types=[
        TypeSpec(name="AirQualityObserved", type="AirQualityObserved"),
    ],
    window="today",
    sort_key="dateObserved",
    created_key="retention_test_created or created",
    description="AQI (PM1, PM2.5, PM10, NOx) és gázkomponensek percenkénti mérése.",
)


def build_rows(ctx) -> list[dict]:
    rows = []
    for entity in ctx.records("AirQualityObserved"):
        rows.append({
            "dateObserved": display_time(attr(entity, "dateObserved")),
            "chartTime": chart_time(attr(entity, "dateObserved")),
            "pm1_ug_m3": attr(entity, "pm1"),
            "pm25_ug_m3": attr(entity, "pm25"),
            "pm10_ug_m3": attr(entity, "pm10"),
            "NOx_ug_m3": attr(entity, "NOx"),
            "temperature_Celsius": attr(entity, "temperature"),
            "relativeHumidity_fraction": attr(entity, "relativeHumidity"),
            "atmosphericPressure_A97": attr(entity, "atmosphericPressure"),
        })
    return rows
