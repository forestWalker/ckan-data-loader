"""#3 Időjárási hatás a bio-részecskékre (legacy: export_idojarasi_hatas_bio_reszecskekre_csv.py).

Kept on the OVAK API: the joined ``BioParticlesObserved`` is not ingested into
Scorpio as a comparable type (no Bioparticle/Weather type pair there yet).
"""

from core.config import ChartSpec, ExportSpec, OvakStream
from core.ngsilib import chart_time, display_time

from ._shared import join_nearest, normalize_bio, normalize_weather

SPEC = ExportSpec(
    slug="idojarasi_hatas_bio_reszecskek",
    title="Időjárási hatás a bio-részecskékre",
    dataset="idojarasi-hatas-a-bio-reszecskekre",
    resource_title="Időjárási hatás a bio-részecskékre",
    fields=[
        "dateObserved", "chartTime", "weatherDateObserved", "timeDifferenceMinutes",
        "particleName", "particleType", "particleCount_count",
        "windSpeed_m_s", "windDirection_degrees", "rainfall_L_m2", "uVIndexMax",
        "relativeHumidity_percent", "temperature_Celsius",
        "pressure_hPa", "illuminance_lux",
    ],
    charts=[
        ChartSpec(
            title="Bio-részecskék és hőmérséklet kapcsolata",
            x="temperature_Celsius", y="particleCount_count", type="Scatter",
            x_label="Hőmérséklet (°C)", y_label="Bio-részecske darabszám",
        ),
    ],
    source="ovak",
    ovak_streams=[
        OvakStream(name="weather", kind="time",
                   endpoint="/api/v1/lumbara/weatherobserveds"),
        OvakStream(name="bio", kind="time",
                   endpoint="/api/v1/lumbara/bioparticlesobserveds"),
    ],
    window="today",
    max_gap_minutes=120.0,
    sort_tuple=("dateObserved", "particleName"),
    description="Bio-részecske-mérések összekapcsolva a legközelebbi időjárásméréssel.",
)


def build_rows(ctx) -> list[dict]:
    bio = normalize_bio(ctx.records("bio"))
    weather = normalize_weather(ctx.records("weather"))
    rows = join_nearest(
        bio, weather, ctx.spec.max_gap_minutes,
        left_time_col="dateObserved", right_time_col="weatherDateObserved",
    )
    for row in rows:
        row["chartTime"] = chart_time(row.get("dateObserved"))
        row["dateObserved"] = display_time(row.get("dateObserved"))
        row["weatherDateObserved"] = display_time(row.get("weatherDateObserved"))
    return rows
