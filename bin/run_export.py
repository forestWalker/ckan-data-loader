#!/usr/bin/env python3
"""Thin launcher for the CKAN export pipeline (python -m ckan_exports run ...).

Kept for CronJob/script compatibility; the logic lives in core.pipeline.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.pipeline import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
