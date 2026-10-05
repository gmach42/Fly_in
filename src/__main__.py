"""Fly-in entry point: `make run`, i.e. `python -m src`."""

import sys

import pygame

from . import render

if __name__ == "__main__":
    try:
        render.Gui.run_gui()
    except KeyboardInterrupt:
        pygame.quit()
        print("\nInterrupted", file=sys.stderr)
        sys.exit(130)
