"""Fly-in entry point: `make run`, i.e. `python -m src`."""

from .render import FlyInApp

if __name__ == "__main__":
    FlyInApp().run()
