"""Fly-in simulation: schedule drones without breaking capacities."""

import heapq

from .pathfinding import NoPathError, k_shortest_paths
from .pydantic_models import Graph, Path

MAX_PATHS = 10

# Where a drone is at the end of a turn: (zone, zone) when it is in a zone,
# (from_zone, to_zone) when it is flying towards a restricted zone.
Step = tuple[str, str]


class Simulation:
    """Schedules all drones from graph.start to graph.end."""

    def __init__(self, graph: Graph) -> None:
        self.graph = graph
        self.paths = k_shortest_paths(graph, graph.start, graph.end, MAX_PATHS)
        if not self.paths:
            raise NoPathError(f"No path from {graph.start!r} to {graph.end!r}")
        self.plans: list[list[Step]] = []
        self.zone_slots: dict[tuple[str, int], int] = {}
        self.link_slots: dict[tuple[frozenset[str], int], int] = {}
        self.last_turn = 0

    def run(self) -> list[str]:
        """Schedule every drone; return one output line per turn."""
        for _ in range(self.graph.nb_drones):
            plan = min((self.schedule(path) for path in self.paths), key=len)
            self.reserve(plan)
            self.plans.append(plan)
        return [self.turn_line(turn) for turn in range(1, self.last_turn + 1)]

    def schedule(self, path: Path) -> list[Step]:
        """Earliest way to follow path, waiting where needed."""
        zones = path.zones
        # Past the last reservation everything is free, so a schedule is
        # always found before this turn.
        horizon = self.last_turn + 2 * len(zones) + 2
        queue: list[tuple[int, int]] = [(0, 0)]
        parents: dict[tuple[int, int], tuple[int, int]] = {}
        while queue:
            turn, index = heapq.heappop(queue)
            if index == len(zones) - 1:
                return self.to_plan(zones, (turn, index), parents)
            if turn > horizon:
                break
            here, target = zones[index], zones[index + 1]
            next_states = []
            if self.zone_free(here, turn + 1):
                next_states.append((turn + 1, index))
            arrival = turn + (2 if self.restricted(target) else 1)
            if all(self.link_free(here, target, t)
                   for t in range(turn + 1, arrival + 1)):
                if self.zone_free(target, arrival):
                    next_states.append((arrival, index + 1))
            for state in next_states:
                if state not in parents:
                    parents[state] = (turn, index)
                    heapq.heappush(queue, state)
        raise NoPathError(f"No schedule found along {zones}")

    def to_plan(
        self,
        zones: list[str],
        state: tuple[int, int],
        parents: dict[tuple[int, int], tuple[int, int]],
    ) -> list[Step]:
        """Rebuild the Step of every turn from the search result."""
        states = [state]
        while states[-1] in parents:
            states.append(parents[states[-1]])
        states.reverse()
        plan: list[Step] = [(zones[0], zones[0])]
        for (turn, index), (next_turn, next_index) in zip(states, states[1:]):
            if next_turn == turn + 2:
                plan.append((zones[index], zones[next_index]))
            plan.append((zones[next_index], zones[next_index]))
        return plan

    def reserve(self, plan: list[Step]) -> None:
        """Book the zone and link slots used by plan."""
        for turn in range(1, len(plan)):
            (prev_zone, _), (zone, target) = plan[turn - 1:turn + 1]
            if zone == target and self.is_limited(zone):
                key = (zone, turn)
                self.zone_slots[key] = self.zone_slots.get(key, 0) + 1
            if prev_zone != target:
                link = (frozenset((prev_zone, target)), turn)
                self.link_slots[link] = self.link_slots.get(link, 0) + 1
        self.last_turn = max(self.last_turn, len(plan) - 1)

    def is_limited(self, zone: str) -> bool:
        """Start and end hubs have no capacity limit."""
        return zone not in (self.graph.start, self.graph.end)

    def zone_free(self, zone: str, turn: int) -> bool:
        if not self.is_limited(zone):
            return True
        used = self.zone_slots.get((zone, turn), 0)
        return used < self.graph.zones[zone].max_drones

    def link_free(self, zone_a: str, zone_b: str, turn: int) -> bool:
        connection = self.graph.get_connection(zone_a, zone_b)
        if connection is None:
            return False
        used = self.link_slots.get((frozenset((zone_a, zone_b)), turn), 0)
        return used < connection.max_link_capacity

    def restricted(self, zone: str) -> bool:
        return self.graph.zones[zone].zone_type == "restricted"

    def turn_line(self, turn: int) -> str:
        """Write the moves of every drone during the given turn"""
        moves: list[str] = []
        for drone_id, plan in enumerate(self.plans, start=1):
            if turn < len(plan) and plan[turn] != plan[turn - 1]:
                zone, target = plan[turn]
                if zone == target:
                    moves.append(f"D{drone_id}-{zone}")
                else:
                    connection = self.graph.get_connection(zone, target)
                    if connection is not None:
                        name = f"{connection.zone_a}-{connection.zone_b}"
                        moves.append(f"D{drone_id}-{name}")
        return " ".join(moves)

    def position(self, drone: int, turn: int) -> Step:
        """Step of drone (0-based) at turn; delivered drones stay at end."""
        plan = self.plans[drone]
        return plan[min(turn, len(plan) - 1)]
