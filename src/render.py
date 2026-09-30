import math
import os
import sys
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

import pygame
import pygame.freetype
from pygame.sprite import Sprite

from parser import ParseError, parse_map_file
from pathfinding import NoPathError
from pydantic_models import Graph, Zone
from simulation import DeadlockError, Position, Simulation

MAPS_DIR = Path(__file__).parent.parent / "maps"
DRONE_IMAGE = Path(__file__).parent.parent / "potato.png"
DIFFICULTIES = ["easy", "medium", "hard", "challenger"]

WHITE = (255, 255, 255)
BLUE = (0, 0, 255)
RED = (255, 0, 0)
GREEN = (0, 255, 0)
BLACK = (0, 0, 0)
LIGHT_BLUE = (106, 159, 181)
LIGHT_GRAY = (230, 230, 230)
DARK_GRAY = (70, 70, 70)
RESTRICTED_OUTLINE = (190, 0, 0)
PRIORITY_OUTLINE = (230, 170, 0)

MENU_SCREEN_SIZE = (800, 600)

SCALE = 150
MARGIN = 80
HUB_RADIUS = 30
HUD_HEIGHT = 110
MIN_WINDOW_SIZE = (820, 420)
TURNS_PER_SECOND = 1.0


@dataclass
class Layout:
    """How grid coordinates map to the simulation window.

    Attributes:
        size: Window size in pixels (graph area + HUD).
        scale: Pixels per grid unit.
        offset: Pixel position of the grid origin.
        hub_radius: Radius of a zone circle, shrunk on large maps.
    """

    size: tuple[int, int]
    scale: float
    offset: tuple[float, float]
    hub_radius: int

    def to_px(self, zone: Zone) -> tuple[float, float]:
        return grid_to_px(zone.x, zone.y, self.offset, self.scale)


def available_screen_size() -> tuple[int, int]:
    """Desktop size minus some room for the window decorations."""
    try:
        sizes = pygame.display.get_desktop_sizes()
    except pygame.error:
        sizes = []
    width, height = sizes[0] if sizes else (1600, 900)
    return width - 80, height - 120


def compute_layout(zones: list[Zone]) -> Layout:
    """Fit the whole map in the screen, centered, above the HUD.

    Uses SCALE pixels per grid unit, or less if the map would not fit
    (e.g. the 23 units wide challenger map).
    """
    min_x = min(z.x for z in zones)
    max_x = max(z.x for z in zones)
    min_y = min(z.y for z in zones)  # y can be negative
    max_y = max(z.y for z in zones)
    span_x, span_y = max_x - min_x, max_y - min_y

    max_w, max_h = available_screen_size()
    scale = float(SCALE)
    if span_x:
        scale = min(scale, (max_w - 2 * MARGIN) / span_x)
    if span_y:
        scale = min(scale, (max_h - 2 * MARGIN - HUD_HEIGHT) / span_y)

    width = max(int(span_x * scale) + 2 * MARGIN, MIN_WINDOW_SIZE[0])
    height = max(
        int(span_y * scale) + 2 * MARGIN + HUD_HEIGHT, MIN_WINDOW_SIZE[1]
    )
    graph_height = height - HUD_HEIGHT

    # Center the map; y grows upwards in the map files.
    offset_x = (width - span_x * scale) / 2 - min_x * scale
    offset_y = (graph_height - span_y * scale) / 2 + max_y * scale
    hub_radius = int(max(12, min(HUB_RADIUS, scale * 0.22)))
    return Layout((width, height), scale, (offset_x, offset_y), hub_radius)


def grid_to_px(
    x: float, y: float, offset: tuple[float, float], scale: float
) -> tuple[float, float]:
    return (offset[0] + x * scale, offset[1] - y * scale)


def draw_connection(
    screen: pygame.Surface,
    zone_a: Zone,
    zone_b: Zone,
    layout: Layout,
    capacity: int,
) -> None:
    """Draw a line between two zones, thicker for higher capacities."""
    width = min(2 * capacity, 8)
    pygame.draw.line(
        screen, BLACK, layout.to_px(zone_a), layout.to_px(zone_b), width
    )


