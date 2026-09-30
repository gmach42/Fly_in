"""Fly-in entry point (`make run`, i.e. `python -m src`).

Without argument, opens the graphical menu (difficulty -> map -> animated
simulation). With a map file, runs the simulation in the terminal only:

    python -m src maps/easy/01_linear_path.txt
"""

import sys
from pathlib import Path

# The modules of src/ import each other by their plain name
# (`from pydantic_models import ...`), so src/ itself must be importable.
sys.path.insert(0, str(Path(__file__).parent))

from parser import ParseError, parse_map_file
from pathfinding import NoPathError
from simulation import DeadlockError, Simulation


def run_in_terminal(map_file: str) -> int:
    """Simulate map_file, print one line per turn. Returns an exit code."""
    try:
        simulation = Simulation(parse_map_file(map_file))
        simulation.run()
    except (OSError, ParseError, NoPathError, DeadlockError,
            ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    for moves in simulation.turns:
        print(simulation.format_turn(moves))
    print(f"{len(simulation.turns)} turns", file=sys.stderr)
    return 0


def main() -> None:
    if len(sys.argv) > 2:
        print("Usage: python -m src [map_file]", file=sys.stderr)
        sys.exit(2)
    if len(sys.argv) == 2:
        sys.exit(run_in_terminal(sys.argv[1]))

    import render  # pygame is only needed for the graphical mode
    render.run_gui()


if __name__ == "__main__":
    main()
