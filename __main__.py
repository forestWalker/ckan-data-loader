"""Allow ``python -m ckan_exports run <slug> ...`` (with apps/ckan_exports on PYTHONPATH)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from core.pipeline import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
