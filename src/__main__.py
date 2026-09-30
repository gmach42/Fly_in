"""Fly-in entry point: `make run`, i.e. `python -m src`."""

import os
import sys
from pathlib import Path

# The modules of src/ import each other by their plain name
# (`from pydantic_models import ...`), so src/ itself must be importable.
sys.path.insert(0, str(Path(__file__).parent))
# pygame prints a banner on import; keep stdout for the simulation turns.
os.environ["PYGAME_HIDE_SUPPORT_PROMPT"] = "1"

import render  # noqa: E402

if __name__ == "__main__":
    render.run_gui()
