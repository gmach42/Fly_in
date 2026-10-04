"""Fly-in entry point: `make run`, i.e. `python -m src`."""

from . import render

if __name__ == "__main__":
    render.Gui.run_gui()
