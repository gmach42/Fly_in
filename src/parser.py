class ParseError(Exception):
    def __init__(self, line_no: int, msg: str) -> None:
        super().__init__(f"Line {line_no}: {msg}")

def parse_config(filepath: str) -> dict:
    result = {}
    with open(filepath, 'r') as file:
        for line_no, raw in enumarate(f, start=1):
            line = raw.strip()
            if not line or line.startswith('#'):
                continue
            if ":" not in line:
                raise ParseError(line_no, f"Expected 'key: value', got '{line}'")
            key, _, value = line.partition(":")
            key = key.strip()
            value = value.strip()
            if not key:
                raise ParseError(line_no, "Empty key")
            result[key] = value
    return result
