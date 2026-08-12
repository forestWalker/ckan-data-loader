"""Pipeline orchestrator for the standardized CKAN exports.

Replaces the eleven legacy ``export_*_csv.py`` scripts (block 4 in
``dsc-setup/k8s-resources/ckan-nifi/python scripts``) with one binary, one
config file and one export module per dataset.

CLI
---
``ckan-exports list``                                  list available slugs
``ckan-exports run <slug> [--date-from ...] [--date-to ...]``
    [--dry-run] [--sample N] [--show-types] [--csv-out PATH]
    [--debug] [-v] [-q]

The summary line is printed to stdout (the CronJob/script wrappers parse it):

    export=<slug> window=<from>/<to> fetched=N assembled=N published=N \
    dedup=N cleanup=N duration=<s>s exit=<code>

Exit codes (per the standardized pipeline plan, §7.4):

    0  ok
    1  unexpected error
    2  fetch / assembly error
    3  nothing to publish
    4  CKAN error
"""

from __future__ import annotations

import argparse
import csv
import importlib
import logging
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional
from zoneinfo import ZoneInfo

from exports import EXPORT_MODULES, SLUGS

from .ckan_exports import CKANExportsClient
from .config import ExportSpec, Settings, apply_pipelines, load_pipelines, load_settings
from .logging_setup import setup_logging
from .ngsilib import api_time
from .ovak import OVAKBackend
from .scorpio import ScorpioBackend

log = logging.getLogger("ckan_exports")

BUDAPEST = ZoneInfo("Europe/Budapest")

EXIT_OK = 0
EXIT_UNEXPECTED = 1
EXIT_FETCH = 2
EXIT_EMPTY = 3
EXIT_CKAN = 4

# OVAK "time" streams always receive a concrete window; when an export has no
# window (spec.window == "all") a far-past start keeps the query well-defined.
_OVAK_HISTORICAL_START = datetime(2020, 1, 1, tzinfo=timezone.utc)


def _parse_datetime(text: str) -> datetime:
    parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=BUDAPEST)


@dataclass
class ExportContext:
    """Everything an export module's ``build_rows(ctx)`` may touch.

    ``records(name)`` returns the fetched entities/records for a type name
    (Scorpio source) or a stream name (OVAK source), so modules stay
    source-agnostic.
    """

    spec: ExportSpec
    settings: Settings
    date_from: Optional[datetime]
    date_to: Optional[datetime]
    entities: dict[str, list[dict]] = field(default_factory=dict)
    streams: dict[str, list[dict]] = field(default_factory=dict)
    limit: Optional[int] = None

    def records(self, name: str) -> list[dict]:
        if name in self.streams:
            return self.streams[name]
        if name in self.entities:
            return self.entities[name]
        return []

    @property
    def fetched(self) -> int:
        return sum(len(items) for items in self.entities.values()) + sum(
            len(items) for items in self.streams.values()
        )


def _default_window(spec: ExportSpec, date_from: Optional[datetime], date_to: Optional[datetime]):
    now = datetime.now(BUDAPEST)
    if date_from is None and spec.window != "all":
        date_from = now.replace(hour=0, minute=0, second=0, microsecond=0)
    if date_to is None:
        date_to = now
    if date_from is not None and date_to <= date_from:
        raise RuntimeError(
            "A date_to nem lehet korábbi, mint a date_from "
            f"({date_from} -> {date_to})."
        )
    return date_from, date_to


def _show_types(spec: ExportSpec, settings: Settings) -> int:
    print(f"{spec.slug} ({spec.source}):")
    if spec.source == "ovak":
        for stream in spec.ovak_streams:
            extra = ""
            if stream.kind == "org_devices":
                extra = f" data_path={stream.data_path}"
            print(f"  ovak stream {stream.name}: kind={stream.kind} {stream.endpoint}{extra}")
        return EXIT_OK
    backend = ScorpioBackend(settings)
    try:
        for type_spec in spec.types:
            resolved, count = backend.verify_type(type_spec.name)
            print(f"  {type_spec.name}: stored={resolved} count={count}")
    finally:
        backend.close()
    return EXIT_OK


def _fetch(ctx: ExportContext, ovak_from: datetime, ovak_to: datetime) -> None:
    spec = ctx.spec
    if spec.source == "ovak":
        backend = OVAKBackend(ctx.settings)
        try:
            ctx.streams = backend.fetch_streams(spec.ovak_streams, ovak_from, ovak_to, cap=ctx.limit)
        finally:
            backend.close()
        return
    backend = ScorpioBackend(ctx.settings)
    try:
        if spec.window == "today":
            time_from, time_to = ctx.date_from, ctx.date_to
        else:
            time_from = time_to = None
        ctx.entities = backend.fetch_types(
            spec.types,
            time_from=time_from,
            time_to=time_to,
            require_attr=spec.require_attr,
            cap=ctx.limit,
        )
    finally:
        backend.close()


