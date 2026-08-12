"""Logging configuration for the export pipeline.

Logs go to stderr so stdout stays reserved for the single-line summary that
the CronJob/script wrappers parse (see the standardized pipeline plan, §7.5).
"""

from __future__ import annotations

import logging
import sys

_LOGGER_NAME = "ckan_exports"


def setup_logging(*, debug: bool = False, quiet: int = 0) -> logging.Logger:
    """Configure and return the pipeline logger."""
    level = logging.DEBUG if debug else logging.INFO
    if quiet >= 2:
        level = logging.ERROR
    elif quiet >= 1:
        level = logging.WARNING

    logger = logging.getLogger(_LOGGER_NAME)
    logger.handlers.clear()
    logger.setLevel(level)
    logger.propagate = False

    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter(
        fmt="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    ))
    handler.setLevel(level)
    logger.addHandler(handler)

    if debug:
        logging.getLogger("httpx").setLevel(logging.DEBUG)
    else:
        logging.getLogger("httpx").setLevel(logging.WARNING)

    return logger
