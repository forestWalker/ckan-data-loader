"""Export pipeline modules.

Each module exposes a module-level ``SPEC`` (an :class:`~core.config.ExportSpec`)
plus a ``build_rows(ctx)`` function. The pipeline fetches the entities declared
by the spec (from Scorpio or the OVAK API, per the resolved source) and feeds
them to ``build_rows`` through an :class:`~core.pipeline.ExportContext`.
"""

from importlib import import_module

from core.config import ExportSpec

EXPORT_MODULES: dict[str, str] = {
    "anonimizalt_ingazasi_utvonalak": "exports.anonimizalt_ingazasi_utvonalak",
    "aqi_pm_gazkomponensek": "exports.aqi_pm_gazkomponensek",
    "idojarasi_hatas_bio_reszecskek": "exports.idojarasi_hatas_bio_reszecskek",
    "idojarassal_korrigalt_forgalom": "exports.idojarassal_korrigalt_forgalom",
    "jaratok_nyomvonala_terkepen": "exports.jaratok_nyomvonala_terkepen",
    "jarmuforgalom_urbanalytics": "exports.jarmuforgalom_urbanalytics",
    "megallok_es_jaratsuruseg": "exports.megallok_es_jaratsuruseg",
    "meteorologiai_kontextus": "exports.meteorologiai_kontextus",
    "pollen_es_bio_reszecskek": "exports.pollen_es_bio_reszecskek",
    "urbanalytics_forgalom_utszakaszokkal": "exports.urbanalytics_forgalom_utszakaszokkal",
    "urbanalytics_utszakasz_es_eszkozadatok": "exports.urbanalytics_utszakasz_es_eszkozadatok",
}

# Official slugs (must match the CronJob / script names).
SLUGS: list[str] = [
    "anonimizalt_ingazasi_utvonalak",
    "aqi_pm_gazkomponensek",
    "idojarasi_hatas_bio_reszecskek",
    "idojarassal_korrigalt_forgalom",
    "jaratok_nyomvonala_terkepen",
    "jarmuforgalom_urbanalytics",
    "megallok_es_jaratsuruseg",
    "meteorologiai_kontextus",
    "pollen_es_bio_reszecskek",
    "urbanalytics_forgalom_utszakaszokkal",
    "urbanalytics_utszakasz_es_eszkozadatok",
]


def load_export(slug: str) -> ExportSpec:
    if slug not in EXPORT_MODULES:
        raise KeyError(f"Unknown export slug: {slug!r}")
    module = import_module(EXPORT_MODULES[slug])
    return module.SPEC
