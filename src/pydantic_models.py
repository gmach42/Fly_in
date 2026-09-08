from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

ZoneType = Literal["normal", "priority", "restricted", "blocked"]

# Cost (in "ticks") to move into a zone of this type. "blocked" zones are
# infranchissable, hence the infinite cost.
ZONE_MOVE_COST: dict[ZoneType, float] = {
    "normal": 1,
    "priority": 1,
    "restricted": 2,
    "blocked": float("inf"),
}


class Zone(BaseModel):
    """A zone (hub) in the map.

    Attributes:
        name: The unique name of the zone.
        x: The x-coordinate of the zone.
        y: The y-coordinate of the zone.
        zone_type: The kind of zone, which drives its movement cost.
        color: Optional display color.
        max_drones: The maximum number of drones allowed in the zone at once.
    """

    name: str
    x: int
    y: int
    zone_type: ZoneType = "normal"
    color: str | None = None
    max_drones: int = 1

    @field_validator("name")
    @classmethod
    def no_dashes(cls, v: str) -> str:
        if "-" in v:
            raise ValueError("Zone name cannot contain dashes")
        return v

    @field_validator("max_drones")
    @classmethod
    def positive_capacity(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("max_drones must be a positive integer")
        return v

    @property
    def move_cost(self) -> float:
        """Cost to move a drone into this zone."""
        return ZONE_MOVE_COST[self.zone_type]

    @property
    def is_blocked(self) -> bool:
        return self.zone_type == "blocked"


class Connection(BaseModel):
    """A bidirectional link between two zones.

    Attributes:
        zone_a: Name of the first zone.
        zone_b: Name of the second zone.
        max_link_capacity: Maximum number of drones allowed on the link
            at once.
    """

    zone_a: str
    zone_b: str
    max_link_capacity: int = 1

    @field_validator("max_link_capacity")
    @classmethod
    def positive_capacity(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("max_link_capacity must be a positive integer")
        return v

    @model_validator(mode="after")
    def no_self_loop(self) -> "Connection":
        if self.zone_a == self.zone_b:
            raise ValueError("A connection cannot link a zone to itself")
        return self

    def links(self, zone_name: str) -> bool:
        return zone_name in (self.zone_a, self.zone_b)

    def other_side(self, zone_name: str) -> str:
        if zone_name == self.zone_a:
            return self.zone_b
        if zone_name == self.zone_b:
            return self.zone_a
        raise ValueError(f"{zone_name!r} is not part of this connection")


class Drone(BaseModel):
    """A drone travelling through the graph.

    Attributes:
        id: Unique identifier for the drone.
        current_zone: Name of the zone where the drone currently is.
        state: Current state of the drone.
    """

    id: int
    current_zone: str
    state: Literal["idle", "waiting", "moving", "arrived"] = "idle"


class Graph(BaseModel):
    """The full map: zones, connections and the start/end hubs.

    Attributes:
        nb_drones: Number of drones to route through the map.
        start: Name of the start hub.
        end: Name of the end hub.
        zones: All zones in the map, keyed by name (includes start/end).
        connections: All connections in the map.
    """

    nb_drones: int
    start: str
    end: str
    zones: dict[str, Zone] = Field(default_factory=dict)
    connections: list[Connection] = Field(default_factory=list)

    @field_validator("nb_drones")
    @classmethod
    def positive_drones(cls, v: int) -> int:
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
        if self.start not in self.zones:
            raise ValueError(f"Unknown start hub: {self.start!r}")
        if self.end not in self.zones:
            raise ValueError(f"Unknown end hub: {self.end!r}")

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
        if zone.name in self.zones:
            raise ValueError(f"Duplicate zone name: {zone.name!r}")
        self.zones[zone.name] = zone

    def add_connection(self, connection: Connection) -> None:
        for zone_name in (connection.zone_a, connection.zone_b):
            if zone_name not in self.zones:
                raise ValueError(
                    f"Connection references unknown zone: {zone_name!r}"
                )
        self.connections.append(connection)

    def get_neighbors(self, zone_name: str) -> list[str]:
        return [
            connection.other_side(zone_name)
            for connection in self.connections
            if connection.links(zone_name)
        ]

    def get_connection(self, zone_a: str, zone_b: str) -> Connection | None:
        for connection in self.connections:
            if {connection.zone_a, connection.zone_b} == {zone_a, zone_b}:
                return connection
        return None
