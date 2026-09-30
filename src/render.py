import sys
from enum import Enum
from pathlib import Path

import pygame
import pygame.freetype

import os

from .parser import ParseError, parse_map_file
from .pathfinding import NoPathError
from .pydantic_models import Zone
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


def compute_scale(zones: list[Zone]) -> int:
    """SCALE, or less so that wide maps fit in MAX_WINDOW_WIDTH."""
    max_x = max(z.x for z in zones)
    return min(SCALE, (MAX_WINDOW_WIDTH - 2 * MARGIN) // max(max_x, 1))


def compute_window_size(zones: list[Zone], scale: int) -> tuple[int, int]:
    max_x = max(z.x for z in zones)
    max_y = max(z.y for z in zones)
    min_y = min(z.y for z in zones)  # y can be negative
    width = (max_x) * scale + 2 * MARGIN
    height = (max_y - min_y + 1) * scale + 2 * MARGIN
    return (width, height)


def compute_offset(zones: list[Zone], scale: int) -> tuple[int, int]:
    max_y = max(z.y for z in zones)
    min_y = min(z.y for z in zones)

    # Centre horizontal : 0 à gauche + marge
    offset_x = MARGIN

    # Centre vertical : y=0 au milieu de la fenêtre
    screen_height = (max_y - min_y + 1) * scale + 2 * MARGIN
    offset_y = screen_height // 2  # y=0 → centre de l'écran

    return (offset_x, offset_y)


def grid_to_px(
    x: float, y: float, offset: tuple[int, int], scale: int
) -> tuple[float, float]:
    return (offset[0] + x * scale, offset[1] - y * scale)


def draw_connection(
    screen: pygame.Surface, zone_a: Zone, zone_b: Zone,
    offset: tuple[int, int], scale: int,
) -> None:
    """Draw a line between two zones."""
    pos_a = grid_to_px(zone_a.x, zone_a.y, offset, scale)
    pos_b = grid_to_px(zone_b.x, zone_b.y, offset, scale)
    pygame.draw.line(screen, BLACK, pos_a, pos_b, 2)


def draw_hub(
    screen: pygame.Surface, zone: Zone, offset: tuple[int, int],
    scale: int, font: pygame.freetype.Font,
) -> None:
    """Draw a zone circle in its map color, with its name below."""
    pos = grid_to_px(zone.x, zone.y, offset, scale)
    radius = HUB_RADIUS * scale // SCALE
    try:
        color = pygame.Color(zone.color or "gray")
    except ValueError:
        color = pygame.Color("gray")
    pygame.draw.circle(screen, color, pos, radius)
    label_surf, label_rect = font.render(zone.name, BLACK)
    label_rect.centerx = int(pos[0])
    label_rect.top = int(pos[1]) + radius + 4
    screen.blit(label_surf, label_rect)


def find_map_path(map_name: str) -> Path:
    """Find the .txt file path for a given display map name."""
    filename = map_name.replace(" ", "_") + ".txt"
    for difficulty in DIFFICULTIES:
        path = MAPS_DIR / difficulty / filename
        if path.exists():
            return path
    raise FileNotFoundError(f"Map '{map_name}' not found.")


class GameState(Enum):
    TITLE = 1
    MAP_SELECT = 2
    SIMULATION = 3
    QUIT = 4


Color = tuple[int, int, int]

# What clicking a UIElement returns: a screen to go to, or a chosen
# difficulty / map name.
Action = GameState | str


def get_maps(difficulty: str) -> list[str]:
    """Return map names for the given difficulty, formatted for display."""
    folder = MAPS_DIR / difficulty
    if not folder.exists():
        return []
    return sorted(p.stem.replace("_", " ") for p in folder.glob("*.txt"))


def create_surface_with_text(
    text: str, font_size: float, text_rgb: Color, bg_rgb: Color
) -> pygame.Surface:
    """Returns a surface with text written on it."""
    font = pygame.freetype.SysFont("Courier", int(font_size), bold=True)
    surface, _ = font.render(text=text, fgcolor=text_rgb, bgcolor=bg_rgb)
    return surface.convert_alpha()


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

        default_image = create_surface_with_text(text=text,
                                                 font_size=font_size,
                                                 text_rgb=text_rgb,
                                                 bg_rgb=bg_rgb)
        highlighted_image = create_surface_with_text(
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


def title_screen(screen: pygame.Surface) -> Action:
    """Difficulty selection. Returns difficulty string or GameState.QUIT."""

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
                                             and event.key == pygame.K_ESCAPE):
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


def map_select_screen(
    screen: pygame.Surface, difficulty: str
) -> tuple[GameState, str | None]:
    """Map selection screen for a given difficulty.
    Returns (GameState.TITLE, None) or (GameState.SIMULATION, map_name)."""
    cx = screen.get_width() // 2
    maps = get_maps(difficulty)

    title = UIElement((cx, 60), difficulty.capitalize(), 40, LIGHT_BLUE, WHITE)

    map_buttons = [
        UIElement((cx, 150 + i * 65), name, 25, LIGHT_BLUE, WHITE, action=name)
        for i, name in enumerate(maps)
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
            if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
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


def step_to_px(
    step: Step, graph_zones: dict[str, Zone],
    offset: tuple[int, int], scale: int,
) -> tuple[float, float]:
    """Pixel position of a drone: its zone, or the middle of the
    connection when it is flying towards a restricted zone."""
    zone_a, zone_b = graph_zones[step[0]], graph_zones[step[1]]
    return grid_to_px((zone_a.x + zone_b.x) / 2, (zone_a.y + zone_b.y) / 2,
                      offset, scale)


def simulation_screen(screen: pygame.Surface, map_name: str) -> GameState:
    """Simulate map_name, print its turns, then animate the drones."""
    try:
        graph = parse_map_file(str(find_map_path(map_name)))
        simulation = Simulation(graph)
        lines = simulation.run()
    except (OSError, ParseError, NoPathError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return GameState.TITLE
    print("\n".join(lines))

    zones = list(graph.zones.values())
    scale = compute_scale(zones)
    w, h = compute_window_size(zones, scale)
    screen = pygame.display.set_mode((w, h))
    pygame.display.set_caption(f"Fly-in - {map_name}")

    offset = compute_offset(zones, scale)
    font = pygame.freetype.SysFont("Arial", 12, bold=True)
    drone_size = HUB_RADIUS * scale // SCALE
    drone_image = pygame.transform.smoothscale(
        pygame.image.load(DRONE_IMAGE).convert_alpha(),
        (drone_size, drone_size),
    )

    return_btn = UIElement(
        (140, h - 40),
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
            if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                return GameState.TITLE
            if event.type == pygame.MOUSEBUTTONUP and event.button == 1:
                mouse_up = True

        screen.fill(WHITE)

        for connection in graph.connections:
            draw_connection(screen, graph.zones[connection.zone_a],
                            graph.zones[connection.zone_b], offset, scale)

        for zone in zones:
            draw_hub(screen, zone, offset, scale, font)

        # One turn per second: drones glide from their position at `turn`
        # to their position at `turn + 1` (fraction = progress in between).
        elapsed = (pygame.time.get_ticks() - start_ticks) / 1000
        progress = min(elapsed * TURNS_PER_SECOND, len(lines))
        turn, fraction = int(progress), progress - int(progress)
        for drone in range(graph.nb_drones):
            x0, y0 = step_to_px(simulation.position(drone, turn),
                                graph.zones, offset, scale)
            x1, y1 = step_to_px(simulation.position(drone, turn + 1),
                                graph.zones, offset, scale)
            # Small shift per drone so drones sharing a zone stay visible.
            x0 += (drone % 3 - 1) * drone_size / 3
            y0 += (drone // 3 % 3 - 1) * drone_size / 3
            x1 += (drone % 3 - 1) * drone_size / 3
            y1 += (drone // 3 % 3 - 1) * drone_size / 3
            center = (x0 + (x1 - x0) * fraction, y0 + (y1 - y0) * fraction)
            screen.blit(drone_image, drone_image.get_rect(center=center))

        action = return_btn.update(pygame.mouse.get_pos(), mouse_up)
        if isinstance(action, GameState):
            return action
        return_btn.draw(screen)

        pygame.display.flip()


def run_gui() -> None:
    """Open the menu window and run the screens until the user quits."""
    pygame.init()
    screen = pygame.display.set_mode(MENU_SCREEN_SIZE)
    pygame.display.set_caption("Fly-in")

    game_state = GameState.TITLE
    selected_difficulty = ""
    selected_map = ""

    while True:
        if game_state == GameState.TITLE:
            if screen.get_size() != MENU_SCREEN_SIZE:
                os.environ['SDL_VIDEO_CENTERED'] = '1'
                screen = pygame.display.set_mode(MENU_SCREEN_SIZE)
            result = title_screen(screen)
            if isinstance(result, GameState):
                break
            selected_difficulty = result
            game_state = GameState.MAP_SELECT

        elif game_state == GameState.MAP_SELECT:
            game_state, map_name = map_select_screen(
                screen, selected_difficulty)
            if map_name is not None:
                selected_map = map_name

        elif game_state == GameState.SIMULATION:
            game_state = simulation_screen(screen, selected_map)

        if game_state == GameState.QUIT:
            break

    pygame.quit()
