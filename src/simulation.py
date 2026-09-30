"""Multi-drone scheduling and turn-by-turn history for a Fly-in Graph.

Drones are planned one after the other (prioritized planning). Each drone
tries every candidate route from pathfinding.k_shortest_paths and keeps
the schedule that delivers it the earliest, given what the previous drones
already reserved:

- zone slots: drones in a zone at the end of a turn (at most max_drones;
  start and end hubs are unlimited);
- link slots: drones using a connection during a turn (at most
  max_link_capacity).

Rules from the subject, and how they map onto reservations:

- a normal/priority move takes 1 turn and uses the link on that turn;
- a restricted move takes 2 turns: the drone is on the connection at the
  end of the first turn (it uses the link on that turn only, the link is
  freed on the arrival turn) and MUST land on the second one, so a slot
  in the destination has to be free at the end of that second turn;
- a drone leaving a zone frees its slot for the same turn: only the
  occupancy at the end of each turn is counted.

Since each schedule is built against the reservations of the previous
drones, the result can never exceed a capacity, and there is no deadlock:
a drone can always wait in the start hub until the way is clear.
"""

from collections import defaultdict

from pathfinding import NoPathError, k_shortest_paths
from pydantic_models import Drone, Graph, Path

MAX_PATHS = 10

# Where a drone is at the end of a turn: (from_zone, to_zone, fraction of
# the connection travelled). A drone sitting in a zone is (zone, zone, 0.0).
Position = tuple[str, str, float]

# A search state while scheduling one drone: (index in its path, turn).
State = tuple[int, int]


class DeadlockError(Exception):
    """Raised when a drone cannot be scheduled within max_turns."""


