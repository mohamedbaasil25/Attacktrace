"""Attacker tool: emulator-only. The only place in the project that writes to the plant.

Used by `python -m attacker` (CLI) and by the backend's LIVE mode (`POST /api/attack`). Every
write target is checked against the allowlist before anything is sent; see `attacker.allowlist`.
"""

import sys
from pathlib import Path

try:
    import app  # noqa: F401
except ModuleNotFoundError:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