def draw_hub(
    screen: pygame.Surface,
    zone: Zone,
    layout: Layout,
    font: pygame.freetype.Font,
    occupancy: int,
    unlimited: bool,
) -> None:
    """Draw a zone circle, its type feedback, name and occupancy.

    restricted: thick red ring, priority: thick gold ring,
    blocked: dark disc crossed out.
    """
    pos = layout.to_px(zone)
    radius = layout.hub_radius
    try:
        color = pygame.Color(zone.color or "gray")
    except ValueError:
        color = pygame.Color("gray")
    if zone.is_blocked:
        color = pygame.Color(DARK_GRAY)
    pygame.draw.circle(screen, color, pos, radius)

    if zone.zone_type == "restricted":
        pygame.draw.circle(screen, RESTRICTED_OUTLINE, pos, radius + 3, 5)
    elif zone.zone_type == "priority":
        pygame.draw.circle(screen, PRIORITY_OUTLINE, pos, radius + 3, 5)
    else:
        pygame.draw.circle(screen, BLACK, pos, radius, 1)

    if zone.is_blocked:
        d = radius * 0.6
        pygame.draw.line(
            screen, RED, (pos[0] - d, pos[1] - d), (pos[0] + d, pos[1] + d), 4
        )
        pygame.draw.line(
            screen, RED, (pos[0] - d, pos[1] + d), (pos[0] + d, pos[1] - d), 4
        )

    label_surf, label_rect = font.render(zone.name, BLACK)
    label_rect.centerx = int(pos[0])
    label_rect.top = int(pos[1]) + radius + 5
    screen.blit(label_surf, label_rect)

    if not zone.is_blocked:
        count = str(occupancy)
        if not unlimited:
            count += f"/{zone.max_drones}"
        count_surf, count_rect = font.render(count, BLACK)
        count_rect.centerx = int(pos[0])
        count_rect.bottom = int(pos[1]) - radius - 5
        screen.blit(count_surf, count_rect)


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


def get_maps(difficulty: str) -> list[str]:
    """Return map names for the given difficulty, formatted for display."""
    folder = MAPS_DIR / difficulty
    if not folder.exists():
        return []
    return sorted(p.stem.replace("_", " ") for p in folder.glob("*.txt"))


def create_surface_with_text(text, font_size, text_rgb, bg_rgb):
    """Returns a surface with text written on it."""
    font = pygame.freetype.SysFont("Courier", font_size, bold=True)
    surface, _ = font.render(text=text, fgcolor=text_rgb, bgcolor=bg_rgb)
    return surface.convert_alpha()


# ── UIElement ───────────────────────────────────────────────────────────
class UIElement(Sprite):
    """A clickable UI element that highlights on hover."""

    def __init__(self,
                 center_position,
                 text,
                 font_size,
                 bg_rgb,
                 text_rgb,
                 action=None):
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
        super().__init__()

    @property
    def image(self):
        return self.images[1] if self.mouse_over else self.images[0]

    @property
    def rect(self):
        return self.rects[1] if self.mouse_over else self.rects[0]

    def update(self, mouse_pos, mouse_up):
        if self.rect.collidepoint(mouse_pos):
            self.mouse_over = True
            if mouse_up:
                return self.action
        else:
            self.mouse_over = False

    def draw(self, surface):
        surface.blit(self.image, self.rect)


def title_screen(screen):
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


def map_select_screen(screen, difficulty: str):
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
            if action is not None:
                if action == GameState.TITLE:
                    return GameState.TITLE, None
                return GameState.SIMULATION, action
            btn.draw(screen)

        pygame.display.flip()


