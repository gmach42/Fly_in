"""Pygame interface: menus and drone animation."""

import os
import sys
from enum import Enum
from pathlib import Path

import pygame
import pygame.freetype

from .parser import MapParser, ParseError
from .pathfinding import NoPathError
from .pydantic_models import Zone
from .simulation import Simulation, Step

MAPS_DIR = Path(__file__).parent.parent / "maps"
DRONE_IMAGE = Path(__file__).parent.parent / "potato.png"
DIFFICULTIES = ["easy", "medium", "hard", "challenger"]

# colors
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
DRONE_SIZE_RATIO = 2.5
BOTTOM_MARGIN = 120
MIN_WINDOW_WIDTH = 400
SCREEN_RATIO = 1
LABEL_GAP = 8
TURNS_PER_SECOND = 1.0
END_DELAY = 2.0

Scale = tuple[float, float]


class MapDrawer:
    """Computes the map layout and draws hubs and connections."""

    @staticmethod
    def compute_scale(zones: list[Zone]) -> Scale:
        """Pixels per grid unit on each axis, shrunk to fit the screen."""
        desktop_w, desktop_h = pygame.display.get_desktop_sizes()[0]
        span_x = max(z.x for z in zones) - min(z.x for z in zones)
        span_y = max(z.y for z in zones) - min(z.y for z in zones)
        avail_w = desktop_w * SCREEN_RATIO - 2 * MARGIN
        avail_h = desktop_h * SCREEN_RATIO - MARGIN - BOTTOM_MARGIN
        return (min(SCALE, avail_w / max(span_x, 1)),
                min(SCALE, avail_h / max(span_y, 1)))

    @staticmethod
    def compute_window_size(zones: list[Zone],
                            scale: Scale) -> tuple[int, int]:
        """Window size needed to show the whole map."""
        span_x = max(z.x for z in zones) - min(z.x for z in zones)
        span_y = max(z.y for z in zones) - min(z.y for z in zones)
        width = max(int(span_x * scale[0]) + 2 * MARGIN, MIN_WINDOW_WIDTH)
        height = int(span_y * scale[1]) + MARGIN + BOTTOM_MARGIN
        return (width, height)

    @staticmethod
    def compute_offset(zones: list[Zone], scale: Scale,
                       width: int) -> tuple[float, float]:
        """Pixel position of the grid origin, map centered horizontally."""
        min_x = min(z.x for z in zones)
        span_x = max(z.x for z in zones) - min_x
        max_y = max(z.y for z in zones)
        return ((width - span_x * scale[0]) / 2 - min_x * scale[0],
                MARGIN + max_y * scale[1])

    @staticmethod
    def grid_to_px(x: float, y: float, offset: tuple[float, float],
                   scale: Scale) -> tuple[float, float]:
        """Pixel position of a grid point."""
        return (offset[0] + x * scale[0], offset[1] - y * scale[1])

    @staticmethod
    def hub_radius(scale: Scale) -> int:
        """Hub radius in pixels, smaller on dense maps."""
        return max(4, int(HUB_RADIUS * min(scale) / SCALE))

    @staticmethod
    def needs_stagger(zones: list[Zone], scale: Scale,
                      font: pygame.freetype.Font) -> bool:
        """Whether labels are wider than the space between two hubs."""
        widest = max(font.get_rect(z.name).width for z in zones)
        return widest + LABEL_GAP > scale[0]

    @staticmethod
    def draw_connection(
        screen: pygame.Surface,
        zone_a: Zone,
        zone_b: Zone,
        offset: tuple[float, float],
        scale: Scale,
    ) -> None:
        """Draw a line between two zones."""
        pos_a = MapDrawer.grid_to_px(zone_a.x, zone_a.y, offset, scale)
        pos_b = MapDrawer.grid_to_px(zone_b.x, zone_b.y, offset, scale)
        pygame.draw.line(screen, BLACK, pos_a, pos_b, 2)

    @staticmethod
    def draw_hub(
        screen: pygame.Surface,
        zone: Zone,
        offset: tuple[float, float],
        scale: Scale,
        font: pygame.freetype.Font,
        stagger: bool,
    ) -> None:
        """Draw a zone circle in its map color, with its name below/above."""
        pos = MapDrawer.grid_to_px(zone.x, zone.y, offset, scale)
        radius = MapDrawer.hub_radius(scale)
        try:
            color = pygame.Color(zone.color or "gray")
        except ValueError:
            color = pygame.Color("gray")
        pygame.draw.circle(screen, color, pos, radius)
        label_surf, label_rect = font.render(zone.name, BLACK)
        label_rect.centerx = int(pos[0])
        if stagger and zone.x % 2:
            label_rect.bottom = int(pos[1]) - radius - 4
        else:
            label_rect.top = int(pos[1]) + radius + 4
        screen.blit(label_surf, label_rect)

    @staticmethod
    def step_to_px(
        step: Step,
        graph_zones: dict[str, Zone],
        offset: tuple[float, float],
        scale: Scale,
    ) -> tuple[float, float]:
        """Pixel position of a drone, mid-connection when in flight."""
        zone_a, zone_b = graph_zones[step[0]], graph_zones[step[1]]
        return MapDrawer.grid_to_px((zone_a.x + zone_b.x) / 2,
                                    (zone_a.y + zone_b.y) / 2, offset, scale)


