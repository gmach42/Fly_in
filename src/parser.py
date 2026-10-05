"""Parser turning a map file into a Graph."""

import os
import sys
from typing import TypeVar

from pydantic import BaseModel, ValidationError
from pygame.colordict import THECOLORS

from .pydantic_models import Connection, Graph, Zone

M = TypeVar("M", bound=BaseModel)

MAX_FILE_SIZE = 1_000_000
HUB_METADATA = ("zone", "color", "max_drones")
CONNECTION_METADATA = ("max_link_capacity", )


class ParseError(Exception):
    """Raised when a map file is invalid."""

    def __init__(self, line_no: int | None, msg: str) -> None:
        """Prefix msg with the line number when there is one."""
        super().__init__(msg if line_no is None else f"Line {line_no}: {msg}")


class MapParser:
    """Parses a map file into a Graph."""

    @staticmethod
    def format_errors(exc: ValidationError) -> str:
        """Format Pydantic validation errors for display."""
        lines = []
        for err in exc.errors(include_url=False, include_context=False):
            loc = ".".join(str(p) for p in err["loc"])
            msg = err["msg"].removeprefix("Value error, ")
            prefix = f"{loc}: " if loc else ""
            lines.append(f"  {prefix}{msg}")
        return "\n" + "\n".join(lines)

    @staticmethod
    def parse_int(text: str, line_no: int, field: str) -> int:
        """Parse a non-negative integer, e.g. the value of 'max_drones=4'."""
        if not (text.isascii() and text.isdigit()):
            raise ParseError(
                line_no, f"Expected an integer for {field!r}, got {text!r}")
        return int(text)

    @staticmethod
    def parse_metadata(text: str, line_no: int,
                       allowed: tuple[str, ...]) -> dict[str, str]:
        """Parse a trailing '[key=value key2=value2]' block, if present."""
        if not text:
            return {}
        if not (text.startswith("[") and text.endswith("]")):
            raise ParseError(line_no, f"Malformed metadata block: {text!r}")

        metadata: dict[str, str] = {}
        for token in text[1:-1].split(" "):
            if not token:
                raise ParseError(line_no, "Metadata entries must be separated "
                                 f"by a single space: {text!r}")
            key, sep, value = token.partition("=")
            if not sep:
                raise ParseError(line_no,
                                 f"Malformed metadata entry: {token!r}")
            if key not in allowed:
                raise ParseError(
                    line_no, f"Unknown metadata key: {key!r} "
                    f"(allowed: {', '.join(allowed)})")
            if key in metadata:
                raise ParseError(line_no, f"Duplicate metadata key: {key!r}")
            metadata[key] = value
        return metadata

    @staticmethod
    def validate(model: type[M], data: dict[str, object],
                 line_no: int | None) -> M:
        """Build a pydantic model, raising ParseError if it is invalid."""
        try:
            return model.model_validate(data)
        except ValidationError as exc:
            raise ParseError(line_no, MapParser.format_errors(exc)) from exc

    @staticmethod
    def parse_hub(text: str, line_no: int, filepath: str,
                  unlimited: bool = False) -> Zone:
        """Parse 'waypoint1 1 0 [color=blue max_drones=2]' into a Zone."""
        parts = text.split(maxsplit=3)
        if len(parts) < 3:
            raise ParseError(line_no,
                             f"Expected 'name x y [metadata]', got {text!r}")
        name, x, y = parts[:3]
        metadata = MapParser.parse_metadata(
            parts[3] if len(parts) == 4 else "", line_no, HUB_METADATA)
        # max_drones is ignored on unlimited zones (the start and end hubs).
        if unlimited:
            metadata.pop("max_drones", None)

        data: dict[str, object] = {"name": name}
        try:
            data["x"], data["y"] = int(x), int(y)
        except ValueError:
            raise ParseError(line_no, f"Invalid coordinates: {x!r}, {y!r}")
        if "zone" in metadata:
            data["zone_type"] = metadata["zone"]
        if "color" in metadata:
            color = metadata["color"].lower()
            if color in THECOLORS:
                data["color"] = color
            else:
                print(f"{filepath}:{line_no}: unknown color "
                      f"{metadata['color']!r}, using default color",
                      file=sys.stderr)
        if "max_drones" in metadata:
            data["max_drones"] = MapParser.parse_int(metadata["max_drones"],
                                                     line_no, "max_drones")
        return MapParser.validate(Zone, data, line_no)

    @staticmethod
    def parse_connection(text: str, line_no: int) -> Connection:
        """Parse 'start-waypoint1 [max_link_capacity=2]' into a Connection."""
        hubs, *rest = text.split(maxsplit=1) or [""]
        zone_a, sep, zone_b = hubs.partition("-")
        if not sep:
            raise ParseError(line_no, f"Expected 'hub1-hub2', got {hubs!r}")
        metadata = MapParser.parse_metadata(rest[0] if rest else "", line_no,
                                            CONNECTION_METADATA)

        data: dict[str, object] = {"zone_a": zone_a, "zone_b": zone_b}
        if "max_link_capacity" in metadata:
            data["max_link_capacity"] = MapParser.parse_int(
                metadata["max_link_capacity"], line_no, "max_link_capacity")
        return MapParser.validate(Connection, data, line_no)

    @staticmethod
    def check_zone(zone: Zone, zones: dict[str, Zone],
                   positions: dict[tuple[int, int],
                                   str], line_no: int) -> None:
        """Reject a zone whose name or position is already used."""
        if zone.name in zones:
            raise ParseError(line_no, f"Duplicate zone name: {zone.name!r}")
        other = positions.get((zone.x, zone.y))
        if other is not None:
            raise ParseError(
                line_no, f"Zones {other!r} and {zone.name!r} share position "
                f"({zone.x}, {zone.y})")

    @staticmethod
    def check_connection(connection: Connection, zones: dict[str, Zone],
                         pairs: set[frozenset[str]], line_no: int) -> None:
        """Reject a connection to an undefined zone, or a duplicate one."""
        for zone_name in (connection.zone_a, connection.zone_b):
            if zone_name not in zones:
                raise ParseError(
                    line_no, f"Connection references undefined zone: "
                    f"{zone_name!r} (zones must be defined before)")
        if frozenset((connection.zone_a, connection.zone_b)) in pairs:
            raise ParseError(
                line_no, "Duplicate connection: "
                f"{connection.zone_a}-{connection.zone_b}")

    @staticmethod
    def parse_map_file(filepath: str) -> Graph:
        """Parse a map file into a Graph; raise ParseError if it is invalid."""
        nb_drones: int | None = None
        start: str | None = None
        end: str | None = None
        zones: dict[str, Zone] = {}
        positions: dict[tuple[int, int], str] = {}
        connections: list[Connection] = []
        pairs: set[frozenset[str]] = set()

        if not os.path.isfile(filepath):
            raise ParseError(None, f"Not a regular file: {filepath!r}")
        if os.path.getsize(filepath) > MAX_FILE_SIZE:
            raise ParseError(None,
                             f"File is larger than {MAX_FILE_SIZE} bytes")
        with open(filepath) as f:
            for line_no, raw_line in enumerate(f, start=1):
                line = raw_line.strip()
                if not line or line.startswith("#"):
                    continue
                key, sep, value = line.partition(":")
                key, value = key.strip(), value.strip()
                if not sep:
                    raise ParseError(line_no,
                                     f"Expected 'key: value', got {line!r}")
                if nb_drones is None and key != "nb_drones":
                    raise ParseError(line_no,
                                     "The first line must define 'nb_drones'")

                if key == "nb_drones":
                    if nb_drones is not None:
                        raise ParseError(line_no,
                                         "Duplicate 'nb_drones' definition")
                    nb_drones = MapParser.parse_int(value, line_no,
                                                    "nb_drones")
                    if nb_drones == 0:
                        raise ParseError(
                            line_no, "nb_drones must be a positive integer")
                elif key in ("hub", "start_hub", "end_hub"):
                    zone = MapParser.parse_hub(value,
                                               line_no,
                                               filepath,
                                               unlimited=key != "hub")
                    MapParser.check_zone(zone, zones, positions, line_no)
                    if key == "start_hub":
                        if start is not None:
                            raise ParseError(
                                line_no, "Multiple 'start_hub' definitions")
                        start = zone.name
                    elif key == "end_hub":
                        if end is not None:
                            raise ParseError(line_no,
                                             "Multiple 'end_hub' definitions")
                        end = zone.name
                    zones[zone.name] = zone
                    positions[(zone.x, zone.y)] = zone.name
                elif key == "connection":
                    connection = MapParser.parse_connection(value, line_no)
                    MapParser.check_connection(connection, zones, pairs,
                                               line_no)
                    pairs.add(frozenset(
                        (connection.zone_a, connection.zone_b)))
                    connections.append(connection)
                else:
                    raise ParseError(line_no, f"Unknown key: {key!r}")

        if nb_drones is None:
            raise ParseError(None, "Missing 'nb_drones' definition")
        if start is None:
            raise ParseError(None, "Missing 'start_hub' definition")
        if end is None:
            raise ParseError(None, "Missing 'end_hub' definition")

        return MapParser.validate(
            Graph, {
                "nb_drones": nb_drones,
                "start": start,
                "end": end,
                "zones": zones,
                "connections": connections,
            }, None)
