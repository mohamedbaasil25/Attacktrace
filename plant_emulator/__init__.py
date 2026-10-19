"""Plant emulator: the simulator physics behind Modbus TCP (emulated plant, no hardware)."""

import sys
from pathlib import Path

try:  # `python -m plant_emulator` from the repo root finds the backend package on any OS
    import app  # noqa: F401
except ModuleNotFoundError:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