class MapFiles:
    """Finds and lists the map files."""

    @staticmethod
    def find_map_path(map_name: str) -> Path:
        """Find the .txt file path for a given display map name."""
        filename = map_name.replace(" ", "_") + ".txt"
        for difficulty in DIFFICULTIES:
            path = MAPS_DIR / difficulty / filename
            if path.exists():
                return path
        raise FileNotFoundError(f"Map '{map_name}' not found.")

    @staticmethod
    def get_maps(difficulty: str) -> list[str]:
        """Return map names for the given difficulty, formatted for display."""
        folder = MAPS_DIR / difficulty
        try:
            return sorted(
                p.stem.replace("_", " ") for p in folder.glob("*.txt"))
        except OSError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return []

    @staticmethod
    def invalid_maps() -> list[str]:
        """Parse every map file; return one error message per invalid map."""
        errors: list[str] = []
        for difficulty in DIFFICULTIES:
            try:
                paths = sorted((MAPS_DIR / difficulty).glob("*.txt"))
            except OSError as exc:
                errors.append(str(exc))
                continue
            for path in paths:
                try:
                    MapParser.parse_map_file(str(path))
                except (OSError, ParseError, UnicodeDecodeError,
                        ValueError) as exc:
                    errors.append(f"{path.relative_to(MAPS_DIR)}: {exc}")
        return errors


class GameState(Enum):
    """Screen the interface is currently showing."""

    TITLE = 1
    MAP_SELECT = 2
    SIMULATION = 3
    QUIT = 4


Color = tuple[int, int, int]

Action = GameState | str


class UIElement:
    """A clickable UI element that highlights on hover."""

    @staticmethod
    def create_surface_with_text(text: str, font_size: float, text_rgb: Color,
                                 bg_rgb: Color) -> pygame.Surface:
        """Return a surface with text written on it."""
        font = pygame.freetype.SysFont("Courier", int(font_size), bold=True)
        surface, _ = font.render(text=text, fgcolor=text_rgb, bgcolor=bg_rgb)
        return surface.convert_alpha()

    def __init__(self,
                 center_position: tuple[int, int],
                 text: str,
                 font_size: float,
                 bg_rgb: Color,
                 text_rgb: Color,
                 action: Action | None = None) -> None:
        """Render the normal and highlighted versions of the text."""
        self.mouse_over = False
        self.action = action

        default_image = UIElement.create_surface_with_text(
            text=text,
            font_size=font_size,
            text_rgb=text_rgb,
            bg_rgb=bg_rgb,
        )
        highlighted_image = UIElement.create_surface_with_text(
            text=text,
            font_size=font_size * 1.2,
            text_rgb=text_rgb,
            bg_rgb=bg_rgb,
        )

        self.images = [default_image, highlighted_image]
        self.rects = [
            default_image.get_rect(center=center_position),
            highlighted_image.get_rect(center=center_position),
        ]

    @property
    def image(self) -> pygame.Surface:
        """Image to draw, bigger when hovered."""
        return self.images[1] if self.mouse_over else self.images[0]

    @property
    def rect(self) -> pygame.Rect:
        """Rect of the current image."""
        return self.rects[1] if self.mouse_over else self.rects[0]

    def update(self, mouse_pos: tuple[int, int],
               mouse_up: bool) -> Action | None:
        """Update hover state; return the action when clicked."""
        if self.rect.collidepoint(mouse_pos):
            self.mouse_over = True
            if mouse_up:
                return self.action
        else:
            self.mouse_over = False
        return None

    def draw(self, surface: pygame.Surface) -> None:
        """Draw the element on surface."""
        surface.blit(self.image, self.rect)


