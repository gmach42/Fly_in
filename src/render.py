import sys
from enum import Enum
from dataclasses import dataclass
from pathlib import Path

import pygame
import pygame.freetype
from pygame.sprite import Sprite

import os

# ── Paths ───────────────────────────────────────────────────────────────
MAPS_DIR = Path(__file__).parent.parent / "maps"
DIFFICULTIES = ["easy", "medium", "hard", "challenger"]

# ── Colors ───────────────────────────────────────────────────────────────
WHITE = (255, 255, 255)
BLUE = (0, 0, 255)
RED = (255, 0, 0)
GREEN = (0, 255, 0)
BLACK = (0, 0, 0)
LIGHT_BLUE = (106, 159, 181)

MENU_SCREEN_SIZE = (800, 600)

# ── Helpers ──────────────────────────────────────────────────────────────
SCALE = 150
MARGIN = 80
HUB_RADIUS = 30


@dataclass
class Zone:
    name: str
    x: int
    y: int
    zone_type: str = "normal"
    color: str = "gray"
    max_drones: int = 1


def compute_window_size(zones) -> tuple[int, int]:
    max_x = max(z.x for z in zones)
    max_y = max(z.y for z in zones)
    min_y = min(z.y for z in zones)  # y can be negative
    width = (max_x) * SCALE + 2 * MARGIN
    height = (max_y - min_y + 1) * SCALE + 2 * MARGIN
    return (width, height)


def compute_offset(zones) -> tuple[int, int]:
    max_y = max(z.y for z in zones)
    min_y = min(z.y for z in zones)

    # Centre horizontal : 0 à gauche + marge
    offset_x = MARGIN

    # Centre vertical : y=0 au milieu de la fenêtre
    screen_height = (max_y - min_y + 1) * SCALE + 2 * MARGIN
    offset_y = screen_height // 2  # y=0 → centre de l'écran

    return (offset_x, offset_y)


def grid_to_px(x, y, offset, scale) -> tuple[int, int]:
    return (offset[0] + x * scale, offset[1] - y * scale)


def draw_connection(screen, zone_a, zone_b, offset):
    """Draw a line between two zones."""
    pos_a = grid_to_px(zone_a.x, zone_a.y, offset, SCALE)
    pos_b = grid_to_px(zone_b.x, zone_b.y, offset, SCALE)
    pygame.draw.line(screen, BLACK, pos_a, pos_b, 2)


def draw_hub(screen, zone, offset, font):
    """Draw a zone circle with its name centered inside."""
    pos = grid_to_px(zone.x, zone.y, offset, SCALE)
    try:
        color = pygame.Color(zone.color)
    except ValueError:
        color = pygame.Color("gray")
    pygame.draw.circle(screen, color, pos, HUB_RADIUS)
    # pygame.draw.circle(screen, BLACK, pos, HUB_RADIUS, 2)  # outline
    label_surf, label_rect = font.render(zone.name, BLACK)
    # label_rect.center = pos # To center label if needed
    label_rect.centerx = pos[0]
    label_rect.top = pos[1] + HUB_RADIUS + 4
    screen.blit(label_surf, label_rect)


def find_map_path(map_name: str) -> Path:
    """Find the .txt file path for a given display map name."""
    filename = map_name.replace(" ", "_") + ".txt"
    for difficulty in DIFFICULTIES:
        path = MAPS_DIR / difficulty / filename
        if path.exists():
            return path
    raise FileNotFoundError(f"Map '{map_name}' not found.")


def parse_metadata(meta_str: str) -> dict:
    """Parse a '[key=value ...]' metadata string into a dict."""
    return dict(
        part.split("=", 1) for part in meta_str.strip("[] ").split()
        if "=" in part)


def parse_map_file(path: Path, ) -> tuple[list[Zone], list[tuple[str, str]]]:
    """Parse a map file, return (zones, connections)."""
    zones: list[Zone] = []
    connections: list[tuple[str, str]] = []

    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue

            meta: dict = {}
            if "[" in line:
                meta = parse_metadata(line[line.index("["):])
                line = line[:line.index("[")].strip()

            parts = line.split()
            if parts[0] in ("hub:", "start_hub:", "end_hub:"):
                zones.append(
                    Zone(
                        name=parts[1],
                        x=int(parts[2]),
                        y=int(parts[3]),
                        zone_type=meta.get("zone", "normal"),
                        color=meta.get("color", "gray"),
                        max_drones=int(meta.get("max_drones", 1)),
                    ))
            elif parts[0] == "connection:":
                a, b = parts[1].split("-", 1)
                connections.append((a, b))

    return zones, connections


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


def simulation_screen(screen, map_name: str):
    """Map display screen."""
    path = find_map_path(map_name)
    zones, connections = parse_map_file(path)
    zone_by_name = {z.name: z for z in zones}

    w, h = compute_window_size(zones)
    screen = pygame.display.set_mode((w, h))
    pygame.display.set_caption(f"Fly-in - {map_name}")

    offset = compute_offset(zones)
    font = pygame.freetype.SysFont("Arial", 12, bold=True)

    return_btn = UIElement(
        (140, h - 40),
        "Return to main menu",
        20,
        WHITE,
        LIGHT_BLUE,
        action=GameState.TITLE,
    )

    while True:
        mouse_up = False
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                return GameState.QUIT
            if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                return GameState.TITLE
            if event.type == pygame.MOUSEBUTTONUP and event.button == 1:
                mouse_up = True

        screen.fill(WHITE)

        for a, b in connections:
            if a in zone_by_name and b in zone_by_name:
                draw_connection(screen, zone_by_name[a], zone_by_name[b],
                                offset)

        for zone in zones:
            draw_hub(screen, zone, offset, font)

        action = return_btn.update(pygame.mouse.get_pos(), mouse_up)
        if action is not None:
            return action
        return_btn.draw(screen)

        pygame.display.flip()


# ── Main ────────────────────────────────────────────────────────────────
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
