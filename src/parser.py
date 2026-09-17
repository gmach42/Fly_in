from typing import Callable

from pydantic import ValidationError

from pydantic_models import Connection, Graph, Zone


class ParseError(Exception):

    def __init__(self, line_no: int, msg: str) -> None:
        super().__init__(f"Line {line_no}: {msg}")


# def parse_config(filepath: str) -> dict:
#     result = {}
#     with open(filepath, 'r') as file:
#         for line_no, raw in enumerate(file, start=1):
#             line = raw.strip()
#             if not line or line.startswith('#'):
#                 continue
#             if ":" not in line:
#                 raise ParseError(line_no, f"Expected 'key: value', got '{line}'")
#             key, _, value = line.partition(":")
#             key = key.strip()
#             value = value.strip()
#             if not key:
#                 raise ParseError(line_no, "Empty key")
#             result[key] = value
#     return result

# Example of input:

# # commentaire (ligne entière, ignorée)
# nb_drones: 2

# start_hub: start 0 0 [color=green]
# hub: waypoint1 1 0 [color=blue]
# hub: slow_path1 1 -1 [zone=restricted color=red]
# end_hub: goal 3 0 [color=red max_drones=4]

# connection: start-waypoint1
# connection: merge_point-goal [max_link_capacity=2]

KEYS = {
    "nb_drones",
    "start_hub",
    "hub",
    "end_hub",
    "connection",
}


def dispatch_per_line(line: str, line_no: int,
                      handlers: dict[str, Callable[[str, int], None]]) -> None:
    """Dispatch a line to the appropriate handler based on its prefix."""

    if not line or line.startswith("#"):
        return
    if ":" not in line:
        raise ParseError(line_no, f"Expected 'key: value', got '{line}'")
    key, _, value = line.partition(":")
    key = key.strip()
    value = value.strip()
    if not key:
        raise ParseError(line_no, "Empty key")
    handler = handlers.get(key)
    if handler is None:
        raise ParseError(line_no, f"Unknown key: {key!r}")
    handler(value, line_no)


def parse_metadata(text: str, line_no: int) -> dict[str, str]:
    """Parse a trailing '[key=value key2=value2]' block, if present."""
    text = text.strip()
    if not text:
        return {}
    if not (text.startswith("[") and text.endswith("]")):
        raise ParseError(line_no, f"Malformed metadata block: {text!r}")

    metadata: dict[str, str] = {}
    for token in text[1:-1].split():
        if "=" not in token:
            raise ParseError(line_no, f"Malformed metadata entry: {token!r}")
        key, _, value = token.partition("=")
        if key in metadata:
            raise ParseError(line_no, f"Duplicate metadata key: {key!r}")
        metadata[key] = value
    return metadata


def parse_nb_drones(text: str, line_no: int) -> int:
    """Parse the number of drones from a line like 'nb_drones: 2'."""
    text = text.strip()
    if not text.isdigit():
        raise ParseError(line_no,
                         f"Expected an integer for nb_drones, got '{text}'")
    return int(text)


HubTuple = tuple[str, int, int, dict[str, str]]


def parse_hub(text: str, line_no: int) -> HubTuple:
    """Parse a hub line like 'hub: waypoint1 1 0 [color=blue]'."""
    text = text.strip()
    if not text:
        raise ParseError(line_no, "Empty hub definition")
    parts = text.split(maxsplit=3)
    if len(parts) < 3:
        raise ParseError(
            line_no, f"Expected 'name x y [metadata]', got '{text}'"
        )
    name, x_str, y_str = parts[:3]
    metadata_str = parts[3] if len(parts) == 4 else ""
    try:
        x = int(x_str)
        y = int(y_str)
    except ValueError:
        raise ParseError(line_no, f"Invalid coordinates: '{x_str}', '{y_str}'")
    metadata = parse_metadata(metadata_str, line_no)
    return name, x, y, metadata


def parse_start_hub(text: str, line_no: int) -> HubTuple:
    """Parse a start hub line like 'start_hub: start 0 0 [color=green]'."""
    return parse_hub(text, line_no)


def parse_end_hub(text: str, line_no: int) -> HubTuple:
    """Parse 'end_hub: goal 3 0 [color=red max_drones=4]'."""
    return parse_hub(text, line_no)


ConnectionTuple = tuple[str, str, dict[str, str]]


def parse_connection(text: str, line_no: int) -> ConnectionTuple:
    """Parse 'connection: start-waypoint1 [max_link_capacity=2]'."""
    text = text.strip()
    if not text:
        raise ParseError(line_no, "Empty connection definition")
    parts = text.split(maxsplit=1)
    if len(parts) < 1:
        raise ParseError(
            line_no, f"Expected 'hub1-hub2 [metadata]', got '{text}'"
        )
    hubs_str = parts[0]
    metadata_str = parts[1] if len(parts) == 2 else ""
    if "-" not in hubs_str:
        raise ParseError(line_no, f"Expected 'hub1-hub2', got '{hubs_str}'")
    hub1, hub2 = hubs_str.split("-", 1)
    metadata = parse_metadata(metadata_str, line_no)
    return hub1.strip(), hub2.strip(), metadata


