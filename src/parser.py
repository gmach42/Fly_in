from typing import Callable


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
                      handlers: dict[str, Callable[[str], None]]) -> None:
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
    handler(value)


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


def parse_hub(text: str, line_no: int) -> str:
    """Parse a hub line like 'hub: waypoint1 1 0 [color=blue]'."""
    text = text.strip()
    if not text:
        raise ParseError(line_no, "Empty hub definition")
    parts = text.split(maxsplit=3)
    if len(parts) < 3:
        raise ParseError(line_no, f"Expected 'name x y [metadata]', got '{text}'")
    name, x_str, y_str = parts[:3]
    metadata_str = parts[3] if len(parts) == 4 else ""
    try:
        x = float(x_str)
        y = float(y_str)
    except ValueError:
        raise ParseError(line_no, f"Invalid coordinates: '{x_str}', '{y_str}'")
    metadata = parse_metadata(metadata_str, line_no)
    return name, x, y, metadata


def parse_start_hub(text: str, line_no: int) -> str:
    """Parse a start hub line like 'start_hub: start 0 0 [color=green]'."""
    return parse_hub(text, line_no)


def parse_end_hub(text: str, line_no: int) -> str:
    """Parse an end hub line like 'end_hub: goal 3 0 [color=red max_drones=4]'."""
    return parse_hub(text, line_no)


def parse_connection(text: str, line_no: int) -> tuple[str, str, dict[str, str]]:
    """Parse a connection line like 'connection: start-waypoint1 [max_link_capacity=2]'."""
    text = text.strip()
    if not text:
        raise ParseError(line_no, "Empty connection definition")
    parts = text.split(maxsplit=1)
    if len(parts) < 1:
        raise ParseError(line_no, f"Expected 'hub1-hub2 [metadata]', got '{text}'")
    hubs_str = parts[0]
    metadata_str = parts[1] if len(parts) == 2 else ""
    if "-" not in hubs_str:
        raise ParseError(line_no, f"Expected 'hub1-hub2', got '{hubs_str}'")
    hub1, hub2 = hubs_str.split("-", 1)
    metadata = parse_metadata(metadata_str, line_no)
    return hub1.strip(), hub2.strip(), metadata
