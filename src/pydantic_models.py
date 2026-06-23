from pydantic import BaseModel, field_validator, model_validator
from typing import Literal

class ZoneModel(BaseModel):
    name: str
    x: int
    y: int
    zone_type: Literal["normal", "blocked", "restricted", "priority"] = "normal"
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


class ConnectionModel(BaseModel):
    zone_a: str
    zone_b: str
    max_link_capacity: int = 1

    @model_validator(mode="after")
    def no_duplicate(self) -> "ConnectionModel":
        # zone_a != zone_b (pas de self-loop)
        if self.zone_a == self.zone_b:
            raise ValueError("A connection cannot link a zone to itself")
        return self


class MapModel(BaseModel):
    nb_drones: int
    start: ZoneModel
    end: ZoneModel
    zones: list[ZoneModel] = []
    connections: list[ConnectionModel] = []

    @field_validator("nb_drones")
    @classmethod
    def positive_drones(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("nb_drones must be a positive integer")
        return v