def _parse_int_metadata(text: str, line_no: int, field: str) -> int:
    """Parse an integer metadata value, e.g. 'max_drones=4'."""
    if not text.isdigit():
        raise ParseError(
            line_no, f"Expected an integer for {field!r}, got {text!r}"
        )
    return int(text)


def _build_zone(
    name: str, x: int, y: int, metadata: dict[str, str], line_no: int
) -> Zone:
    """Turn a parsed hub tuple into a Zone, casting metadata values."""
    kwargs: dict[str, object] = {"name": name, "x": x, "y": y}
    if "zone" in metadata:
        kwargs["zone_type"] = metadata["zone"]
    if "color" in metadata:
        kwargs["color"] = metadata["color"]
    if "max_drones" in metadata:
        kwargs["max_drones"] = _parse_int_metadata(
            metadata["max_drones"], line_no, "max_drones"
        )
    try:
        return Zone(**kwargs)
    except ValidationError as exc:
        raise ParseError(line_no, str(exc)) from exc


def _build_connection(
    zone_a: str, zone_b: str, metadata: dict[str, str], line_no: int
) -> Connection:
    """Turn a parsed connection tuple into a Connection, casting metadata."""
    kwargs: dict[str, object] = {"zone_a": zone_a, "zone_b": zone_b}
    if "max_link_capacity" in metadata:
        kwargs["max_link_capacity"] = _parse_int_metadata(
            metadata["max_link_capacity"], line_no, "max_link_capacity"
        )
    try:
        return Connection(**kwargs)
    except ValidationError as exc:
        raise ParseError(line_no, str(exc)) from exc


def parse_map_file(filepath: str) -> Graph:
    """Parse a full map file and build the corresponding Graph.

    Raises:
        ParseError: On any malformed line, a duplicate 'nb_drones'
            definition, more than one 'start_hub'/'end_hub', or a
            missing 'nb_drones'/'start_hub'/'end_hub'.
        ParseError: Wrapping a pydantic ValidationError if the resulting
            Zone/Connection/Graph is inconsistent (duplicate zone name,
            unknown start/end hub, connection to an unknown zone,
            duplicate connection, non-positive capacity, ...).
    """
    state: dict[str, object] = {"nb_drones": None, "start": None, "end": None}
    zones: list[Zone] = []
    connections: list[Connection] = []

    def handle_nb_drones(value: str, line_no: int) -> None:
        if state["nb_drones"] is not None:
            raise ParseError(line_no, "Duplicate 'nb_drones' definition")
        state["nb_drones"] = parse_nb_drones(value, line_no)

    def handle_hub(value: str, line_no: int) -> None:
        name, x, y, metadata = parse_hub(value, line_no)
        zones.append(_build_zone(name, x, y, metadata, line_no))

    def handle_start_hub(value: str, line_no: int) -> None:
        if state["start"] is not None:
            raise ParseError(line_no, "Multiple 'start_hub' definitions")
        name, x, y, metadata = parse_start_hub(value, line_no)
        state["start"] = name
        zones.append(_build_zone(name, x, y, metadata, line_no))

    def handle_end_hub(value: str, line_no: int) -> None:
        if state["end"] is not None:
            raise ParseError(line_no, "Multiple 'end_hub' definitions")
        name, x, y, metadata = parse_end_hub(value, line_no)
        state["end"] = name
        zones.append(_build_zone(name, x, y, metadata, line_no))

    def handle_connection(value: str, line_no: int) -> None:
        zone_a, zone_b, metadata = parse_connection(value, line_no)
        connections.append(
            _build_connection(zone_a, zone_b, metadata, line_no)
        )

    handlers: dict[str, Callable[[str, int], None]] = {
        "nb_drones": handle_nb_drones,
        "hub": handle_hub,
        "start_hub": handle_start_hub,
        "end_hub": handle_end_hub,
        "connection": handle_connection,
    }

    with open(filepath) as f:
        for line_no, raw_line in enumerate(f, start=1):
            dispatch_per_line(raw_line.strip(), line_no, handlers)

    if state["nb_drones"] is None:
        raise ParseError(0, "Missing 'nb_drones' definition")
    if state["start"] is None:
        raise ParseError(0, "Missing 'start_hub' definition")
    if state["end"] is None:
        raise ParseError(0, "Missing 'end_hub' definition")

    try:
        return Graph(
            nb_drones=state["nb_drones"],
            start=state["start"],
            end=state["end"],
            zones=zones,
            connections=connections,
        )
    except ValidationError as exc:
        raise ParseError(0, str(exc)) from exc
