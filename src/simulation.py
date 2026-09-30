"""Simulation of Fly-in"""

from pathfinding import NoPathError, k_shortest_paths
from pydantic_models import Drone, Graph, Path

MAX_PATHS = 5


class DeadlockError(Exception):
    """Raised when no drone can move but some have not arrived."""


class Simulation:
    """Runs all drones from graph.start to graph.end, turn by turn.

    Attributes:
        graph: The map.
        drones: All drones, indexed by id - 1.
        paths: Route assigned to each drone id.
        turns: History, one list of move strings per turn.
    """

    def __init__(self, graph: Graph) -> None:
        self.graph = graph
        self.drones = [
            Drone(id=i, current_zone=graph.start)
            for i in range(1, graph.nb_drones + 1)
        ]
        self.paths: dict[int, Path] = {}
        self.progress: dict[int, int] = {}      # drone id -> index in its path
        self.turns_left: dict[int, int] = {}    # drone id -> remaining transit turns
        self.zone_occupancy: dict[str, int] = {graph.start: graph.nb_drones}
        self.turns: list[list[str]] = []
        self._assign_paths()

    def _assign_paths(self) -> None:
        """Spread drones over the k cheapest paths.

        Greedy: each drone takes the path minimising
        path.total_cost + number of drones already assigned to it.
        """
        paths = k_shortest_paths(
            self.graph, self.graph.start, self.graph.end, MAX_PATHS
        )
        # TODO: raise / propagate NoPathError if paths is empty
        # TODO: load = [0] * len(paths); for each drone pick argmin(cost + load)
        if not paths:
            raise NoPathError(
                f"No path from {self.graph.start!r} to {self.graph.end!r}"
            )

        load = [0] * len(paths)

        for drone in self.drones:
            best_index = min(
                range(len(paths)),
                key=lambda i: paths[i].total_cost + load[i],
            )
            self.paths[drone.id] = paths[best_index]
            self.progress[drone.id] = 0
            self.turns_left[drone.id] = 0
            load[best_index] += 1

    def _capacity(self, zone_name: str) -> float:
        """max_drones of the zone; unlimited for start/end (à vérifier)."""
        if zone_name in (self.graph.start, self.graph.end):
            return float("inf")
        return self.graph.zones[zone_name].max_drones

    def run(self, max_turns: int = 10_000) -> list[list[str]]:
        """Simulate until every drone has arrived; return the turn history."""
        while not self.is_finished():
            if len(self.turns) >= max_turns:
                raise DeadlockError("Turn limit reached")
            moves = self.step()
            if not moves and not self._any_in_transit():
                raise DeadlockError(f"Stuck at turn {len(self.turns) + 1}")
            self.turns.append(moves)
        return self.turns

    def step(self) -> list[str]:
        """Play one turn and return the moves made (e.g. ["D1-hub", ...])."""
        link_usage: dict[frozenset[str], int] = {}
        moves: list[str] = []
        for drone in self._ordered_drones():
            if drone.state == "arrived":
                continue
            if drone.state == "moving":
                # TODO: finish restricted transit (turns_left -= 1, count link,
                #       arrive when 0, record move)
                continue
            # TODO: next_zone = path.zones[progress + 1]
            # TODO: if self._can_move(drone, next_zone, link_usage): self._move(...)
            # TODO: else drone.state = "waiting"
            next_zone = self.paths[drone.id].zones[self.progress[drone.id] + 1]
            if self._can_move(drone, next_zone, link_usage):
                move = self._move(drone, next_zone, link_usage)
                if move:
                    moves.append(move)
            else:
                drone.state = "waiting"
        return moves

    # ── Rules ───────────────────────────────────────────────────────────
    def _ordered_drones(self) -> list[Drone]:
        """Most advanced drones first so they free space for followers."""
        return sorted(
            self.drones, key=lambda d: (-self.progress[d.id], d.id)
        )

    def _can_move(
        self,
        drone: Drone,
        next_zone: str,
        link_usage: dict[frozenset[str], int],
    ) -> bool:
        """Zone capacity and link capacity both allow this hop this turn."""
        # TODO: connection = self.graph.get_connection(drone.current_zone, next_zone)
        # TODO: link_usage.get(key, 0) < connection.max_link_capacity
        # TODO: self.zone_occupancy.get(next_zone, 0) < self._capacity(next_zone)
        ...

    def _move(
        self,
        drone: Drone,
        next_zone: str,
        link_usage: dict[frozenset[str], int],
    ) -> str | None:
        """Apply the hop: update occupancy/link usage, state, progress.

        Restricted destination -> state "moving", turns_left = 1, destination
        slot reserved now. Returns the move string, or None if in transit.
        """
        ...

    def is_finished(self) -> bool:
        return all(d.state == "arrived" for d in self.drones)

    def _any_in_transit(self) -> bool:
        return any(d.state == "moving" for d in self.drones)

    @staticmethod
    def format_turn(moves: list[str]) -> str:
        return " ".join(moves)