class Simulation:
    """Schedules all drones from graph.start to graph.end.

    Attributes:
        graph: The map.
        drones: All drones, indexed by id - 1.
        candidate_paths: Routes a drone may follow, cheapest first.
        plans: Position of each drone at the end of every turn, from turn 0
            (in the start hub) until its delivery turn.
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
        self.candidate_paths = k_shortest_paths(
            graph, graph.start, graph.end, MAX_PATHS
        )
        if not self.candidate_paths:
            raise NoPathError(
                f"No path from {graph.start!r} to {graph.end!r}"
            )
        self.plans: dict[int, list[Position]] = {}
        self.turns: list[list[str]] = []
        self.snapshots: list[dict[int, Position]] = []
        self._zone_slots: dict[tuple[str, int], int] = defaultdict(int)
        self._link_slots: dict[tuple[frozenset[str], int], int] = (
            defaultdict(int)
        )
        self._last_reserved_turn = 0
        # graph.get_connection scans the whole list; this is the hot path.
        self._link_capacity = {
            frozenset((c.zone_a, c.zone_b)): c.max_link_capacity
            for c in graph.connections
        }

    def run(self, max_turns: int = 100_000) -> list[list[str]]:
        """Schedule every drone and return the turn history.

        Raises:
            DeadlockError: If a drone could not be delivered within
                max_turns.
        """
        if self.plans:
            return self.turns
        for drone in self.drones:
            plan = self._best_plan()
            if len(plan) - 1 > max_turns:
                raise DeadlockError(
                    f"D{drone.id} cannot be delivered in {max_turns} turns"
                )
            self._reserve(plan)
            self.plans[drone.id] = plan
            drone.current_zone = self.graph.end
            drone.state = "arrived"
        self._build_history()
        return self.turns

    def _best_plan(self) -> list[Position]:
        """Earliest delivery over all candidate paths.

        Ties go to the path with the most priority zones, then to the
        cheapest one (candidate_paths is sorted by cost).
        """
        best_plan: list[Position] = []
        best_key: tuple[int, int, int] | None = None
        for index, path in enumerate(self.candidate_paths):
            plan = self._schedule(path)
            key = (len(plan), -self._priority_zones(path), index)
            if best_key is None or key < best_key:
                best_plan, best_key = plan, key
        return best_plan

    def _schedule(self, path: Path) -> list[Position]:
        """Earliest schedule along path given the current reservations.

        Breadth-first search over (index in path, turn) states: from each
        state the drone can wait, or move to the next zone of the path.
        States are expanded turn by turn, so the first time the end is
        reached is the earliest possible delivery.
        """
        zones = path.zones
        last = len(zones) - 1
        # Past the last reservation everything is free: the drone can
        # always walk the path then, 2 turns per hop at most.
        horizon = self._last_reserved_turn + 2 * len(zones) + 2
        layers: dict[int, set[int]] = defaultdict(set)
        layers[0].add(0)
        parents: dict[State, State] = {}

        for turn in range(horizon + 1):
            if last in layers[turn]:
                return self._to_positions(zones, (last, turn), parents)
            for index in sorted(layers[turn], reverse=True):
                for target in self._successors(zones, index, turn):
                    if target[0] not in layers[target[1]]:
                        layers[target[1]].add(target[0])
                        parents[target] = (index, turn)
        raise DeadlockError(f"No schedule found along {zones}")

    def _successors(
        self, zones: list[str], index: int, turn: int
    ) -> list[State]:
        """States reachable from being in zones[index] at end of turn."""
        successors: list[State] = []
        zone = zones[index]
        if self._zone_has_room(zone, turn + 1):
            successors.append((index, turn + 1))

        if index + 1 < len(zones):
            target = zones[index + 1]
            link = frozenset((zone, target))
            if self._link_has_room(link, turn + 1):
                arrival = turn + (
                    2 if self._is_restricted(target) else 1
                )
                if self._zone_has_room(target, arrival):
                    successors.append((index + 1, arrival))
        return successors

    def _to_positions(
        self, zones: list[str], goal: State, parents: dict[State, State]
    ) -> list[Position]:
        """Turn the search result into one Position per turn."""
        states = [goal]
        while states[-1] in parents:
            states.append(parents[states[-1]])
        states.reverse()

        plan: list[Position] = [(zones[0], zones[0], 0.0)]
        for (index, turn), (next_index, next_turn) in zip(
            states, states[1:]
        ):
            if next_turn - turn == 2:
                plan.append((zones[index], zones[next_index], 0.5))
            zone = zones[next_index]
            plan.append((zone, zone, 0.0))
        return plan

    def _reserve(self, plan: list[Position]) -> None:
        """Book the zone and link slots used by plan."""
        for turn in range(1, len(plan)):
            before, after = plan[turn - 1], plan[turn]
            zone, target, fraction = after
            if fraction == 0.0 and not self._is_unlimited(zone):
                self._zone_slots[(zone, turn)] += 1
            # The link is used on the turn the drone leaves a zone; a
            # restricted connection is freed on the arrival turn.
            leaves_zone = before[2] == 0.0 and after != before
            if leaves_zone:
                self._link_slots[(frozenset((before[0], target)), turn)] += 1
        self._last_reserved_turn = max(
            self._last_reserved_turn, len(plan) - 1
        )

    def _is_unlimited(self, zone_name: str) -> bool:
        return zone_name in (self.graph.start, self.graph.end)

    def _is_restricted(self, zone_name: str) -> bool:
        return self.graph.zones[zone_name].zone_type == "restricted"

    def _zone_has_room(self, zone_name: str, turn: int) -> bool:
        if self._is_unlimited(zone_name):
            return True
        used = self._zone_slots.get((zone_name, turn), 0)
        return used < self.graph.zones[zone_name].max_drones

    def _link_has_room(self, link: frozenset[str], turn: int) -> bool:
        capacity = self._link_capacity.get(link, 0)
        return self._link_slots.get((link, turn), 0) < capacity

    def _priority_zones(self, path: Path) -> int:
        return sum(
            self.graph.zones[zone].zone_type == "priority"
            for zone in path.zones
        )

    def _build_history(self) -> None:
        """Fill turns (move strings) and snapshots from the plans."""
        total_turns = max(len(plan) for plan in self.plans.values()) - 1
        for turn in range(total_turns + 1):
            self.snapshots.append({
                drone_id: plan[min(turn, len(plan) - 1)]
                for drone_id, plan in self.plans.items()
            })
        for turn in range(1, total_turns + 1):
            moves: list[str] = []
            for drone_id, plan in sorted(self.plans.items()):
                if turn < len(plan) and plan[turn] != plan[turn - 1]:
                    moves.append(self._move_string(drone_id, plan, turn))
            self.turns.append(moves)

    def _move_string(
        self, drone_id: int, plan: list[Position], turn: int
    ) -> str:
        """ "D<id>-<zone>", or "D<id>-<connection>" while in flight."""
        zone, target, fraction = plan[turn]
        if fraction == 0.0:
            return f"D{drone_id}-{zone}"
        connection = self.graph.get_connection(zone, target)
        name = connection.name if connection else f"{zone}-{target}"
        return f"D{drone_id}-{name}"

    @staticmethod
    def format_turn(moves: list[str]) -> str:
        return " ".join(moves)
