import os
import sys
from abc import ABC, abstractmethod
from enum import Enum
from pathlib import Path

import pygame
import pygame.freetype

from .parser import MapParser, ParseError
from .pathfinding import NoPathError
from .pydantic_models import Graph, Zone
from .simulation import Simulation, Step

MAPS_DIR = Path(__file__).parent.parent / "maps"
DRONE_IMAGE = Path(__file__).parent.parent / "potato.png"
DIFFICULTIES = ["easy", "medium", "hard", "challenger"]

WHITE = (255, 255, 255)
BLUE = (0, 0, 255)
RED = (255, 0, 0)
GREEN = (0, 255, 0)
BLACK = (0, 0, 0)
LIGHT_BLUE = (106, 159, 181)

MENU_SCREEN_SIZE = (800, 600)

SCALE = 150
MARGIN = 80
HUB_RADIUS = 30
MAX_WINDOW_WIDTH = 1800
TURNS_PER_SECOND = 1.0
FPS = 60


class GameState(Enum):
    TITLE = 1
    MAP_SELECT = 2
    SIMULATION = 3
    QUIT = 4


Color = tuple[int, int, int]
Action = GameState | str


class MapCatalog:
    """Lists the map files stored under a maps directory."""

    def __init__(self, maps_dir: Path) -> None:
        self.maps_dir = maps_dir

    def maps(self, difficulty: str) -> list[str]:
        """Return map names for the given difficulty, formatted for display."""
        folder = self.maps_dir / difficulty
        try:
            return sorted(p.stem.replace("_", " ")
                          for p in folder.glob("*.txt"))
        except OSError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return []

    def find(self, map_name: str) -> Path:
        """Find the .txt file path for a given display map name."""
        filename = map_name.replace(" ", "_") + ".txt"
        for difficulty in DIFFICULTIES:
            path = self.maps_dir / difficulty / filename
            if path.exists():
                return path
        raise FileNotFoundError(f"Map '{map_name}' not found.")


