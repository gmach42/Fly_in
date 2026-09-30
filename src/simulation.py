"""Turn-based multi-drone simulation over a Fly-in Graph.

Each drone gets a precomputed Path (see pathfinding.k_shortest_paths) and,
every turn, either advances one hop along it or waits. Rules enforced:

- a zone never holds more than max_drones drones at the end of a turn
  (start and end hubs are unlimited);
- a connection is never used by more than max_link_capacity drones
  during the same turn;
- moving into a restricted zone takes 2 turns: the drone spends the first
  one on the connection (which it keeps using on both turns) and its slot
  in the destination is reserved as soon as it leaves, so it can never get
  stuck halfway.

Moves within a turn are simultaneous: a drone leaving a zone frees its slot
for a follower in the same turn. To get that right whatever the path
layout, a turn is resolved in passes until no more drone can move.
"""

from pathfinding import NoPathError, k_shortest_paths
from pydantic_models import Drone, Graph, Path

MAX_PATHS = 5

# Where a drone is at the end of a turn: (from_zone, to_zone, fraction of
# the connection travelled). A drone sitting in a zone is (zone, zone, 0.0).
Position = tuple[str, str, float]


class DeadlockError(Exception):
    """Raised when no drone can move but some have not arrived."""


class Simulation:
    """Runs all drones from graph.start to graph.end, turn by turn.

    Attributes:
        graph: The map.
        drones: All drones, indexed by id - 1.
        paths: Route assigned to each drone id.
        progress: Index in its path of the zone each drone is in (or is
            leaving, while in transit).
        zone_occupancy: Drones in (or reserved for) each zone.
        turns: History, one list of move strings per turn.
        snapshots: Drone positions after each turn; snapshots[0] is the
            initial state, so len(snapshots) == len(turns) + 1.
    """

    def __init__(self, graph: Graph) -> None:
        self.graph = graph
        self.drones = [
            Drone(id=i, current_zone=graph.start)
            for i in range(1, graph.nb_drones + 1)
        ]
        self.paths: dict[int, Path] = {}
        self.progress: dict[int, int] = {}
        self.turns_left: dict[int, int] = {}
        self.zone_occupancy: dict[str, int] = {graph.start: graph.nb_drones}
        self.turns: list[list[str]] = []
        self.snapshots: list[dict[int, Position]] = []
        self._assign_paths()
        self.snapshots.append(self._snapshot())

    def _assign_paths(self) -> None:
        """Spread drones over the k cheapest paths.

        Greedy: each drone takes the path where it is expected to arrive
        first, i.e. path.total_cost + (drones already on it // throughput),
        throughput being the narrowest capacity along the path.
        """
        paths = k_shortest_paths(
            self.graph, self.graph.start, self.graph.end, MAX_PATHS
        )
        if not paths:
            raise NoPathError(
                f"No path from {self.graph.start!r} to {self.graph.end!r}"
            )

        throughputs = [self._throughput(path) for path in paths]
        load = [0] * len(paths)

        for drone in self.drones:
            best_index = min(
                range(len(paths)),
                key=lambda i: paths[i].total_cost + load[i] // throughputs[i],
            )
            self.paths[drone.id] = paths[best_index]
            self.progress[drone.id] = 0
            self.turns_left[drone.id] = 0
            load[best_index] += 1

    def _throughput(self, path: Path) -> int:
        """Drones per turn the path can let through (its bottleneck)."""
        capacities: list[int] = []
        for zone_a, zone_b in zip(path.zones, path.zones[1:]):
            connection = self.graph.get_connection(zone_a, zone_b)
            if connection is not None:
                capacities.append(connection.max_link_capacity)
            if zone_b != self.graph.end:
                capacities.append(self.graph.zones[zone_b].max_drones)
        return min(capacities, default=1)

    def _capacity(self, zone_name: str) -> float:
        """max_drones of the zone; unlimited for start/end."""
        if zone_name in (self.graph.start, self.graph.end):
            return float("inf")
        return self.graph.zones[zone_name].max_drones

    def run(self, max_turns: int = 10_000) -> list[list[str]]:
        """Simulate until every drone has arrived; return the turn history.

        Raises:
            DeadlockError: If a turn goes by with no drone able to move,
                or if max_turns is reached.
        """
        while not self.is_finished():
            if len(self.turns) >= max_turns:
                raise DeadlockError("Turn limit reached")
            moves = self.step()
            # A drone in transit always lands, so an empty turn means that
            # nobody can move any more.
            if not moves:
                raise DeadlockError(f"Stuck at turn {len(self.turns) + 1}")
            self.turns.append(moves)
            self.snapshots.append(self._snapshot())
        return self.turns

    def step(self) -> list[str]:
        """Play one turn and return the moves made (e.g. ["D1-hub", ...])."""
        link_usage: dict[frozenset[str], int] = {}
        moves: list[str] = []

        # Drones already on a connection are committed: they land first,
        # and that landing is their move for this turn.
        landed: set[int] = set()
        for drone in self.drones:
            if drone.state == "moving":
                moves.append(self._finish_transit(drone, link_usage))
                landed.add(drone.id)

        pending = [
            drone for drone in self._ordered_drones()
            if drone.state != "arrived" and drone.id not in landed
        ]
        # Repeat until stable: a drone blocked in one pass may get a slot
        # freed by a drone of another path later in the same pass.
        moved = True
        while moved:
            moved = False
            still_pending: list[Drone] = []
            for drone in pending:
                next_zone = self._next_zone(drone)
                if self._can_move(drone, next_zone, link_usage):
                    moves.append(self._move(drone, next_zone, link_usage))
                    moved = True
                else:
                    still_pending.append(drone)
            pending = still_pending

        for drone in pending:
            drone.state = "waiting"
        return sorted(moves, key=self._move_drone_id)

    def _ordered_drones(self) -> list[Drone]:
        """Most advanced drones first so they free space for followers."""
        return sorted(
            self.drones, key=lambda d: (-self.progress[d.id], d.id)
        )

    def _next_zone(self, drone: Drone) -> str:
        return self.paths[drone.id].zones[self.progress[drone.id] + 1]

    def _can_move(
        self,
        drone: Drone,
        next_zone: str,
        link_usage: dict[frozenset[str], int],
    ) -> bool:
        """Zone capacity and link capacity both allow this hop this turn."""
        connection = self.graph.get_connection(drone.current_zone, next_zone)
        if connection is None:
            return False
        key = frozenset((drone.current_zone, next_zone))
        if link_usage.get(key, 0) >= connection.max_link_capacity:
            return False
        occupancy = self.zone_occupancy.get(next_zone, 0)
        return occupancy < self._capacity(next_zone)

    def _move(
        self,
        drone: Drone,
        next_zone: str,
        link_usage: dict[frozenset[str], int],
    ) -> str:
        """Apply the hop: update occupancy/link usage, state, progress.

        Restricted destination: the drone only leaves its zone this turn
        (state "moving", destination slot reserved) and lands next turn.
        Returns the move string: "D<id>-<zone>", or "D<id>-<from>-<to>"
        for a drone that is now on the connection.
        """
        origin = drone.current_zone
        key = frozenset((origin, next_zone))
        link_usage[key] = link_usage.get(key, 0) + 1
        self.zone_occupancy[origin] -= 1
        self.zone_occupancy[next_zone] = (
            self.zone_occupancy.get(next_zone, 0) + 1
        )

        if self.graph.zones[next_zone].zone_type == "restricted":
            drone.state = "moving"
            self.turns_left[drone.id] = 1
            return f"D{drone.id}-{origin}-{next_zone}"

        self._land(drone, next_zone)
        return f"D{drone.id}-{next_zone}"

    def _finish_transit(
        self, drone: Drone, link_usage: dict[frozenset[str], int]
    ) -> str:
        """Second turn of a restricted move: the drone reaches its zone."""
        next_zone = self._next_zone(drone)
        key = frozenset((drone.current_zone, next_zone))
        link_usage[key] = link_usage.get(key, 0) + 1
        self.turns_left[drone.id] = 0
        self._land(drone, next_zone)
        return f"D{drone.id}-{next_zone}"

    def _land(self, drone: Drone, zone_name: str) -> None:
        """Put the drone in zone_name (its slot is already counted)."""
        drone.current_zone = zone_name
        self.progress[drone.id] += 1
        drone.state = "arrived" if zone_name == self.graph.end else "idle"

    def _snapshot(self) -> dict[int, Position]:
        positions: dict[int, Position] = {}
        for drone in self.drones:
            if drone.state == "moving":
                target = self._next_zone(drone)
                positions[drone.id] = (drone.current_zone, target, 0.5)
            else:
                zone = drone.current_zone
                positions[drone.id] = (zone, zone, 0.0)
        return positions

    @staticmethod
    def _move_drone_id(move: str) -> int:
        return int(move[1:move.index("-")])

    def is_finished(self) -> bool:
        return all(d.state == "arrived" for d in self.drones)

    @staticmethod
    def format_turn(moves: list[str]) -> str:
        return " ".join(moves)