def _write_csv(path: Path, fields: list[str], rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    log.info("CSV mentve: %s (%d sor)", path, len(rows))


def _summary(spec: ExportSpec, ctx: ExportContext, rows: list[dict], stats: dict, started: float, exit_code: int) -> str:
    window_from = api_time(ctx.date_from) if ctx.date_from else "-"
    window_to = api_time(ctx.date_to) if ctx.date_to else "-"
    return (
        f"export={spec.slug} window={window_from}/{window_to} "
        f"fetched={ctx.fetched} assembled={len(rows)} "
        f"published={stats.get('published', 0)} dedup={stats.get('dedup', 0)} "
        f"cleanup={stats.get('cleanup', 0)} duration={time.time() - started:.1f}s "
        f"exit={exit_code}"
    )


def _run(args: argparse.Namespace) -> int:
    started = time.time()
    settings = load_settings()
    module = importlib.import_module(EXPORT_MODULES[args.slug])
    spec = apply_pipelines(module.SPEC, load_pipelines(), settings)
    build_rows = getattr(module, "build_rows", None)
    if not callable(build_rows):
        log.error("%s modul nem tartalmaz build_rows(ctx) függvényt.", args.slug)
        return EXIT_UNEXPECTED

    if args.show_types:
        return _show_types(spec, settings)

    try:
        date_from, date_to = _default_window(spec, args.date_from, args.date_to)
    except RuntimeError as e:
        log.error("%s", e)
        return EXIT_FETCH

    # For "all"-window exports fed to OVAK "time" streams, keep the window open.
    ovak_from = date_from or _OVAK_HISTORICAL_START
    ovak_to = date_to or datetime.now(timezone.utc)

    ctx = ExportContext(spec=spec, settings=settings, date_from=date_from, date_to=date_to,
                        limit=args.limit)
    try:
        _fetch(ctx, ovak_from, ovak_to)
        rows = build_rows(ctx)
        if spec.sort_key:
            rows.sort(key=lambda row: str(row.get(spec.sort_key, "")))
        elif spec.sort_tuple:
            rows.sort(key=lambda row: tuple(str(row.get(key, "")) for key in spec.sort_tuple))
    except Exception as e:
        log.error("Lekérési/összeállítási hiba (%s): %s", args.slug, e)
        return EXIT_FETCH

    if args.csv_out:
        _write_csv(Path(args.csv_out), spec.fields, rows)

    if args.sample and rows:
        log.info("Minta (%d sor):", min(args.sample, len(rows)))
        for row in rows[: args.sample]:
            log.info("  %s", {k: row.get(k) for k in spec.fields})

    dry_run = bool(args.dry_run)
    if dry_run:
        print(_summary(spec, ctx, rows, {}, started, EXIT_OK))
        return EXIT_OK

    if not rows:
        log.warning("Nincs feltölthető rekord (%s).", args.slug)
        print(_summary(spec, ctx, rows, {}, started, EXIT_EMPTY))
        return EXIT_EMPTY

    client = CKANExportsClient(settings)
    try:
        client.login()
        stats = client.publish(spec, rows)
    except Exception as e:
        log.error("CKAN hiba (%s): %s", args.slug, e)
        print(_summary(spec, ctx, rows, {}, started, EXIT_CKAN))
        return EXIT_CKAN
    finally:
        client.close()

    print(_summary(spec, ctx, rows, stats, started, EXIT_OK))
    return EXIT_OK


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ckan-exports",
        description="Standardizált CKAN export-pipeline (Scorpio + OVAK források).",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    list_parser = sub.add_parser("list", help="Export-slugok listázása.")
    list_parser.set_defaults(handler=_cmd_list)

    run = sub.add_parser("run", help="Egy export futtatása.")
    run.add_argument("slug", choices=SLUGS, help="Export-slug (lásd: list).")
    run.add_argument("--from", dest="date_from", type=_parse_datetime,
                     help="Ablak kezdete (ISO-8601).")
    run.add_argument("--to", dest="date_to", type=_parse_datetime,
                     help="Ablak vége (ISO-8601).")
    run.add_argument("--dry-run", action="store_true",
                     help="Összeállít, de nem ír CKAN-ba.")
    run.add_argument("--sample", type=int, default=0,
                     help="Első N sor kiírása a logba (csak nem dry-run esetén is hasznos).")
    run.add_argument("--limit", type=int, default=None,
                     help="Smoke-teszt: típusonként/streamenként maximum N entitás lekérése.")
    run.add_argument("--show-types", action="store_true",
                     help="Típusok/totálok listázása a backendből, export nélkül.")
    run.add_argument("--csv-out", type=Path, help="CSV kiírása ide is (utf-8-sig).")
    run.add_argument("--debug", action="store_true", help="Debug log (HTTP is).")
    run.add_argument("-v", "--verbose", action="count", default=0, help="Bővebb log.")
    run.add_argument("-q", "--quiet", action="count", default=0, help="Csendesebb log.")
    run.set_defaults(handler=_run)
    return parser


def _cmd_list(args: argparse.Namespace) -> int:
    settings = load_settings()
    pipelines = load_pipelines()
    for slug in SLUGS:
        module = importlib.import_module(EXPORT_MODULES[slug])
        spec = apply_pipelines(module.SPEC, pipelines, settings)
        print(f"{slug:45s} [{spec.source:6s}] {spec.title}")
    return EXIT_OK


def main(argv: Optional[list[str]] = None) -> int:
    args = _build_parser().parse_args(argv)
    debug = bool(getattr(args, "debug", False)) or getattr(args, "verbose", 0) > 0
    setup_logging(debug=debug, quiet=getattr(args, "quiet", 0))
    try:
        return int(args.handler(args) or EXIT_OK)
    except KeyboardInterrupt:
        return EXIT_UNEXPECTED
    except Exception as e:  # noqa: BLE001 - the wrapper needs every exit code
        log.exception("Nem várt hiba: %s", e)
        return EXIT_UNEXPECTED