class MapView:
    """Converts grid coordinates to pixels and draws the map."""

    def __init__(self, graph: Graph) -> None:
        self.graph = graph
        zones = list(graph.zones.values())
        self.max_x = max(z.x for z in zones)
        self.max_y = max(z.y for z in zones)
        self.min_y = min(z.y for z in zones)
        self.scale = min(SCALE,
                         (MAX_WINDOW_WIDTH - 2 * MARGIN) // max(self.max_x, 1))
        self.hub_radius = HUB_RADIUS * self.scale // SCALE
        self.font = pygame.freetype.SysFont("Arial", 12, bold=True)

    @property
    def size(self) -> tuple[int, int]:
        """Window size needed to show the whole map."""
        width = self.max_x * self.scale + 2 * MARGIN
        height = (self.max_y - self.min_y + 1) * self.scale + 2 * MARGIN
        return (width, height)

    @property
    def offset(self) -> tuple[int, int]:
        """Pixel position of the grid origin."""
        return (MARGIN, self.size[1] // 2)

    def to_px(self, x: float, y: float) -> tuple[float, float]:
        """Pixel position of a grid point."""
        offset_x, offset_y = self.offset
        return (offset_x + x * self.scale, offset_y - y * self.scale)

    def step_to_px(self, step: Step) -> tuple[float, float]:
        """Pixel position of a drone, mid-connection when in flight."""
        zone_a = self.graph.zones[step[0]]
        zone_b = self.graph.zones[step[1]]
        return self.to_px((zone_a.x + zone_b.x) / 2,
                          (zone_a.y + zone_b.y) / 2)

    def draw(self, surface: pygame.Surface) -> None:
        """Draw every connection, then every hub."""
        for connection in self.graph.connections:
            self.draw_connection(surface, self.graph.zones[connection.zone_a],
                                 self.graph.zones[connection.zone_b])
        for zone in self.graph.zones.values():
            self.draw_hub(surface, zone)

    def draw_connection(self, surface: pygame.Surface,
                        zone_a: Zone, zone_b: Zone) -> None:
        """Draw a line between two zones."""
        pygame.draw.line(surface, BLACK, self.to_px(zone_a.x, zone_a.y),
                         self.to_px(zone_b.x, zone_b.y), 2)

    def draw_hub(self, surface: pygame.Surface, zone: Zone) -> None:
        """Draw a zone circle in its map color, with its name below."""
        pos = self.to_px(zone.x, zone.y)
        try:
            color = pygame.Color(zone.color or "gray")
        except ValueError:
            color = pygame.Color("gray")
        pygame.draw.circle(surface, color, pos, self.hub_radius)
        label_surf, label_rect = self.font.render(zone.name, BLACK)
        label_rect.centerx = int(pos[0])
        label_rect.top = int(pos[1]) + self.hub_radius + 4
        surface.blit(label_surf, label_rect)


class DroneSprite:
    """A numbered drone gliding along its simulation plan."""

    def __init__(self, index: int, simulation: Simulation, view: MapView,
                 image: pygame.Surface, font: pygame.freetype.Font) -> None:
        self.index = index
        self.simulation = simulation
        self.view = view
        self.image = image
        self.label, _ = font.render(str(index + 1), RED)
        size = image.get_width()
        self.shift = ((index % 3 - 1) * size / 3,
                      (index // 3 % 3 - 1) * size / 3)

    def center(self, progress: float) -> tuple[float, float]:
        """Pixel position of the drone at a fractional turn."""
        turn, fraction = int(progress), progress - int(progress)
        x0, y0 = self.view.step_to_px(
            self.simulation.position(self.index, turn))
        x1, y1 = self.view.step_to_px(
            self.simulation.position(self.index, turn + 1))
        return (x0 + (x1 - x0) * fraction + self.shift[0],
                y0 + (y1 - y0) * fraction + self.shift[1])

    def draw(self, surface: pygame.Surface, progress: float) -> None:
        """Draw the drone image with its number on top."""
        center = self.center(progress)
        surface.blit(self.image, self.image.get_rect(center=center))
        surface.blit(self.label, self.label.get_rect(center=center))


class UIElement:
    """A clickable UI element that highlights on hover."""

    def __init__(self,
                 center_position: tuple[int, int],
                 text: str,
                 font_size: float,
                 bg_rgb: Color,
                 text_rgb: Color,
                 action: Action | None = None) -> None:
        self.mouse_over = False
        self.action = action

        default_image = self.text_surface(text, font_size, text_rgb, bg_rgb)
        highlighted_image = self.text_surface(text, font_size * 1.2,
                                              text_rgb, bg_rgb)

        self.images = [default_image, highlighted_image]
        self.rects = [
            default_image.get_rect(center=center_position),
            highlighted_image.get_rect(center=center_position),
        ]

    @staticmethod
    def text_surface(text: str, font_size: float, text_rgb: Color,
                     bg_rgb: Color) -> pygame.Surface:
        """Return a surface with text written on it."""
        font = pygame.freetype.SysFont("Courier", int(font_size), bold=True)
        surface, _ = font.render(text=text, fgcolor=text_rgb, bgcolor=bg_rgb)
        return surface.convert_alpha()

    @property
    def image(self) -> pygame.Surface:
        return self.images[1] if self.mouse_over else self.images[0]

    @property
    def rect(self) -> pygame.Rect:
        return self.rects[1] if self.mouse_over else self.rects[0]

    def update(
        self, mouse_pos: tuple[int, int], mouse_up: bool
    ) -> Action | None:
        if self.rect.collidepoint(mouse_pos):
            self.mouse_over = True
            if mouse_up:
                return self.action
        else:
            self.mouse_over = False
        return None

    def draw(self, surface: pygame.Surface) -> None:
        surface.blit(self.image, self.rect)


class Screen(ABC):
    """A window state with buttons, run until it returns the next state."""

    escape_state = GameState.TITLE

    def __init__(self, app: "FlyInApp") -> None:
        self.app = app
        self.buttons: list[UIElement] = []

    @abstractmethod
    def draw(self) -> None:
        """Draw everything except the buttons."""

    @abstractmethod
    def on_action(self, action: Action) -> GameState:
        """Return the next state after a button was clicked."""

    def run(self) -> GameState:
        """Loop over events and frames until the state changes."""
        clock = pygame.time.Clock()
        while True:
            clock.tick(FPS)
            mouse_up = False
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    return GameState.QUIT
                if (event.type == pygame.KEYDOWN
                        and event.key == pygame.K_ESCAPE):
                    return self.escape_state
                if event.type == pygame.MOUSEBUTTONUP and event.button == 1:
                    mouse_up = True

            self.draw()
            for btn in self.buttons:
                action = btn.update(pygame.mouse.get_pos(), mouse_up)
                if action is not None:
                    return self.on_action(action)
                btn.draw(self.app.screen)

            pygame.display.flip()


class TitleScreen(Screen):
    """Difficulty selection."""

    escape_state = GameState.QUIT

    def __init__(self, app: "FlyInApp") -> None:
        super().__init__(app)
        cx = app.screen.get_width() // 2
        self.title = UIElement((cx, 100), "Fly-in", 50, LIGHT_BLUE, WHITE)
        self.buttons = [
            UIElement((cx, 220 + i * 70), diff.capitalize(), 30,
                      LIGHT_BLUE, WHITE, action=diff)
            for i, diff in enumerate(DIFFICULTIES)
        ]
        self.buttons.append(UIElement(
            (cx, 220 + len(DIFFICULTIES) * 70), "Quit", 30,
            LIGHT_BLUE, WHITE, action=GameState.QUIT))

    def draw(self) -> None:
        self.app.screen.fill(LIGHT_BLUE)
        self.title.draw(self.app.screen)

    def on_action(self, action: Action) -> GameState:
        if isinstance(action, GameState):
            return action
        self.app.difficulty = action
        return GameState.MAP_SELECT


class MapSelectScreen(Screen):
    """Map selection for the chosen difficulty."""

    def __init__(self, app: "FlyInApp") -> None:
        super().__init__(app)
        cx = app.screen.get_width() // 2
        maps = app.catalog.maps(app.difficulty)
        self.title = UIElement((cx, 60), app.difficulty.capitalize(), 40,
                               LIGHT_BLUE, WHITE)
        self.buttons = [
            UIElement((cx, 150 + i * 65), name, 25, LIGHT_BLUE, WHITE,
                      action=name)
            for i, name in enumerate(maps)
        ]
        self.buttons.append(UIElement(
            (cx, 150 + len(maps) * 65 + 40), "Return", 25,
            LIGHT_BLUE, WHITE, action=GameState.TITLE))

    def draw(self) -> None:
        self.app.screen.fill(LIGHT_BLUE)
        self.title.draw(self.app.screen)

    def on_action(self, action: Action) -> GameState:
        if isinstance(action, GameState):
            return action
        self.app.map_name = action
        return GameState.SIMULATION


class SimulationScreen(Screen):
    """Animates the drones of a simulated map."""

    def __init__(self, app: "FlyInApp", simulation: Simulation,
                 nb_turns: int) -> None:
        super().__init__(app)
        self.nb_turns = nb_turns
        self.view = MapView(simulation.graph)
        width, height = self.view.size
        app.screen = pygame.display.set_mode((width, height))
        pygame.display.set_caption(f"Fly-in - {app.map_name}")

        drone_size = self.view.hub_radius
        drone_image = pygame.transform.smoothscale(
            pygame.image.load(DRONE_IMAGE).convert_alpha(),
            (drone_size, drone_size),
        )
        drone_font = pygame.freetype.SysFont("Arial", max(8, drone_size // 2),
                                             bold=True)
        self.drones = [
            DroneSprite(i, simulation, self.view, drone_image, drone_font)
            for i in range(simulation.graph.nb_drones)
        ]
        self.buttons = [UIElement((140, height - 40), "Return to main menu",
                                  20, WHITE, LIGHT_BLUE,
                                  action=GameState.TITLE)]
        self.start_ticks = pygame.time.get_ticks()

    def draw(self) -> None:
        self.app.screen.fill(WHITE)
        self.view.draw(self.app.screen)
        elapsed = (pygame.time.get_ticks() - self.start_ticks) / 1000
        progress = min(elapsed * TURNS_PER_SECOND, self.nb_turns)
        for drone in self.drones:
            drone.draw(self.app.screen, progress)

    def on_action(self, action: Action) -> GameState:
        return action if isinstance(action, GameState) else GameState.TITLE


class FlyInApp:
    """Opens the window and switches between screens until the user quits."""

    def __init__(self) -> None:
        pygame.init()
        self.screen = pygame.display.set_mode(MENU_SCREEN_SIZE)
        pygame.display.set_caption("Fly-in")
        self.catalog = MapCatalog(MAPS_DIR)
        self.difficulty = ""
        self.map_name = ""

    def run(self) -> None:
        """Run the screens until the user quits."""
        state = GameState.TITLE
        while state != GameState.QUIT:
            if state == GameState.TITLE:
                self.reset_menu_window()
                state = TitleScreen(self).run()
            elif state == GameState.MAP_SELECT:
                state = MapSelectScreen(self).run()
            elif state == GameState.SIMULATION:
                state = self.start_simulation()
        pygame.quit()

    def reset_menu_window(self) -> None:
        """Go back to the menu window size after a simulation."""
        if self.screen.get_size() != MENU_SCREEN_SIZE:
            os.environ['SDL_VIDEO_CENTERED'] = '1'
            self.screen = pygame.display.set_mode(MENU_SCREEN_SIZE)
            pygame.display.set_caption("Fly-in")

    def start_simulation(self) -> GameState:
        """Simulate the chosen map, print its turns, then animate it."""
        try:
            graph = MapParser(str(self.catalog.find(self.map_name))).parse()
            simulation = Simulation(graph)
            lines = simulation.run()
        except (OSError, ParseError, NoPathError, ValueError) as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return GameState.TITLE
        print("\n".join(lines))
        return SimulationScreen(self, simulation, len(lines)).run()
