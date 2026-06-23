ZONE_TYPES = {"normal", "blocked", "restricted", "priority"}

class Zone:
    def __init__(self, name, x, y, zone_type, color, max_drones):
        self.name = name
        self.x = x
        self.y = y
        if zone_type in ZONE_TYPES:
            self.zone_type = zone_type
        else:
            raise ValueError(f"Invalid zone type: {zone_type}. Must be one of {ZONE_TYPES}.")
        self.color = color
        self.max_drones = max_drones


