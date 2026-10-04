"""Pydantic models describing a Fly-in map."""

from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

ZoneType = Literal["normal", "priority", "restricted", "blocked"]

ZONE_MOVE_COST: dict[ZoneType, float] = {
    "normal": 1,
    "priority": 1,
    "restricted": 2,
    "blocked": float("inf"),
}

MAX_COORDINATE = 100


class Zone(BaseModel):
    """A zone (hub) in the map."""

    name: str
    x: int = Field(ge=-MAX_COORDINATE, le=MAX_COORDINATE)
    y: int = Field(ge=-MAX_COORDINATE, le=MAX_COORDINATE)
    zone_type: ZoneType = "normal"
    color: str | None = None
    max_drones: int = 1

    @field_validator("name")
    @classmethod
    def no_dashes(cls, v: str) -> str:
        """Ensure the zone name does not contain dashes."""
        if "-" in v:
            raise ValueError("Zone name cannot contain dashes")
        return v

    @field_validator("max_drones")
    @classmethod
    def positive_capacity(cls, v: int) -> int:
        """Ensure the max_drones is a positive integer."""
        if v <= 0:
            raise ValueError("max_drones must be a positive integer")
        return v

    @property
    def move_cost(self) -> float:
        """Cost to move a drone into this zone."""
        return ZONE_MOVE_COST[self.zone_type]

    @property
    def is_priority(self) -> bool:
        """Whether paths through this zone are preferred on equal cost."""
        return self.zone_type == "priority"

    @property
    def is_blocked(self) -> bool:
        """Whether drones can never enter this zone."""
        return self.zone_type == "blocked"


class Connection(BaseModel):
    """A bidirectional link between two zones."""

    zone_a: str
    zone_b: str
    max_link_capacity: int = 1

    @field_validator("max_link_capacity")
    @classmethod
    def positive_capacity(cls, v: int) -> int:
        """Ensure the max_link_capacity is a positive integer."""
        if v <= 0:
            raise ValueError("max_link_capacity must be a positive integer")
        return v

    @model_validator(mode="after")
    def no_self_loop(self) -> "Connection":
        """Ensure that a connection does not link a zone to itself."""
        if self.zone_a == self.zone_b:
            raise ValueError("A connection cannot link a zone to itself")
        return self

    def links(self, zone_name: str) -> bool:
        """Check if the given zone is part of this connection."""
        return zone_name in (self.zone_a, self.zone_b)

    def other_side(self, zone_name: str) -> str:
        """Given one zone in the connection, return the other side."""
        if zone_name == self.zone_a:
            return self.zone_b
        if zone_name == self.zone_b:
            return self.zone_a
        raise ValueError(f"{zone_name!r} is not part of this connection")


class Graph(BaseModel):
    """The full map: zones, connections and the start/end hubs."""

    nb_drones: int
    start: str
    end: str
    zones: dict[str, Zone] = Field(default_factory=dict)
    connections: list[Connection] = Field(default_factory=list)

    @field_validator("nb_drones")
    @classmethod
    def positive_drones(cls, v: int) -> int:
        """Ensure the number of drones is a positive integer."""
        if v <= 0:
            raise ValueError("nb_drones must be a positive integer")
        return v

    @field_validator("zones", mode="before")
    @classmethod
    def zones_from_list(cls, v: object) -> object:
        """Allow passing zones as a list, rejecting duplicate names."""
        if isinstance(v, list):
            zones: dict[str, Zone] = {}
            for zone in v:
                name = zone.name if isinstance(zone, Zone) else zone["name"]
                if name in zones:
                    raise ValueError(f"Duplicate zone name: {name!r}")
                zones[name] = zone
            return zones
        return v

    @model_validator(mode="after")
    def check_consistency(self) -> "Graph":
        """Ensure the graph is internally consistent."""
        if self.start not in self.zones:
            raise ValueError(f"Unknown start hub: {self.start!r}")
        if self.end not in self.zones:
            raise ValueError(f"Unknown end hub: {self.end!r}")

        positions: dict[tuple[int, int], str] = {}
        for zone in self.zones.values():
            other = positions.setdefault((zone.x, zone.y), zone.name)
            if other != zone.name:
                raise ValueError(
                    f"Zones {other!r} and {zone.name!r} share position "
                    f"({zone.x}, {zone.y})"
                )

        seen_pairs: set[frozenset[str]] = set()
        for connection in self.connections:
            for zone_name in (connection.zone_a, connection.zone_b):
                if zone_name not in self.zones:
                    raise ValueError(
                        f"Connection references unknown zone: {zone_name!r}"
                    )
            pair = frozenset((connection.zone_a, connection.zone_b))
            if pair in seen_pairs:
                raise ValueError(
                    "Duplicate connection: "
                    f"{connection.zone_a}-{connection.zone_b}"
                )
            seen_pairs.add(pair)
        return self

    def add_zone(self, zone: Zone) -> None:
        """Add a new zone to the graph."""
        if zone.name in self.zones:
            raise ValueError(f"Duplicate zone name: {zone.name!r}")
        self.zones[zone.name] = zone

    def add_connection(self, connection: Connection) -> None:
        """Add a new connection to the graph."""
        for zone_name in (connection.zone_a, connection.zone_b):
            if zone_name not in self.zones:
                raise ValueError(
                    f"Connection references unknown zone: {zone_name!r}"
                )
        self.connections.append(connection)

    def get_neighbors(self, zone_name: str) -> list[str]:
        """Return a list of neighboring zone names for the given zone."""
        return [
            connection.other_side(zone_name)
            for connection in self.connections
            if connection.links(zone_name)
        ]

    def get_connection(self, zone_a: str, zone_b: str) -> Connection | None:
        """Return the connection between two zones, if any."""
        for connection in self.connections:
            if {connection.zone_a, connection.zone_b} == {zone_a, zone_b}:
                return connection
        return None


class Path(BaseModel):
    """A route through the graph for a single drone."""

    zones: list[str]
    total_cost: float
    priority_hubs: int = 0

    @property
    def length(self) -> int:
        """Number of zones in the path."""
        return len(self.zones)
