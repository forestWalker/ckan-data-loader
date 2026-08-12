"""#8 Meteorológiai kontextus (legacy: export_meteorologiai_kontextus_csv.py).

Kept on the OVAK API: the lumbara weather observations are not (yet) ingested
into Scorpio (no ``WeatherObserved`` type in the broker).
"""

from core.config import ChartSpec, ExportSpec, OvakStream
from core.context import attr
from core.ngsilib import chart_time, display_time

SPEC = ExportSpec(
    slug="meteorologiai_kontextus",
    title="Meteorológiai kontextus",
    dataset="meteorologiai-kontextus",
    resource_title="Meteorológiai kontextus",
    fields=[
        "dateObserved", "chartTime", "temperature_Celsius", "relativeHumidity_percent",
        "pressure_hPa", "windSpeed_m_s", "windDirection_degrees",
        "rainfall_L_m2", "uVIndexMax", "illuminance_lux", "typeofLocation",
    ],
    charts=[
        ChartSpec(
            title="Hőmérséklet alakulása",
            x="chartTime", y="temperature_Celsius", type="Line",
            x_label="Időpont (óra:perc)", y_label="Hőmérséklet (°C)",
        ),
    ],
    source="ovak",
    ovak_streams=[
        OvakStream(name="weather", kind="time",
                   endpoint="/api/v1/lumbara/weatherobserveds"),
    ],
    window="today",
    sort_key="dateObserved",
    description="Meteorológiai kontextus: hőmérséklet, páratartalom, légnyomás, szél, csapadék.",
)


def build_rows(ctx) -> list[dict]:
    rows = []
    for entity in ctx.records("weather"):
        rainfall = attr(entity, "rainfall")
        if rainfall is None:
            rainfall = attr(entity, "precipitation")
        rows.append({
            "dateObserved": display_time(attr(entity, "dateObserved")),
            "chartTime": chart_time(attr(entity, "dateObserved")),
            "temperature_Celsius": attr(entity, "temperature"),
            "relativeHumidity_percent": attr(entity, "relativeHumidity"),
            "pressure_hPa": attr(entity, "pressure"),
            "windSpeed_m_s": attr(entity, "windSpeed"),
            "windDirection_degrees": attr(entity, "windDirection"),
            "rainfall_L_m2": rainfall,
            "uVIndexMax": attr(entity, "uVIndexMax"),
            "illuminance_lux": attr(entity, "illuminance"),
            "typeofLocation": attr(entity, "typeofLocation"),
        })
    return rows