def load_drone_image(size: int) -> pygame.Surface:
    """The potato sprite scaled to size x size (a plain disc if missing)."""
    try:
        image = pygame.image.load(DRONE_IMAGE).convert_alpha()
        return pygame.transform.smoothscale(image, (size, size))
    except (pygame.error, FileNotFoundError):
        fallback = pygame.Surface((size, size), pygame.SRCALPHA)
        pygame.draw.circle(
            fallback, (160, 110, 60), (size // 2, size // 2), size // 2
        )
        return fallback


def drone_pixels(
    snapshot: dict[int, Position], graph: Graph, layout: Layout
) -> dict[int, tuple[float, float]]:
    """Pixel position of every drone for one turn snapshot.

    Drones sharing a spot (same zone, or same point on a connection) are
    spread on a small ring around it so they stay visible.
    """
    groups: dict[Position, list[int]] = {}
    for drone_id, position in sorted(snapshot.items()):
        groups.setdefault(position, []).append(drone_id)

    pixels: dict[int, tuple[float, float]] = {}
    for (zone_a, zone_b, fraction), drone_ids in groups.items():
        ax, ay = layout.to_px(graph.zones[zone_a])
        bx, by = layout.to_px(graph.zones[zone_b])
        cx, cy = ax + (bx - ax) * fraction, ay + (by - ay) * fraction
        ring = 0.0 if len(drone_ids) == 1 else layout.hub_radius * 0.6
        for k, drone_id in enumerate(drone_ids):
            angle = 2 * math.pi * k / len(drone_ids) - math.pi / 2
            pixels[drone_id] = (
                cx + ring * math.cos(angle), cy + ring * math.sin(angle)
            )
    return pixels


def zone_occupancy(snapshot: dict[int, Position]) -> dict[str, int]:
    """Drones sitting in each zone (drones on a connection not counted)."""
    counts: dict[str, int] = {}
    for zone_a, _, fraction in snapshot.values():
        if fraction == 0.0:
            counts[zone_a] = counts.get(zone_a, 0) + 1
    return counts


def fit_text(font: pygame.freetype.Font, text: str, max_width: int) -> str:
    """Cut text with '...' so it fits in max_width pixels."""
    if font.get_rect(text).width <= max_width:
        return text
    while text and font.get_rect(text + "...").width > max_width:
        text = text[:-1]
    return text + "..."


def draw_legend(
    screen: pygame.Surface, font: pygame.freetype.Font, pos: tuple[int, int]
) -> None:
    """Zone type legend, matching draw_hub's visual feedback."""
    x, y = pos
    entries = [
        ("restricted (2 turns)", RESTRICTED_OUTLINE, False),
        ("priority", PRIORITY_OUTLINE, False),
        ("blocked", DARK_GRAY, True),
    ]
    for label, color, filled in entries:
        pygame.draw.circle(screen, color, (x + 7, y), 7, 0 if filled else 3)
        label_surf, label_rect = font.render(label, BLACK)
        label_rect.midleft = (x + 20, y)
        screen.blit(label_surf, label_rect)
        x += label_rect.width + 45


def error_screen(screen, map_name: str, message: str):
    """Show why a map could not be simulated. Returns the next GameState."""
    screen = pygame.display.set_mode(MENU_SCREEN_SIZE)
    font = pygame.freetype.SysFont("Arial", 16, bold=True)
    cx = screen.get_width() // 2
    return_btn = UIElement(
        (cx, screen.get_height() - 60),
        "Return to main menu",
        20,
        LIGHT_BLUE,
        WHITE,
        action=GameState.TITLE,
    )
    lines = [f"Cannot simulate '{map_name}':"] + message.splitlines()

    while True:
        mouse_up = False
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                return GameState.QUIT
            if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                return GameState.TITLE
            if event.type == pygame.MOUSEBUTTONUP and event.button == 1:
                mouse_up = True

        screen.fill(LIGHT_BLUE)
        for i, line in enumerate(lines[:20]):
            text = fit_text(font, line, screen.get_width() - 60)
            surf, rect = font.render(text, WHITE)
            rect.topleft = (30, 40 + i * 24)
            screen.blit(surf, rect)

        action = return_btn.update(pygame.mouse.get_pos(), mouse_up)
        if action is not None:
            return action
        return_btn.draw(screen)
        pygame.display.flip()


def simulation_screen(screen, map_name: str):
    """Run the simulation for map_name and animate it turn by turn.

    Controls: SPACE play/pause, LEFT/RIGHT previous/next turn,
    UP/DOWN speed, R restart, ESC back to the menu.
    """
    try:
        graph = parse_map_file(str(find_map_path(map_name)))
        simulation = Simulation(graph)
        simulation.run()
    except (OSError, ParseError, NoPathError, DeadlockError,
            ValueError) as exc:
        return error_screen(screen, map_name, str(exc))

    for moves in simulation.turns:
        print(simulation.format_turn(moves))

    layout = compute_layout(list(graph.zones.values()))
    width, height = layout.size
    os.environ["SDL_VIDEO_CENTERED"] = "1"
    screen = pygame.display.set_mode(layout.size)
    pygame.display.set_caption(f"Fly-in - {map_name}")

    font = pygame.freetype.SysFont("Arial", 12, bold=True)
    hud_font = pygame.freetype.SysFont("Arial", 14, bold=True)
    drone_size = max(18, int(layout.hub_radius * 1.1))
    drone_image = load_drone_image(drone_size)
    frames = [
        drone_pixels(snapshot, graph, layout)
        for snapshot in simulation.snapshots
    ]
    last_turn = len(frames) - 1

    return_btn = UIElement(
        (width - 120, height - 22),
        "Return to menu",
        16,
        WHITE,
        LIGHT_BLUE,
        action=GameState.TITLE,
    )

    turn = 0        # last completed turn shown
    phase = 0.0     # progress of the animation towards turn + 1, in [0, 1)
    paused = False
    speed = 1.0
    clock = pygame.time.Clock()

    while True:
        elapsed = clock.tick(60) / 1000
        mouse_up = False
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                return GameState.QUIT
            if event.type == pygame.MOUSEBUTTONUP and event.button == 1:
                mouse_up = True
            if event.type != pygame.KEYDOWN:
                continue
            if event.key == pygame.K_ESCAPE:
                return GameState.TITLE
            if event.key == pygame.K_SPACE:
                if turn == last_turn:
                    turn = 0
                    paused = False
                else:
                    paused = not paused
            elif event.key == pygame.K_RIGHT:
                turn, phase, paused = min(turn + 1, last_turn), 0.0, True
            elif event.key == pygame.K_LEFT:
                turn, phase, paused = max(turn - 1, 0), 0.0, True
            elif event.key == pygame.K_UP:
                speed = min(speed * 2, 16.0)
            elif event.key == pygame.K_DOWN:
                speed = max(speed / 2, 0.25)
            elif event.key == pygame.K_r:
                turn, phase, paused = 0, 0.0, False

        if not paused and turn < last_turn:
            phase += elapsed * speed * TURNS_PER_SECOND
            while phase >= 1.0 and turn < last_turn:
                phase -= 1.0
                turn += 1
            if turn == last_turn:
                phase = 0.0

        screen.fill(WHITE)

        for connection in graph.connections:
            draw_connection(
                screen,
                graph.zones[connection.zone_a],
                graph.zones[connection.zone_b],
                layout,
                connection.max_link_capacity,
            )

        occupancy = zone_occupancy(simulation.snapshots[turn])
        for zone in graph.zones.values():
            draw_hub(
                screen, zone, layout, font,
                occupancy.get(zone.name, 0),
                zone.name in (graph.start, graph.end),
            )

        # Smoothstep easing between the two snapshots.
        t = phase * phase * (3 - 2 * phase)
        current = frames[turn]
        target = frames[turn + 1] if turn < last_turn else current
        for drone_id, (x0, y0) in current.items():
            x1, y1 = target[drone_id]
            center = (x0 + (x1 - x0) * t, y0 + (y1 - y0) * t)
            screen.blit(drone_image, drone_image.get_rect(center=center))
            if drone_size >= 18:
                id_surf, id_rect = font.render(str(drone_id), BLACK)
                id_rect.center = (int(center[0]), int(center[1]))
                screen.blit(id_surf, id_rect)

        hud_top = height - HUD_HEIGHT
        pygame.draw.rect(screen, LIGHT_GRAY, (0, hud_top, width, HUD_HEIGHT))
        status = f"Turn {turn}/{last_turn}   speed x{speed:g}"
        if paused:
            status += "   PAUSED"
        elif turn == last_turn:
            status += "   DONE"
        shown_turn = turn + 1 if phase > 0 else turn
        moves = (
            f"Turn {shown_turn}: "
            + simulation.format_turn(simulation.turns[shown_turn - 1])
            if shown_turn > 0 else ""
        )
        hud_lines = [
            status,
            fit_text(hud_font, moves, width - 30),
            "[SPACE] play/pause   [LEFT/RIGHT] step   "
            "[UP/DOWN] speed   [R] restart   [ESC] menu",
        ]
        for i, line in enumerate(hud_lines):
            surf, rect = hud_font.render(line, BLACK)
            rect.topleft = (15, hud_top + 10 + i * 22)
            screen.blit(surf, rect)
        draw_legend(screen, font, (15, height - 16))

        action = return_btn.update(pygame.mouse.get_pos(), mouse_up)
        if action is not None:
            return action
        return_btn.draw(screen)

        pygame.display.flip()


def main():
    pygame.init()
    screen = pygame.display.set_mode(MENU_SCREEN_SIZE)
    pygame.display.set_caption("Fly-in")

    game_state = GameState.TITLE
    selected_difficulty = None
    selected_map = None

    while True:
        if game_state == GameState.TITLE:
            if screen.get_size() != MENU_SCREEN_SIZE:
                os.environ['SDL_VIDEO_CENTERED'] = '1'
                screen = pygame.display.set_mode(MENU_SCREEN_SIZE)
            result = title_screen(screen)
            if result == GameState.QUIT:
                break
            selected_difficulty = result
            game_state = GameState.MAP_SELECT

        elif game_state == GameState.MAP_SELECT:
            game_state, selected_map = map_select_screen(
                screen, selected_difficulty)

        elif game_state == GameState.SIMULATION:
            game_state = simulation_screen(screen, selected_map)

        if game_state == GameState.QUIT:
            break

    pygame.quit()
    sys.exit()


if __name__ == "__main__":
    main()
