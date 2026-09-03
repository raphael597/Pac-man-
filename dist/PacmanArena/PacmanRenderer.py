import sys
import pygame
from Pacman import Direction, Position, Field, Pacman, Wall, Cabbage

CELL_SIZE = 32

LEGEND_WIDTH = 220
LEGEND_MARGIN = 12
LEGEND_ITEM_HEIGHT = 34
LEGEND_SWATCH_SIZE = 20
COLOR_LEGEND_BG = (15, 15, 15)
COLOR_LEGEND_DEAD = (140, 140, 140)   # Textfarbe für tote Pacmans

# Fallback-Farben, falls Icon-Dateien nicht gefunden werden
COLOR_BG = (30, 30, 30)
COLOR_EMPTY = (20, 20, 20)
COLOR_WALL = (90, 90, 90)
COLOR_CABBAGE = (60, 140, 60)
COLOR_TEXT = (255, 255, 255)
COLOR_STATUS_BG = (10, 10, 10)
COLOR_GRID = (50, 50, 50)

# Individuelle Farben pro Pacman-Instanz (Reihenfolge = Erzeugungsreihenfolge)
PACMAN_COLORS = [
    (255, 215, 0),   # Gelb
    (220, 60, 60),   # Rot
    (60, 120, 220),  # Blau
    (200, 100, 220), # Lila
    (100, 220, 200), # Türkis
]

DIRECTION_ANGLES = {
    (1, 0): 0,      # east  -> Standard
    (0, -1): 90,    # north
    (-1, 0): 180,   # west
    (0, 1): 270,    # south
}

