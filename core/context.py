"""Attribute-name normalization for Scorpio entities.

Scorpio stores attributes under *expanded* context IRIs (e.g.
``https://smartdatamodels.org/dataModel.Environment/pm25``) for most types,
while some types (``AnonymousCommuterId``, ``Device``, ``Organization``) are
stored with plain short names. Export modules should always read attributes
through :func:`attr`, which resolves a short name against both forms.
"""

from __future__ import annotations

from typing import Any

from .ngsilib import unwrap

TERMS_PREFIX = "https://smart-data-models.github.io/data-models/terms.jsonld#/definitions/"
SMART_DM = "https://smartdatamodels.org/"
URI_FIWARE = "https://uri.fiware.org/ns/data-models#"
NGSLD_PREFIX = "ngsi-ld:"


def shorten(key: Any) -> str:
    """Map a stored attribute IRI (or short name) to its short CSV name."""
    if not isinstance(key, str):
        return str(key)
    if key.startswith(NGSLD_PREFIX):
        key = key[len(NGSLD_PREFIX):]
    elif key.startswith(TERMS_PREFIX):
        key = key[len(TERMS_PREFIX):]
    elif key.startswith(SMART_DM):
        key = key[len(SMART_DM):]
    elif key.startswith(URI_FIWARE):
        key = key[len(URI_FIWARE):]
    # after the known prefixes the tail is ``<Domain>/<attr>`` (Smart Data
    # Models) or ``#attr`` (Fiware terms) — take the last segment.
    if "#" in key:
        return key.rsplit("#", 1)[1]
    if "/" in key:
        return key.rsplit("/", 1)[1]
    return key


def _index(entity: dict) -> dict[str, Any]:
    """Build {short_name: raw_value} index for an entity's attributes."""
    index: dict[str, Any] = {}
    for key, value in entity.items():
        if key in ("id", "type", "@context"):
            continue
        index.setdefault(shorten(key), value)
    return index


def attr(entity: dict, *names: str) -> Any:
    """Return the unwrapped value of the first matching attribute name."""
    if not isinstance(entity, dict):
        return None
    for name in names:
        if name in entity:
            return unwrap(entity[name])
    index = _index(entity)
    for name in names:
        if name in index:
            return unwrap(index[name])
    return None


def attr_raw(entity: dict, *names: str) -> Any:
    """Like :func:`attr` but returns the raw NGSI-LD wrapper, not the value."""
    if not isinstance(entity, dict):
        return None
    for name in names:
        if name in entity:
            return entity[name]
    index = _index(entity)
    for name in names:
        if name in index:
            return index[name]
    return None


def has_attr(entity: dict, name: str) -> bool:
    """True when the entity carries the attribute under any stored spelling."""
    if not isinstance(entity, dict):
        return False
    return name in entity or name in _index(entity)
