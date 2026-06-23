# Graph : zones dictionary + connections list + method get_neighbors(zone)

class Graph:
    def __init__(self):
        self.zones = {}
        self.connections = []

    def add_zone(self, zone):
        self.zones[zone.name] = zone

    def add_connection(self, connection):
        self.connections.append(connection)

    def get_neighbors(self, zone_name):
        neighbors = []
        for connection in self.connections:
            if connection.zone_a.name == zone_name:
                neighbors.append(connection.zone_b)
            elif connection.zone_b.name == zone_name:
                neighbors.append(connection.zone_a)
        return neighbors
