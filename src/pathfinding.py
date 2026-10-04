"""A* search for the cheapest path between two zones of a Graph."""

import heapq
from math import dist

from .pydantic_models import Graph, Path


class NoPathError(Exception):
    """Raised when no path exists between start and end."""


class PathFinder:
    """Finds the cheapest route between two zones of a Graph using A*."""

    def __init__(
        self,
        graph: Graph,
        start: str,
        end: str,
        excluded_connections: set[frozenset[str]] | None = None,
    ) -> None:
        """Store the search parameters and validate start/end zones."""
        self.graph = graph
        self.start = start
        self.end = end
        self.excluded_connections = excluded_connections or set()
        self.validate()
        self.heuristic_scale = self.min_cost_per_distance()

    def validate(self) -> None:
        """Ensure start and end exist and are not blocked."""
        for name in (self.start, self.end):
            if name not in self.graph.zones:
                raise ValueError(f"Unknown zone: {name!r}")
        if self.graph.zones[self.start].is_blocked:
            raise ValueError(f"Start zone is blocked: {self.start!r}")
        if self.graph.zones[self.end].is_blocked:
            raise ValueError(f"End zone is blocked: {self.end!r}")

    def min_cost_per_distance(self) -> float:
        """Smallest move cost per unit of distance, for the heuristic."""
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
        return distance * self.heuristic_scale

    def reconstruct_path(self, node: str, came_from: dict[str,
                                                          str]) -> list[str]:
        """Rebuild the ordered list of zone names from start to node."""
        path = [node]
        while node in came_from:
            node = came_from[node]
            path.append(node)
        path.reverse()
        return path

    def a_star(self) -> Path:
        """Run A*; on equal cost, prefer the path with most priority hubs."""
        came_from: dict[str, str] = {}
        best: dict[str, tuple[float, int]] = {self.start: (0.0, 0)}
        visited: set[str] = set()

        open_paths: list[tuple[float, int, float, str]] = [
            (round(self.heuristic(self.start), 9), 0, 0.0, self.start)
        ]

        while open_paths:
            _, neg_priority, current_cost, current = heapq.heappop(open_paths)
            if current in visited:
                continue
            visited.add(current)

            if current == self.end:
                zones = self.reconstruct_path(current, came_from)
                return Path(zones=zones, total_cost=current_cost,
                            priority_hubs=-neg_priority)

            for neighbor in self.graph.get_neighbors(current):
                neighbor_zone = self.graph.zones[neighbor]
                if neighbor_zone.is_blocked or neighbor in visited:
                    continue
                if frozenset((current, neighbor)) in self.excluded_connections:
                    continue

                new_cost = current_cost + neighbor_zone.move_cost
                new_priority = -neg_priority + neighbor_zone.is_priority
                label = (new_cost, -new_priority)
                old_cost, old_priority = best.get(neighbor, (float("inf"), 0))
                if label < (old_cost, -old_priority):
                    best[neighbor] = (new_cost, new_priority)
                    came_from[neighbor] = current
                    estimate = round(new_cost + self.heuristic(neighbor), 9)
                    heapq.heappush(open_paths, (estimate, -new_priority,
                                                new_cost, neighbor))

        raise NoPathError(f"No path from {self.start!r} to {self.end!r}")

    @staticmethod
    def k_shortest_paths(graph: Graph, start: str, end: str,
                         k: int) -> list[Path]:
        """Return up to k distinct paths, cheapest then most priority."""
        paths: list[Path] = []
        seen_routes: set[tuple[str, ...]] = set()
        tried: set[frozenset[frozenset[str]]] = set()

        candidates: list[tuple[float, int, int, Path,
                               frozenset[frozenset[str]]]] = []
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
            heapq.heappush(candidates, (path.total_cost, -path.priority_hubs,
                                        counter, path, excluded))
            counter += 1

        push(frozenset())
        while candidates and len(paths) < k:
            _, _, _, path, excluded = heapq.heappop(candidates)
            route = tuple(path.zones)
            if route in seen_routes:
                continue
            seen_routes.add(route)
            paths.append(path)
            for zone_a, zone_b in zip(path.zones, path.zones[1:]):
                push(excluded | {frozenset((zone_a, zone_b))})

        return paths
