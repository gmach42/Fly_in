from typing import TypeVar

from pydantic import BaseModel, ValidationError

from .pydantic_models import Connection, Graph, Zone

M = TypeVar("M", bound=BaseModel)


class ParseError(Exception):
    """Raised when a map file is invalid."""

    def __init__(self, line_no: int | None, msg: str) -> None:
        super().__init__(msg if line_no is None else f"Line {line_no}: {msg}")


class MapParser:
    """Parses a map file into a Graph."""

    def __init__(self, filepath: str) -> None:
        self.filepath = filepath
        self.nb_drones: int | None = None
        self.start: str | None = None
        self.end: str | None = None
        self.zones: list[Zone] = []
        self.connections: list[Connection] = []

    def parse(self) -> Graph:
        """Read the whole file and return the Graph; raise ParseError."""
        with open(self.filepath) as f:
            for line_no, raw_line in enumerate(f, start=1):
                line = raw_line.strip()
                if line and not line.startswith("#"):
                    self.parse_line(line, line_no)

        if self.nb_drones is None:
            raise ParseError(None, "Missing 'nb_drones' definition")
        if self.start is None:
            raise ParseError(None, "Missing 'start_hub' definition")
        if self.end is None:
            raise ParseError(None, "Missing 'end_hub' definition")

        return self.validate(
            Graph, {
                "nb_drones": self.nb_drones,
                "start": self.start,
                "end": self.end,
                "zones": self.zones,
                "connections": self.connections,
            }, None)

    def parse_line(self, line: str, line_no: int) -> None:
        """Dispatch one 'key: value' line to the matching parser."""
        key, sep, value = line.partition(":")
        key, value = key.strip(), value.strip()
        if not sep:
            raise ParseError(line_no, f"Expected 'key: value', got {line!r}")
        if self.nb_drones is None and key != "nb_drones":
            raise ParseError(line_no, "The first line must define 'nb_drones'")

        if key == "nb_drones":
            if self.nb_drones is not None:
                raise ParseError(line_no, "Duplicate 'nb_drones' definition")
            self.nb_drones = self.parse_int(value, line_no, "nb_drones")
        elif key in ("hub", "start_hub", "end_hub"):
            zone = self.parse_hub(value, line_no)
            if key == "start_hub":
                if self.start is not None:
                    raise ParseError(line_no,
                                     "Multiple 'start_hub' definitions")
                self.start = zone.name
            elif key == "end_hub":
                if self.end is not None:
                    raise ParseError(line_no, "Multiple 'end_hub' definitions")
                self.end = zone.name
            self.zones.append(zone)
        elif key == "connection":
            self.connections.append(self.parse_connection(value, line_no))
        else:
            raise ParseError(line_no, f"Unknown key: {key!r}")

    def parse_hub(self, text: str, line_no: int) -> Zone:
        """Parse 'waypoint1 1 0 [color=blue max_drones=2]' into a Zone."""
        parts = text.split(maxsplit=3)
        if len(parts) < 3:
            raise ParseError(line_no,
                             f"Expected 'name x y [metadata]', got {text!r}")
        name, x, y = parts[:3]
        metadata = self.parse_metadata(parts[3] if len(parts) == 4 else "",
                                       line_no)

        data: dict[str, object] = {"name": name}
        try:
            data["x"], data["y"] = int(x), int(y)
        except ValueError:
            raise ParseError(line_no, f"Invalid coordinates: {x!r}, {y!r}")
        if "zone" in metadata:
            data["zone_type"] = metadata["zone"]
        if "color" in metadata:
            data["color"] = metadata["color"]
        if "max_drones" in metadata:
            data["max_drones"] = self.parse_int(metadata["max_drones"],
                                                line_no, "max_drones")
        return self.validate(Zone, data, line_no)

    def parse_connection(self, text: str, line_no: int) -> Connection:
        """Parse 'start-waypoint1 [max_link_capacity=2]' into a Connection."""
        hubs, *rest = text.split(maxsplit=1) or [""]
        zone_a, sep, zone_b = hubs.partition("-")
        if not sep:
            raise ParseError(line_no, f"Expected 'hub1-hub2', got {hubs!r}")
        metadata = self.parse_metadata(rest[0] if rest else "", line_no)

        data: dict[str, object] = {"zone_a": zone_a, "zone_b": zone_b}
        if "max_link_capacity" in metadata:
            data["max_link_capacity"] = self.parse_int(
                metadata["max_link_capacity"], line_no, "max_link_capacity")
        return self.validate(Connection, data, line_no)

    @staticmethod
    def parse_int(text: str, line_no: int, field: str) -> int:
        """Parse a non-negative integer, e.g. the value of 'max_drones=4'."""
        if not text.isdigit():
            raise ParseError(
                line_no, f"Expected an integer for {field!r}, got {text!r}")
        return int(text)

    @staticmethod
    def parse_metadata(text: str, line_no: int) -> dict[str, str]:
        """Parse a trailing '[key=value key2=value2]' block, if present."""
        if not text:
            return {}
        if not (text.startswith("[") and text.endswith("]")):
            raise ParseError(line_no, f"Malformed metadata block: {text!r}")

        metadata: dict[str, str] = {}
        for token in text[1:-1].split():
            key, sep, value = token.partition("=")
            if not sep:
                raise ParseError(line_no,
                                 f"Malformed metadata entry: {token!r}")
            if key in metadata:
                raise ParseError(line_no, f"Duplicate metadata key: {key!r}")
            metadata[key] = value
        return metadata

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

    @classmethod
    def validate(cls, model: type[M], data: dict[str, object],
                 line_no: int | None) -> M:
        """Build a pydantic model, raising ParseError if it is invalid."""
        try:
            return model.model_validate(data)
        except ValidationError as exc:
            raise ParseError(line_no, cls.format_errors(exc)) from exc
