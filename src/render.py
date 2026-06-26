import sys
from enum import Enum
from pathlib import Path

# from pydantic_models import MapModel, ZoneModel, ConnectionModel

import pygame
import pygame.freetype
from pygame.sprite import Sprite

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
def grid_to_px(x, y, offset, scale) -> tuple[int, int]:
    return (offset[0] + x * scale, offset[1] + y * scale)


def get_screen_size_for_map(map_name: str) -> tuple[int, int]:
    """Return the screen size for a given map name."""
    for difficulty in DIFFICULTIES:
        map_path = MAPS_DIR / difficulty / f"{map_name.replace(' ', '_')}.txt"
        if map_path.exists():
            with open(map_path, "r") as f:
                lines = f.readlines()
                width = len(lines[0].strip())
                height = len(lines)
                return (width * 20, height * 20)  # Scale factor of 20
    raise ValueError(f"Map '{map_name}' not found in any difficulty folder.")


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


def get_hubs_from_map_file(map_file_path: Path) -> list[tuple[int, int]]:
    """Read a map file and return a list of (x, y) coordinates for hubs."""
    hubs = []
    with open(map_file_path, "r") as f:
        for y, line in enumerate(f):
            for x, char in enumerate(line.strip()):
                if char == "Z":  # Assuming 'Z' marks a hub
                    hubs.append((x, y))
    return hubs


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


class MapElement(Sprite):
    """A map element that can be drawn on the screen."""

    def __init__(self, position, size, color):
        self.image = pygame.Surface(size)
        self.image.fill(color)
        self.rect = self.image.get_rect(topleft=position)

    def draw(self, surface):
        surface.blit(self.image, self.rect)


class DroneElement(Sprite):
    """A drone element that can be drawn on the screen."""

    def __init__(self, position, size, color):
        self.image = pygame.Surface(size)
        self.image.fill(color)
        self.rect = self.image.get_rect(center=position)

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
    """Placeholder simulation screen. Press Escape to return to title."""
    screen_size = get_screen_size_for_map(map_name)
    screen = pygame.display.set_mode(screen_size)

    RETURN_POS = (screen_size[0] - 140, screen_size[1] - 30)

    return_btn = UIElement(
        RETURN_POS,
        "Return to main menu",
        20,
        WHITE,
        LIGHT_BLUE,
        action=GameState.TITLE,
    )

    hubs = []
    for difficulty in DIFFICULTIES:
        map_path = MAPS_DIR / difficulty / f"{map_name.replace(' ', '_')}.txt"
        if map_path.exists():
            hubs = get_hubs_from_map_file(map_path)
            for (x, y) in hubs:
                px, py = grid_to_px(x, y, offset=(0, 0), scale=20)
                hubs.append((px + 10, py + 10))  # Center of the cell
            break

    hub_elements = [
        MapElement((px, py), (20, 20), GREEN) for (px, py) in hubs
    ]

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

        action = return_btn.update(pygame.mouse.get_pos(), mouse_up)
        if action is not None:
            return action
        return_btn.draw(screen)

        for hub in hub_elements:
            hub.draw(screen)

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

# # ============ MAP ============== #

# background_color = WHITE
# circle_color = RED

# # Set up the display of the map with dynamic size
# screen = pygame.display.set_mode((800, 600))
# pygame.display.set_caption("Fly-in")

# # Load potato img and scale it down
# potato_img = pygame.image.load('potato.png').convert_alpha()
# potato_img = pygame.transform.scale(
#     potato_img, (potato_img.get_width() * 0.1,
#                  potato_img.get_height() * 0.1))

# # Game loop
# running = True
# x = 0
# clock = pygame.time.Clock()

# delta_time = 0.1

# # Game loop
# while running:

#     screen.fill(background_color)
#     screen.blit(potato_img, (x, 30))

#     x += 100 * delta_time

#     for event in pygame.event.get():
#         if event.type == pygame.QUIT:
#             running = False

#     pygame.display.flip()

#     delta_time = clock.tick(60) / 1000
#     delta_time = max(0.001, min(0.1, delta_time))

#     # pygame.draw.circle(screen, circle_color, (50, 50), 20)
#     pygame.display.update()

# # Quit Pygame
# pygame.quit()
