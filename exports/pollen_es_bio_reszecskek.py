"""#9 Pollen- és bio-részecskék (legacy: export_pollen_es_bio_reszecskek_csv.py).

Kept on the OVAK API: the nested ``BioParticlesObserved`` observations are not
ingested into Scorpio as a comparable type.
"""

from core.config import ChartSpec, ExportSpec, OvakStream
from core.context import attr
from core.ngsilib import chart_time, display_time

SPEC = ExportSpec(
    slug="pollen_es_bio_reszecskek",
    title="Pollen- és bio-részecskék",
    dataset="pollen-es-bio-reszecskek",
    resource_title="Pollen- és bio-részecskék",
    fields=[
        "dateObserved", "chartTime", "particleName", "particleType", "particleCount_count",
        "alternateName", "typeofLocation",
    ],
    charts=[
        ChartSpec(
            title="Pollen- és bio-részecske szintek",
            x="particleName", y="particleCount_count", type="Bar",
            x_label="Részecske neve", y_label="Mért darabszám",
        ),
    ],
    source="ovak",
    ovak_streams=[
        OvakStream(name="bio", kind="time",
                   endpoint="/api/v1/lumbara/bioparticlesobserveds"),
    ],
    window="today",
    sort_tuple=("dateObserved", "particleName"),
    description="Pollen- és bio-részecske szintek (nested BioParticlesObserved tömb).",
)


def build_rows(ctx) -> list[dict]:
    rows = []
    for entity in ctx.records("bio"):
        particles = attr(entity, "BioParticlesObserved")
        if not isinstance(particles, list):
            continue
        for particle in particles:
            if not isinstance(particle, dict):
                continue
            rows.append({
                "dateObserved": display_time(attr(entity, "dateObserved")),
                "chartTime": chart_time(attr(entity, "dateObserved")),
                "particleName": particle.get("name"),
                "particleType": (
                    particle.get("particleType")
                    or particle.get("type")
                    or particle.get("@type")
                ),
                "particleCount_count": particle.get("count"),
                "alternateName": attr(entity, "alternateName"),
                "typeofLocation": attr(entity, "typeofLocation"),
            })
    return rows
