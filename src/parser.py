from typing import TypeVar

from pydantic import BaseModel, ValidationError

from .pydantic_models import Connection, Graph, Zone

M = TypeVar("M", bound=BaseModel)


class ParseError(Exception):

    def __init__(self, line_no: int | None, msg: str) -> None:
        super().__init__(msg if line_no is None else f"Line {line_no}: {msg}")


def format_errors(exc: ValidationError) -> str:
    """Format Pydantic validation errors for display."""
    lines = []
    for err in exc.errors(include_url=False, include_context=False):
        loc = ".".join(str(p) for p in err["loc"])
        msg = err["msg"].removeprefix("Value error, ")
        prefix = f"{loc}: " if loc else ""
        lines.append(f"  {prefix}{msg}")
    return "\n" + "\n".join(lines)


def parse_int(text: str, line_no: int, field: str) -> int:
    """Parse a non-negative integer, e.g. the value of 'max_drones=4'."""
    if not text.isdigit():
        raise ParseError(line_no,
                         f"Expected an integer for {field!r}, got {text!r}")
    return int(text)


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
            raise ParseError(line_no, f"Malformed metadata entry: {token!r}")
        if key in metadata:
            raise ParseError(line_no, f"Duplicate metadata key: {key!r}")
        metadata[key] = value
    return metadata


def validate(model: type[M], data: dict[str, object],
             line_no: int | None) -> M:
    """Build a pydantic model, turning validation errors into ParseError."""
    try:
        return model.model_validate(data)
    except ValidationError as exc:
        raise ParseError(line_no, format_errors(exc)) from exc


def parse_hub(text: str, line_no: int) -> Zone:
    """Parse 'waypoint1 1 0 [color=blue max_drones=2]' into a Zone."""
    parts = text.split(maxsplit=3)
    if len(parts) < 3:
        raise ParseError(line_no,
                         f"Expected 'name x y [metadata]', got {text!r}")
    name, x, y = parts[:3]
    metadata = parse_metadata(parts[3] if len(parts) == 4 else "", line_no)

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
        data["max_drones"] = parse_int(metadata["max_drones"], line_no,
                                       "max_drones")
    return validate(Zone, data, line_no)


def parse_connection(text: str, line_no: int) -> Connection:
    """Parse 'start-waypoint1 [max_link_capacity=2]' into a Connection."""
    hubs, *rest = text.split(maxsplit=1) or [""]
    zone_a, sep, zone_b = hubs.partition("-")
    if not sep:
        raise ParseError(line_no, f"Expected 'hub1-hub2', got {hubs!r}")
    metadata = parse_metadata(rest[0] if rest else "", line_no)

    data: dict[str, object] = {"zone_a": zone_a, "zone_b": zone_b}
    if "max_link_capacity" in metadata:
        data["max_link_capacity"] = parse_int(metadata["max_link_capacity"],
                                              line_no, "max_link_capacity")
    return validate(Connection, data, line_no)


def parse_map_file(filepath: str) -> Graph:
    """Parse a map file into a Graph; raise ParseError if it is invalid."""
    nb_drones: int | None = None
    start: str | None = None
    end: str | None = None
    zones: list[Zone] = []
    connections: list[Connection] = []

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
                nb_drones = parse_int(value, line_no, "nb_drones")
            elif key in ("hub", "start_hub", "end_hub"):
                zone = parse_hub(value, line_no)
                if key == "start_hub":
                    if start is not None:
                        raise ParseError(line_no,
                                         "Multiple 'start_hub' definitions")
                    start = zone.name
                elif key == "end_hub":
                    if end is not None:
                        raise ParseError(line_no,
                                         "Multiple 'end_hub' definitions")
                    end = zone.name
                zones.append(zone)
            elif key == "connection":
                connections.append(parse_connection(value, line_no))
            else:
                raise ParseError(line_no, f"Unknown key: {key!r}")

    if nb_drones is None:
        raise ParseError(None, "Missing 'nb_drones' definition")
    if start is None:
        raise ParseError(None, "Missing 'start_hub' definition")
    if end is None:
        raise ParseError(None, "Missing 'end_hub' definition")

    return validate(
        Graph, {
            "nb_drones": nb_drones,
            "start": start,
            "end": end,
            "zones": zones,
            "connections": connections,
        }, None)
