"""Adaptation of the A* algorithm to find the cheapest path between two zones
of a Graph.
"""


import heapq
from math import dist

from pydantic_models import Graph, Path


class NoPathError(Exception):
    """Raised when no path exists between start and end."""


class PathFinder:
    """Finds the cheapest route between two zones of a Graph using A*.

    Attributes:
        graph: The map to search.
        start: Name of the starting zone.
        end: Name of the destination zone.
    """

    def __init__(
        self,
        graph: Graph,
        start: str,
        end: str,
        excluded_connections: set[frozenset[str]] | None = None,
    ) -> None:
        """Initialize the PathFinder and validate start/end.

        Args:
            graph: The map to search.
            start: Name of the starting zone.
            end: Name of the destination zone.
            excluded_connections: Connections to treat as unusable, as
                `{zone_a, zone_b}` pairs. Used by `k_shortest_paths` to
                force alternative routes.

        Raises:
            ValueError: If start or end are unknown or blocked zones.
        """
        self.graph = graph
        self.start = start
        self.end = end
        self.excluded_connections = excluded_connections or set()
        self._validate()
        self._heuristic_scale = self._min_cost_per_distance()

    def _validate(self) -> None:
        for name in (self.start, self.end):
            if name not in self.graph.zones:
                raise ValueError(f"Unknown zone: {name!r}")
        if self.graph.zones[self.start].is_blocked:
            raise ValueError(f"Start zone is blocked: {self.start!r}")
        if self.graph.zones[self.end].is_blocked:
            raise ValueError(f"End zone is blocked: {self.end!r}")

    def _min_cost_per_distance(self) -> float:
        ratios: list[float] = []
        for connection in self.graph.connections:
            zone_a = self.graph.zones[connection.zone_a]
            zone_b = self.graph.zones[connection.zone_b]
            distance = dist((zone_a.x, zone_a.y), (zone_b.x, zone_b.y))
            if distance == 0:
                continue
            if not zone_a.is_blocked:
                ratios.append(zone_a.move_cost / distance)
            if not zone_b.is_blocked:
                ratios.append(zone_b.move_cost / distance)
        return min(ratios, default=0.0)

    def heuristic(self, zone_name: str) -> float:
        """Estimated (admissible) cost from zone_name to self.end."""
        zone = self.graph.zones[zone_name]
        end_zone = self.graph.zones[self.end]
        distance = dist((zone.x, zone.y), (end_zone.x, end_zone.y))
        return distance * self._heuristic_scale

    def reconstruct_path(
        self, node: str, came_from: dict[str, str]
    ) -> list[str]:
        """Rebuild the ordered list of zone names from start to node."""
        path = [node]
        while node in came_from:
            node = came_from[node]
            path.append(node)
        path.reverse()
        return path

    def a_star(self) -> Path:
        """Run A* and return the cheapest Path from start to end.

        f(n) = g(n) + h(n), with g(n) the real cost accumulated so far
        and h(n) the heuristic estimate to the goal. The open set is a
        binary heap (heapq) keyed on (f_score, g_score, zone), so the
        best-looking cell is always popped in O(log n) instead of
        sorting the whole list at every iteration.

        Raises:
            NoPathError: If end is unreachable from start.
        """
        came_from: dict[str, str] = {}
        path_cost: dict[str, float] = {self.start: 0.0}
        visited: set[str] = set()

        # (f_score, g_score, zone) ; g_score is a stable tie-breaker
        open_paths: list[tuple[float, float, str]] = [
            (self.heuristic(self.start), 0.0, self.start)
        ]

        while open_paths:
            _, current_cost, current = heapq.heappop(open_paths)
            if current in visited:
                continue
            visited.add(current)

            if current == self.end:
                zones = self.reconstruct_path(current, came_from)
                return Path(zones=zones, total_cost=current_cost)

            for neighbor in self.graph.get_neighbors(current):
                neighbor_zone = self.graph.zones[neighbor]
                if neighbor_zone.is_blocked or neighbor in visited:
                    continue
                if frozenset((current, neighbor)) in self.excluded_connections:
                    continue

                new_cost = current_cost + neighbor_zone.move_cost
                if new_cost < path_cost.get(neighbor, float("inf")):
                    path_cost[neighbor] = new_cost
                    came_from[neighbor] = current
                    priority = new_cost + self.heuristic(neighbor)
                    heapq.heappush(open_paths, (priority, new_cost, neighbor))

        raise NoPathError(f"No path from {self.start!r} to {self.end!r}")


def k_shortest_paths(graph: Graph, start: str, end: str, k: int) -> list[Path]:
    paths: list[Path] = []
    seen_routes: set[tuple[str, ...]] = set()
    tried: set[frozenset[frozenset[str]]] = set()
    # (total_cost, tie-breaker, path, excluded connections)
    candidates: list[
        tuple[float, int, Path, frozenset[frozenset[str]]]
    ] = []
    counter = 0

    def push(excluded: frozenset[frozenset[str]]) -> None:
        nonlocal counter
        if excluded in tried:
            return
        tried.add(excluded)
        finder = PathFinder(graph, start, end, set(excluded))
        try:
            path = finder.a_star()
        except NoPathError:
            return
        if tuple(path.zones) in seen_routes:
            return
        heapq.heappush(candidates, (path.total_cost, counter, path, excluded))
        counter += 1

    push(frozenset())
    while candidates and len(paths) < k:
        _, _, path, excluded = heapq.heappop(candidates)
        route = tuple(path.zones)
        if route in seen_routes:
            continue
        seen_routes.add(route)
        paths.append(path)
        for zone_a, zone_b in zip(path.zones, path.zones[1:]):
            push(excluded | {frozenset((zone_a, zone_b))})

    return paths
