#!/usr/bin/env python3
"""Export the FastAPI OpenAPI schema to backend/openapi.json (no server required)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_ROOT.parent
DEFAULT_OUT = BACKEND_ROOT / "openapi.json"


def main() -> int:
    sys.path.insert(0, str(BACKEND_ROOT))
    from app.main import app  # noqa: PLC0415

    out = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_OUT
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(app.openapi(), indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {out.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
