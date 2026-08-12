"""Configuration: env-backed Settings plus the typed export spec model.

A :class:`ExportSpec` is defined in each ``exports/<slug>.py`` module and can be
tuned per-deployment through ``config/pipelines.yaml`` (source override, page
sizes, retention). The ``source`` field is the swappability point promised by
the plan: ``scorpio`` reads the NGSI-LD broker, ``ovak`` reads the OVAK API
directly (used today for the flows that are not (yet) ingested into Scorpio).
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, Optional

import yaml

APP_ROOT = Path(__file__).resolve().parent.parent
REPO_ROOT = APP_ROOT.parent.parent

Source = Literal["scorpio", "ovak"]

VALID_GROUPS = {"air-quality", "traffic", "public-transport"}

DEFAULT_ENV = {
    "OVAK_API_SOURCE": "https://ovakszeged.hu/test_stids_external_api",
    "OVAK_API_KEY": "",
    "CKAN_URL": "https://stids.ovakszeged.hu",
    "CKAN_ADMIN_PASSWORD": "",
    "CKAN_ADMIN_USER": "admin",
    "CKAN_API_TOKEN": "",
    "SCORPIO_URL": "https://stids-scorpio.ovakszeged.hu",
    "SCORPIO_TENANT": "default",
    "PAGE_SIZE": "500",
    "CKAN_CHUNK": "500",
    "CLEANUP_DAYS": "30",
}


@dataclass
class Settings:
    ovak_source: str
    ovak_key: str
    ckan_url: str
    ckan_admin_password: str
    ckan_admin_user: str = "admin"
    ckan_api_key: str = ""
    scorpio_url: str = ""
    scorpio_tenant: str = "default"
    page_size: int = 500
    ckan_chunk: int = 500
    cleanup_days: int = 30
    timeout: float = 60.0


def load_env(path: Optional[Path] = None) -> dict[str, str]:
    """Load ``KEY=VALUE`` pairs from a .env file (merged over process env)."""
    candidates: list[Path] = []
    if path:
        candidates.append(Path(path))
    else:
        candidates = [
            APP_ROOT / ".env",
            REPO_ROOT / ".env",
        ]
    values: dict[str, str] = {}
    for candidate in candidates:
        if not candidate.is_file():
            continue
        try:
            text = candidate.read_text(encoding="utf-8")
        except OSError:
            continue
        for raw in text.splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            values[key.strip()] = value.strip().strip('"').strip("'")
        break  # first existing file wins
    for key in tuple(values):
        if os.environ.get(key):
            values[key] = os.environ[key]
    return values


def load_settings(path: Optional[Path] = None) -> Settings:
    env = load_env(path)

    def get(key: str) -> str:
        return os.environ.get(key) or env.get(key) or DEFAULT_ENV.get(key, "")

    def get_int(key: str, default: int) -> int:
        try:
            return int(get(key))
        except (TypeError, ValueError):
            return default

    return Settings(
        ovak_source=get("OVAK_API_SOURCE").rstrip("/"),
        ovak_key=get("OVAK_API_KEY"),
        ckan_url=get("CKAN_URL").rstrip("/"),
        ckan_admin_password=get("CKAN_ADMIN_PASSWORD"),
        ckan_admin_user=get("CKAN_ADMIN_USER") or "admin",
        ckan_api_key=get("CKAN_API_TOKEN"),
        scorpio_url=get("SCORPIO_URL").rstrip("/"),
        scorpio_tenant=get("SCORPIO_TENANT") or "default",
        page_size=get_int("PAGE_SIZE", 500),
        ckan_chunk=get_int("CKAN_CHUNK", 500),
        cleanup_days=get_int("CLEANUP_DAYS", 30),
    )


@dataclass
class TypeSpec:
    """A single entity type to fetch from the backend."""

    name: str
    type: str
    attrs: list[str] = field(default_factory=list)
    url_encode: bool = True


@dataclass
class ChartSpec:
    title: str
    x: str
    y: str
    type: str
    x_label: str = ""
    y_label: str = ""


@dataclass
class OvakStream:
    """A single fetch stream from the OVAK API.

    ``kind`` selects the fetch strategy:
      - ``time``: paginated endpoint with ``DateFrom``/``DateTo`` (+PageNumber/PageSize)
      - ``time_span``: paginated endpoint with ``timeFrom``/``timeTo``
      - ``list``: plain paginated list (no time params)
      - ``gtfs``: paginated GTFS list (optional ``FeedId``)
      - ``stoptimes``: per-stop ``gtfs/stoptimes`` (StopId query)
      - ``org_devices``: organizations -> devices -> ``{data_path}`` with timeFrom/timeTo
      - ``org_devices_plain``: organizations -> devices -> roadSegments / commuters
    """

    name: str
    kind: str
    endpoint: str
    organization_kind: str = "urbanalytics"
    data_path: str = ""
    list_endpoint: str = ""


@dataclass
class ExportSpec:
    slug: str
    title: str
    dataset: str
    resource_title: str
    fields: list[str] = field(default_factory=list)
    charts: list[ChartSpec] = field(default_factory=list)
    source: Source = "scorpio"
    types: list[TypeSpec] = field(default_factory=list)
    ovak_streams: list[OvakStream] = field(default_factory=list)
    # "today" restricts the fetch to the current UTC day; "all" fetches everything
    window: str = "all"
    max_gap_minutes: float = 120.0
    sort_key: Optional[str] = None
    sort_tuple: tuple[str, ...] = ()
    # used by the Scorpio backend: keep only entities carrying this attribute
    require_attr: Optional[str] = None
    # optional per-export override of the backend page size (from pipelines.yaml)
    page_size: Optional[int] = None
    # which entity attribute carries the CKAN resource "created" timestamp
    # (a legacy AQI export stores it under "retention_test_created")
    created_key: str = "created"
    description: str = ""
    notes: str = ""

    @property
    def chart_specs(self) -> list[ChartSpec]:
        return self.charts

    @property
    def group(self) -> str:
        slug = self.slug.lower()
        if any(token in slug for token in (
                "idojaras", "meteorologia", "aqi", "pollen", "reszecske",
                "bio", "gazkomponensek")):
            return "air-quality"
        if any(token in slug for token in ("jarat", "megallo", "nyomvonal", "forgalom")):
            return "public-transport" if "jarat" in slug or "megallo" in slug else "traffic"
        return "traffic"


def group_for_slug(slug: str) -> str:
    spec = ExportSpec(slug=slug, title="", dataset="", resource_title="")
    group = spec.group
    return group if group in VALID_GROUPS else "traffic"


def load_pipelines(path: Optional[Path] = None) -> dict[str, Any]:
    """Load ``config/pipelines.yaml`` (empty dict when absent)."""
    candidate = path or APP_ROOT / "config" / "pipelines.yaml"
    if not candidate.is_file():
        return {}
    with candidate.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    return data or {}


def apply_pipelines(spec: ExportSpec, pipelines: dict[str, Any], settings: Settings) -> ExportSpec:
    """Overlay per-export settings from pipelines.yaml onto a spec."""
    defaults = pipelines.get("defaults", {}) or {}
    entry = (pipelines.get("exports", {}) or {}).get(spec.slug, {}) or {}
    merged = {**defaults, **entry}

    overrides = {
        "source": merged.get("source", spec.source),
        "window": merged.get("window", spec.window),
        "max_gap_minutes": merged.get("max_gap_minutes", spec.max_gap_minutes),
    }
    if "created_key" in merged:
        overrides["created_key"] = merged["created_key"]
    if "page_size" in merged:
        overrides["page_size"] = int(merged["page_size"])
    return dataclasses_replace(spec, **overrides)


def dataclasses_replace(spec: ExportSpec, **changes: Any) -> ExportSpec:
    return dataclass_replace(spec, **changes)


def dataclass_replace(spec: ExportSpec, **changes: Any) -> ExportSpec:
    values = {f: getattr(spec, f) for f in spec.__dataclass_fields__}
    values.update(changes)
    return ExportSpec(**values)