class Renderer:
    def __init__(self, field):
        self.field = field
        self.fieldsize = Position.fieldsize
        field_pixel_size = self.fieldsize * CELL_SIZE

        legend_needed_height = (
            2 * LEGEND_MARGIN + len(field.pacmans) * LEGEND_ITEM_HEIGHT
        )
        self.height = max(field_pixel_size, legend_needed_height)
        self.width = field_pixel_size + LEGEND_WIDTH

        self.screen = pygame.display.set_mode((self.width, self.height))
        pygame.display.set_caption("Pacman Simulation")

        self.font = pygame.font.SysFont("consolas", 18)
        self.small_font = pygame.font.SysFont("consolas", 14)

        self.entity_color = {}
        for idx, pac in enumerate(self.field.pacmans):
            self.entity_color[id(pac)] = PACMAN_COLORS[idx % len(PACMAN_COLORS)]

        self.icon_cache = {}
        self.rotated_icon_cache = {}

    def _load_icon(self, path):
        if path in self.icon_cache:
            return self.icon_cache[path]
        surface = None
        try:
            img = pygame.image.load(path)
            img = img.convert_alpha()
            surface = pygame.transform.smoothscale(img, (CELL_SIZE, CELL_SIZE))
        except Exception:
            surface = None
        self.icon_cache[path] = surface
        return surface

    def _get_direction_angle(self, direction):
        key = (direction._x, direction._y)
        return DIRECTION_ANGLES.get(key, 0)

    def _get_icon(self, entry):
        base = self._load_icon(entry.icon)
        if base is None:
            return None

        if isinstance(entry, Pacman):
            angle = self._get_direction_angle(entry.direction)
            if angle == 0:
                return base
            cache_key = (entry.icon, angle)
            if cache_key not in self.rotated_icon_cache:
                self.rotated_icon_cache[cache_key] = pygame.transform.rotate(base, angle)
            return self.rotated_icon_cache[cache_key]

        return base

    def _draw_direction_indicator(self, rect, direction):
        cx, cy = rect.center
        dx, dy = direction._x, direction._y
        size = CELL_SIZE // 2 - 4

        tip = (cx + dx * size, cy + dy * size)
        perp_dx, perp_dy = -dy, dx
        base1 = (
            cx + perp_dx * (size // 2) - dx * (size // 3),
            cy + perp_dy * (size // 2) - dy * (size // 3),
        )
        base2 = (
            cx - perp_dx * (size // 2) - dx * (size // 3),
            cy - perp_dy * (size // 2) - dy * (size // 3),
        )
        pygame.draw.polygon(self.screen, (0, 0, 0), [tip, base1, base2])

    def _draw_fallback_cell(self, rect, entry):
        if isinstance(entry, Pacman):
            color = self.entity_color.get(id(entry), (255, 255, 255))
            pygame.draw.rect(self.screen, COLOR_EMPTY, rect)
            pygame.draw.circle(self.screen, color, rect.center, CELL_SIZE // 2 - 3)
            self._draw_direction_indicator(rect, entry.direction)
        elif isinstance(entry, Wall):
            pygame.draw.rect(self.screen, COLOR_WALL, rect)
        elif isinstance(entry, Cabbage):
            pygame.draw.rect(self.screen, COLOR_EMPTY, rect)
            pygame.draw.circle(self.screen, COLOR_CABBAGE, rect.center, CELL_SIZE // 2 - 6)
        else:
            pygame.draw.rect(self.screen, COLOR_EMPTY, rect)

        pygame.draw.rect(self.screen, COLOR_GRID, rect, 1)

    def _draw_cell(self, rect, entry):
        icon = self._get_icon(entry)
        if icon is not None:
            self.screen.blit(icon, rect.topleft)
            pygame.draw.rect(self.screen, COLOR_GRID, rect, 1)
            if isinstance(entry, Pacman):
                color = self.entity_color.get(id(entry), (255, 255, 255))
                pygame.draw.rect(self.screen, color, rect, 3)
        else:
            self._draw_fallback_cell(rect, entry)

    def draw_field(self):
        self.screen.fill(COLOR_BG)

        for x in range(self.fieldsize):
            for y in range(self.fieldsize):
                pos = Position(x, y)
                entry = self.field.field[pos]
                rect = pygame.Rect(x * CELL_SIZE, y * CELL_SIZE, CELL_SIZE, CELL_SIZE)
                self._draw_cell(rect, entry)

        self._draw_legend()
        pygame.display.flip()

    def _draw_legend(self):
        panel_x = self.fieldsize * CELL_SIZE
        panel_rect = pygame.Rect(panel_x, 0, LEGEND_WIDTH, self.height)
        pygame.draw.rect(self.screen, COLOR_LEGEND_BG, panel_rect)
        pygame.draw.line(
            self.screen, COLOR_GRID, (panel_x, 0), (panel_x, self.height), 2
        )

        title = self.font.render("Legende", True, COLOR_TEXT)
        self.screen.blit(title, (panel_x + LEGEND_MARGIN, LEGEND_MARGIN))

        start_y = LEGEND_MARGIN + LEGEND_ITEM_HEIGHT
        for idx, pac in enumerate(self.field.pacmans):
            item_y = start_y + idx * LEGEND_ITEM_HEIGHT
            self._draw_legend_item(panel_x, item_y, pac)

    def _draw_legend_item(self, panel_x, item_y, pac):
        color = self.entity_color.get(id(pac), (255, 255, 255))
        swatch_rect = pygame.Rect(
            panel_x + LEGEND_MARGIN,
            item_y + (LEGEND_ITEM_HEIGHT - LEGEND_SWATCH_SIZE) // 2,
            LEGEND_SWATCH_SIZE,
            LEGEND_SWATCH_SIZE,
        )

        if pac.alive:
            pygame.draw.rect(self.screen, color, swatch_rect, border_radius=4)
        else:
            pygame.draw.rect(self.screen, color, swatch_rect, width=2, border_radius=4)
            # diagonales Kreuz zeigt "tot" auch ohne Text an
            pygame.draw.line(self.screen, color, swatch_rect.topleft, swatch_rect.bottomright, 2)
            pygame.draw.line(self.screen, color, swatch_rect.bottomleft, swatch_rect.topright, 2)

        text_color = COLOR_TEXT if pac.alive else COLOR_LEGEND_DEAD
        status = "lebt" if pac.alive else "tot"
        label_text = f"{pac.name}: {pac.strength} ({status})"
        label = self.small_font.render(label_text, True, text_color)

        text_x = swatch_rect.right + 8
        text_y = item_y + (LEGEND_ITEM_HEIGHT - label.get_height()) // 2
        self.screen.blit(label, (text_x, text_y))