class Gui:
    """Runs the menu, map selection and simulation screens."""

    @staticmethod
    def title_screen(screen: pygame.Surface) -> Action:
        """Difficulty selection; return a difficulty or GameState.QUIT."""
        cx = screen.get_width() // 2

        title = UIElement((cx, 100), "Fly-in", 50, LIGHT_BLUE, WHITE)

        diff_buttons = [
            UIElement(
                (cx, 220 + i * 70),
                diff.capitalize(),
                30,
                LIGHT_BLUE,
                WHITE,
                action=diff,
            ) for i, diff in enumerate(DIFFICULTIES)
        ]
        quit_btn = UIElement(
            (cx, 220 + len(DIFFICULTIES) * 70),
            "Quit",
            30,
            LIGHT_BLUE,
            WHITE,
            action=GameState.QUIT,
        )

        buttons = diff_buttons + [quit_btn]

        while True:
            mouse_up = False
            for event in pygame.event.get():
                if event.type == pygame.QUIT or (event.type == pygame.KEYDOWN
                                                 and event.key
                                                 == pygame.K_ESCAPE):
                    return GameState.QUIT
                if event.type == pygame.MOUSEBUTTONUP and event.button == 1:
                    mouse_up = True

            screen.fill(LIGHT_BLUE)
            title.draw(screen)
            for btn in buttons:
                action = btn.update(pygame.mouse.get_pos(), mouse_up)
                if action is not None:
                    return action
                btn.draw(screen)

            pygame.display.flip()

    @staticmethod
    def map_select_screen(screen: pygame.Surface,
                          difficulty: str) -> tuple[GameState, str | None]:
        """Map selection screen; return the next state and chosen map."""
        cx = screen.get_width() // 2
        maps = MapFiles.get_maps(difficulty)

        title = UIElement((cx, 60), difficulty.capitalize(), 40, LIGHT_BLUE,
                          WHITE)

        map_buttons = [
            UIElement((cx, 150 + i * 65),
                      name,
                      25,
                      LIGHT_BLUE,
                      WHITE,
                      action=name) for i, name in enumerate(maps)
        ]
        return_btn = UIElement(
            (cx, 150 + len(maps) * 65 + 40),
            "Return",
            25,
            LIGHT_BLUE,
            WHITE,
            action=GameState.TITLE,
        )

        buttons = map_buttons + [return_btn]

        while True:
            mouse_up = False
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    return GameState.QUIT, None
                if event.type == pygame.MOUSEBUTTONUP and event.button == 1:
                    mouse_up = True
                if (event.type == pygame.KEYDOWN
                        and event.key == pygame.K_ESCAPE):
                    return GameState.TITLE, None

            screen.fill(LIGHT_BLUE)
            title.draw(screen)
            for btn in buttons:
                action = btn.update(pygame.mouse.get_pos(), mouse_up)
                if isinstance(action, GameState):
                    return action, None
                if action is not None:
                    return GameState.SIMULATION, action
                btn.draw(screen)

            pygame.display.flip()

    @staticmethod
    def simulation_screen(screen: pygame.Surface, map_name: str) -> GameState:
        """Simulate map_name, print its turns, then animate the drones."""
        try:
            graph = MapParser.parse_map_file(
                str(MapFiles.find_map_path(map_name)))
            simulation = Simulation(graph)
            lines = simulation.run()
        except (OSError, ParseError, NoPathError, ValueError) as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return GameState.QUIT

        print("\n".join(lines))

        zones = list(graph.zones.values())
        scale = MapDrawer.compute_scale(zones)
        w, h = MapDrawer.compute_window_size(zones, scale)
        screen = pygame.display.set_mode((w, h))
        pygame.display.set_caption(f"Fly-in - {map_name}")

        offset = MapDrawer.compute_offset(zones, scale, w)
        font = pygame.freetype.SysFont("Courier", 12, bold=True)
        # A stagger is used to avoid overlapping labels
        stagger = MapDrawer.needs_stagger(zones, scale, font)
        drone_size = int(MapDrawer.hub_radius(scale) * DRONE_SIZE_RATIO)
        drone_image = pygame.transform.smoothscale(
            pygame.image.load(DRONE_IMAGE).convert_alpha(),
            (drone_size, drone_size),
        )
        drone_font = pygame.freetype.SysFont("Arial",
                                             max(8, drone_size // 2),
                                             bold=True)
        drone_labels = [
            drone_font.render(str(drone + 1), RED)[0]
            for drone in range(graph.nb_drones)
        ]

        return_btn = UIElement(
            (140, h - 30),
            "Return to main menu",
            20,
            WHITE,
            LIGHT_BLUE,
            action=GameState.TITLE,
        )

        clock = pygame.time.Clock()
        start_ticks = pygame.time.get_ticks()
        while True:
            clock.tick(60)
            mouse_up = False
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    return GameState.QUIT
                if (event.type == pygame.KEYDOWN
                        and event.key == pygame.K_ESCAPE):
                    return GameState.TITLE
                if event.type == pygame.MOUSEBUTTONUP and event.button == 1:
                    mouse_up = True

            screen.fill(WHITE)

            for connection in graph.connections:
                MapDrawer.draw_connection(screen,
                                          graph.zones[connection.zone_a],
                                          graph.zones[connection.zone_b],
                                          offset, scale)

            for zone in zones:
                MapDrawer.draw_hub(screen, zone, offset, scale, font,
                                   stagger)

            elapsed = (pygame.time.get_ticks() - start_ticks) / 1000
            progress = min(elapsed * TURNS_PER_SECOND, len(lines))
            turn, fraction = int(progress), progress - int(progress)
            for drone in range(graph.nb_drones):
                x0, y0 = MapDrawer.step_to_px(simulation.position(drone, turn),
                                              graph.zones, offset, scale)
                x1, y1 = MapDrawer.step_to_px(
                    simulation.position(drone, turn + 1), graph.zones, offset,
                    scale)
                center = (x0 + (x1 - x0) * fraction, y0 + (y1 - y0) * fraction)
                screen.blit(drone_image, drone_image.get_rect(center=center))
                label = drone_labels[drone]
                screen.blit(label, label.get_rect(center=center))

            action = return_btn.update(pygame.mouse.get_pos(), mouse_up)
            if isinstance(action, GameState):
                return action
            return_btn.draw(screen)

            pygame.display.flip()

            if elapsed >= len(lines) / TURNS_PER_SECOND + END_DELAY:
                return GameState.TITLE

    @staticmethod
    def run_gui() -> None:
        """Open the menu window and run the screens until the user quits."""
        errors = MapFiles.invalid_maps()
        if errors:
            for error in errors:
                print(f"Error: {error}", file=sys.stderr)
            sys.exit(1)

        os.environ['SDL_VIDEO_CENTERED'] = '1'
        pygame.init()
        screen = pygame.display.set_mode(MENU_SCREEN_SIZE)
        pygame.display.set_caption("Fly-in")

        game_state = GameState.TITLE
        selected_difficulty = ""
        selected_map = ""

        while True:
            if game_state == GameState.TITLE:
                if screen.get_size() != MENU_SCREEN_SIZE:
                    screen = pygame.display.set_mode(MENU_SCREEN_SIZE)
                result = Gui.title_screen(screen)
                if isinstance(result, GameState):
                    break
                selected_difficulty = result
                game_state = GameState.MAP_SELECT

            elif game_state == GameState.MAP_SELECT:
                game_state, map_name = Gui.map_select_screen(
                    screen, selected_difficulty)
                if map_name is not None:
                    selected_map = map_name

            elif game_state == GameState.SIMULATION:
                game_state = Gui.simulation_screen(screen, selected_map)

            if game_state == GameState.QUIT:
                break

        pygame.quit()
