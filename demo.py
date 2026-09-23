"""
NOKIA SNAKE GAME - Enhanced Edition
===================================
Setup:
    pip install pygame

Run:
    python demo.py

Bonus (+5 gold food) spawns on its own random timer every 5-15 seconds
instead of immediately after eating food. It still lasts 5 seconds on screen.

Controls:
    Arrow Keys / WASD  - Move snake
    SPACE              - Start / resume
    P                  - Pause / resume
    M                  - Toggle sound
    G                  - Toggle grid
    1 / 2 / 3          - Easy / Normal / Hard (on menu)
    R                  - Restart (game over)
    Q                  - Quit (game over)
    ESC                - Quit anytime
"""

from __future__ import annotations

import array
import math
import os
import random
import sys
from typing import Dict, List, Optional, Tuple

import pygame

# ----------------------------------------------------------------------------
# Settings / Constants
# ----------------------------------------------------------------------------
WIDTH: int = 800
HEIGHT: int = 600
CELL: int = 20
HUD_HEIGHT: int = 44
COLS: int = WIDTH // CELL                    # 40
ROWS: int = (HEIGHT - HUD_HEIGHT) // CELL    # 28

SPEEDUP_EVERY: int = 5
LEVEL_EVERY: int = 10  # maze obstacles every N food items
MAX_LEVEL: int = 5
SLOW_DURATION_MS: int = 4000
BONUS_DURATION_MS: int = 5000
BONUS_SPAWN_MIN_MS: int = 5000   # bonus spawns at a random time every 5-15s
BONUS_SPAWN_MAX_MS: int = 15000
POPUP_LIFETIME: int = 45
SHAKE_FRAMES: int = 18

SCRIPT_DIR: str = os.path.dirname(os.path.abspath(__file__))
SCORES_FILE: str = os.path.join(SCRIPT_DIR, "snake_scores.txt")

DIFFICULTIES: Dict[str, Dict[str, int]] = {
    "EASY": {"base": 10, "max": 18, "inc": 1},
    "NORMAL": {"base": 15, "max": 30, "inc": 2},
    "HARD": {"base": 20, "max": 42, "inc": 3},
}

# Colors - dark neon / retro scheme
COLOR_BG = (10, 12, 24)
COLOR_GRID = (20, 26, 44)
COLOR_HUD_BG = (8, 36, 44)
COLOR_NEON = (0, 255, 170)
COLOR_SNAKE = (0, 230, 110)
COLOR_SNAKE_HEAD = (150, 255, 190)
COLOR_SNAKE_GLOW = (0, 180, 90)
COLOR_WALL = (70, 80, 120)
COLOR_WALL_EDGE = (130, 140, 200)
COLOR_FOOD = (255, 60, 80)
COLOR_FOOD_GLOW = (255, 150, 160)
COLOR_BONUS = (255, 210, 60)
COLOR_BONUS_GLOW = (255, 240, 160)
COLOR_SLOW = (80, 200, 255)
COLOR_SLOW_GLOW = (160, 230, 255)
COLOR_SHRINK = (200, 100, 255)
COLOR_SHRINK_GLOW = (230, 180, 255)
COLOR_TEXT = (0, 255, 200)
COLOR_TEXT_DIM = (110, 150, 150)
COLOR_WHITE = (240, 240, 240)
COLOR_BLACK = (0, 0, 0)
COLOR_ACCENT = (255, 80, 120)

FOOD_COLORS = {
    "NORMAL": (COLOR_FOOD, COLOR_FOOD_GLOW, 1, False),
    "BONUS": (COLOR_BONUS, COLOR_BONUS_GLOW, 5, False),
    "SLOW": (COLOR_SLOW, COLOR_SLOW_GLOW, 1, False),
    "SHRINK": (COLOR_SHRINK, COLOR_SHRINK_GLOW, 1, True),
}

DIRECTION_VECTORS: Dict[str, Tuple[int, int]] = {
    "UP": (0, -1),
    "DOWN": (0, 1),
    "LEFT": (-1, 0),
    "RIGHT": (1, 0),
}
OPPOSITES: Dict[str, str] = {
    "UP": "DOWN",
    "DOWN": "UP",
    "LEFT": "RIGHT",
    "RIGHT": "LEFT",
}

KEY_BINDINGS: Dict[int, str] = {
    pygame.K_UP: "UP",
    pygame.K_w: "UP",
    pygame.K_DOWN: "DOWN",
    pygame.K_s: "DOWN",
    pygame.K_LEFT: "LEFT",
    pygame.K_a: "LEFT",
    pygame.K_RIGHT: "RIGHT",
    pygame.K_d: "RIGHT",
}

GridPos = Tuple[int, int]
PixelPos = Tuple[float, float]


# ----------------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------------
def grid_to_pixel(col: int, row: int) -> Tuple[int, int]:
    return col * CELL, HUD_HEIGHT + row * CELL


def lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def make_font(size: int, bold: bool = False) -> pygame.font.Font:
    path = pygame.font.match_font("consolas,couriernew,arial")
    if path:
        font = pygame.font.Font(path, size)
        font.set_bold(bold)
        return font
    return pygame.font.SysFont("consolas,arial", size, bold=bold)


def load_scores(path: str = SCORES_FILE) -> List[int]:
    try:
        with open(path, "r", encoding="utf-8") as fh:
            values = [int(line.strip()) for line in fh if line.strip()]
        return sorted(values, reverse=True)[:5]
    except (OSError, ValueError):
        return []


def save_score(score: int, path: str = SCORES_FILE) -> List[int]:
    scores = load_scores(path)
    scores.append(score)
    scores = sorted(scores, reverse=True)[:5]
    try:
        with open(path, "w", encoding="utf-8") as fh:
            for value in scores:
                fh.write(f"{value}\n")
    except OSError:
        pass
    return scores


def generate_beep(
    freq: float = 440.0,
    duration: float = 0.08,
    volume: float = 0.25,
    square: bool = True,
) -> pygame.mixer.Sound:
    """Create a small beep sound without numpy."""
    sample_rate = 22050
    count = max(1, int(sample_rate * duration))
    buffer = array.array("h")
    for i in range(count):
        t = i / sample_rate
        if square:
            sample = 1.0 if math.sin(2.0 * math.pi * freq * t) >= 0 else -1.0
        else:
            sample = math.sin(2.0 * math.pi * freq * t)
        fade_in = min(1.0, i / 150.0)
        fade_out = min(1.0, (count - i) / 400.0)
        envelope = max(0.0, min(fade_in, fade_out))
        buffer.append(int(sample * envelope * volume * 32767))
    return pygame.mixer.Sound(buffer=buffer.tobytes())


class Audio:
    """Sound manager with graceful fallback if the mixer is unavailable."""

    def __init__(self, enabled: bool = True) -> None:
        self.enabled = enabled
        self.available = False
        self.sounds: Dict[str, pygame.mixer.Sound] = {}
        try:
            pygame.mixer.init(frequency=22050, size=-16, channels=1, buffer=512)
            self.available = True
            self.sounds = {
                "eat": generate_beep(660, 0.07, 0.22, square=False),
                "bonus": generate_beep(990, 0.12, 0.25, square=False),
                "crash": generate_beep(90, 0.30, 0.30, square=True),
                "ui": generate_beep(440, 0.05, 0.18, square=False),
                "level": generate_beep(880, 0.15, 0.20, square=False),
            }
        except pygame.error:
            self.available = False

    def play(self, name: str) -> None:
        if self.enabled and self.available and name in self.sounds:
            try:
                self.sounds[name].play()
            except pygame.error:
                pass

    def toggle(self) -> bool:
        self.enabled = not self.enabled
        return self.enabled


# ----------------------------------------------------------------------------
# Maze / Level obstacles
# ----------------------------------------------------------------------------
def build_obstacles(level: int) -> List[GridPos]:
    """Return obstacle cells for the current level (1-based)."""
    if level <= 1:
        return []
    cells: List[GridPos] = []

    def add_pillar(cx: int, cy: int, w: int = 3, h: int = 3) -> None:
        for x in range(cx, cx + w):
            for y in range(cy, cy + h):
                if 1 <= x < COLS - 1 and 2 <= y < ROWS - 2:
                    cells.append((x, y))

    def add_line_horizontal(y: int, x0: int, x1: int) -> None:
        for x in range(x0, x1 + 1):
            if 1 <= x < COLS - 1 and 2 <= y < ROWS - 2:
                cells.append((x, y))

    # Level 2: four small pillars
    if level >= 2:
        add_pillar(8, 8)
        add_pillar(COLS - 11, 8)
        add_pillar(8, ROWS - 11)
        add_pillar(COLS - 11, ROWS - 11)

    # Level 3: center cross gap walls
    if level >= 3:
        add_line_horizontal(ROWS // 2, COLS // 2 - 7, COLS // 2 - 3)
        add_line_horizontal(ROWS // 2, COLS // 2 + 3, COLS // 2 + 7)
        for y in range(2, 8):
            cells.append((COLS // 2, y + ROWS // 2 - 4))
            cells.append((COLS // 2 - 1, y + ROWS // 2 - 4))
            cells.append((COLS // 2, ROWS - 1 - y))
            cells.append((COLS // 2 - 1, ROWS - 1 - y))

    # Level 4+: corner blocks
    if level >= 4:
        add_pillar(16, 6, 8, 2)
        add_pillar(16, ROWS - 8, 8, 2)

    # Level 5: fortress walls near spawn lane
    if level >= 5:
        add_line_horizontal(ROWS // 2 - 6, 4, 14)
        add_line_horizontal(ROWS // 2 - 6, COLS - 15, COLS - 5)
        add_line_horizontal(ROWS // 2 + 5, 4, 14)
        add_line_horizontal(ROWS // 2 + 5, COLS - 15, COLS - 5)

    # Deduplicate while keeping order
    seen = set()
    unique: List[GridPos] = []
    for pos in cells:
        if pos not in seen:
            seen.add(pos)
            unique.append(pos)
    # Keep spawn corridor clear (middle row, middle band)
    safe = {
        (c, r)
        for c in range(COLS // 2 - 4, COLS // 2 + 5)
        for r in range(ROWS // 2 - 3, ROWS // 2 + 4)
    }
    return [pos for pos in unique if pos not in safe]


# ----------------------------------------------------------------------------
# Snake (with smooth rendering)
# ----------------------------------------------------------------------------
class Snake:
    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        start_col = COLS // 2
        start_row = ROWS // 2
        self.segments: List[GridPos] = [
            (start_col, start_row),
            (start_col - 1, start_row),
            (start_col - 2, start_row),
        ]
        self.prev_segments: List[GridPos] = list(self.segments)
        self.direction: str = "RIGHT"
        self.next_direction: str = "RIGHT"
        self.grow_pending: bool = False

    @property
    def head(self) -> GridPos:
        return self.segments[0]

    def change_direction(self, new_direction: str) -> None:
        if new_direction == self.direction:
            return
        if new_direction == OPPOSITES[self.direction]:
            return
        self.next_direction = new_direction

    def grow(self) -> None:
        self.grow_pending = True

    def shrink(self) -> bool:
        """Remove the tail segment (SHRINK food). Won't shrink below length 2."""
        if len(self.segments) <= 2:
            return False
        self.segments.pop()
        self.prev_segments = list(self.segments)
        return True

    def update(self) -> None:
        self.prev_segments = list(self.segments)
        self.direction = self.next_direction
        dx, dy = DIRECTION_VECTORS[self.direction]
        hx, hy = self.head
        self.segments.insert(0, (hx + dx, hy + dy))
        if self.grow_pending:
            self.grow_pending = False
        else:
            self.segments.pop()

    def hits_wall(self) -> bool:
        x, y = self.head
        return x < 0 or x >= COLS or y < 0 or y >= ROWS

    def hits_self(self, obstacles: List[GridPos]) -> bool:
        hx, hy = self.head
        if (hx, hy) in obstacles:
            return True
        return self.head in self.segments[1:]

    def interpolated_segments(self, alpha: float) -> List[PixelPos]:
        """Pixel centers for each segment, lerped between grid steps."""
        points: List[PixelPos] = []
        for i, (cx, cy) in enumerate(self.segments):
            if i < len(self.prev_segments):
                pcx, pcy = self.prev_segments[i]
                px = lerp(pcx * CELL + CELL // 2, cx * CELL + CELL // 2, alpha)
                py = lerp(pcy * CELL + CELL // 2, cy * CELL + CELL // 2, alpha)
            else:
                # Newly grown tail: sit on its cell
                px = cx * CELL + CELL // 2
                py = cy * CELL + CELL // 2
            points.append((px, HUD_HEIGHT + py))
        return points

    def _draw_eyes(self, surface: pygame.Surface, rect: pygame.Rect) -> None:
        cx, cy = rect.centerx, rect.centery
        if self.direction == "RIGHT":
            eyes = [(cx + 4, cy - 4), (cx + 4, cy + 4)]
        elif self.direction == "LEFT":
            eyes = [(cx - 4, cy - 4), (cx - 4, cy + 4)]
        elif self.direction == "UP":
            eyes = [(cx - 4, cy - 4), (cx + 4, cy - 4)]
        else:
            eyes = [(cx - 4, cy + 4), (cx + 4, cy + 4)]
        for ex, ey in eyes:
            pygame.draw.circle(surface, COLOR_BLACK, (ex, ey), 3)
            pygame.draw.circle(surface, COLOR_WHITE, (ex, ey), 1)


# ----------------------------------------------------------------------------
# Food
# ----------------------------------------------------------------------------
class Food:
    def __init__(
        self,
        position: GridPos,
        kind: str = "NORMAL",
        timed: bool = False,
        lifetime_ms: int = BONUS_DURATION_MS,
    ) -> None:
        self.position: GridPos = position
        self.kind: str = kind
        self.timed: bool = timed
        self.lifetime_ms: int = lifetime_ms
        self.age_ms: int = 0
        self.pulse: int = random.randint(0, 59)
        self.color: Tuple[int, int, int]
        self.glow: Tuple[int, int, int]
        self.value: int
        self.shrink: bool
        self.color, self.glow, self.value, self.shrink = FOOD_COLORS[kind]

    @property
    def expired(self) -> bool:
        return self.timed and self.age_ms >= self.lifetime_ms

    @property
    def remaining_ratio(self) -> float:
        if not self.timed:
            return 1.0
        return max(0.0, 1.0 - self.age_ms / self.lifetime_ms)

    def update(self, dt_ms: int) -> None:
        self.pulse = (self.pulse + max(1, dt_ms // 16)) % 60
        if self.timed:
            self.age_ms += dt_ms

    # Visual drawing is handled by Game._draw_food_local (field-local coords).

    @staticmethod
    def _draw_star(
        surface: pygame.Surface,
        center: Tuple[int, int],
        points: int,
        radius: int,
        color: Tuple[int, int, int],
    ) -> None:
        coords = []
        for i in range(points * 2):
            angle = -math.pi / 2 + i * math.pi / points
            r = radius if i % 2 == 0 else radius // 2
            coords.append(
                (center[0] + r * math.cos(angle), center[1] + r * math.sin(angle))
            )
        pygame.draw.polygon(surface, color, coords)


# ----------------------------------------------------------------------------
# Particles / Popups
# ----------------------------------------------------------------------------
class Particle:
    __slots__ = ("x", "y", "vx", "vy", "life", "max_life", "color")

    def __init__(self, x: float, y: float, color: Tuple[int, int, int]) -> None:
        self.x = x
        self.y = y
        angle = random.uniform(0, math.tau)
        speed = random.uniform(0.5, 2.5)
        self.vx = math.cos(angle) * speed
        self.vy = math.sin(angle) * speed
        self.max_life = random.randint(12, 24)
        self.life = self.max_life
        self.color = color

    def update(self) -> bool:
        self.x += self.vx
        self.y += self.vy
        self.vy += 0.05
        self.life -= 1
        return self.life > 0

    def draw(self, surface: pygame.Surface) -> None:
        ratio = self.life / self.max_life
        radius = max(1, int(3 * ratio))
        alpha = int(255 * ratio)
        size = radius * 2 + 2
        overlay = pygame.Surface((size, size), pygame.SRCALPHA)
        pygame.draw.circle(overlay, (*self.color, alpha), (size // 2, size // 2), radius)
        surface.blit(overlay, (int(self.x) - size // 2, int(self.y) - size // 2))


class ScorePopup:
    __slots__ = ("x", "y", "text", "life", "color", "font")

    def __init__(self, x: float, y: float, text: str, color: Tuple[int, int, int], font: pygame.font.Font) -> None:
        self.x = x
        self.y = y
        self.text = text
        self.life = POPUP_LIFETIME
        self.color = color
        self.font = font

    def update(self) -> bool:
        self.y -= 0.8
        self.life -= 1
        return self.life > 0

    def draw(self, surface: pygame.Surface) -> None:
        ratio = self.life / POPUP_LIFETIME
        alpha = max(0, min(255, int(255 * ratio * 1.5)))
        surf = self.font.render(self.text, True, self.color)
        if alpha < 255:
            surf = surf.copy()
            surf.set_alpha(alpha)
        surface.blit(surf, surf.get_rect(center=(int(self.x), int(self.y))))


# ----------------------------------------------------------------------------
# Game
# ----------------------------------------------------------------------------
class Game:
    MENU = "MENU"
    PLAYING = "PLAYING"
    PAUSED = "PAUSED"
    GAME_OVER = "GAME_OVER"
    WIN = "WIN"

    def __init__(self) -> None:
        pygame.init()
        pygame.display.set_caption("NOKIA SNAKE GAME - Enhanced")
        self.screen: pygame.Surface = pygame.display.set_mode((WIDTH, HEIGHT))
        self.clock: pygame.time.Clock = pygame.time.Clock()
        self.audio = Audio(enabled=True)

        self.font_title = make_font(58, bold=True)
        self.font_big = make_font(46, bold=True)
        self.font_med = make_font(24, bold=True)
        self.font_small = make_font(18)
        self.font_tiny = make_font(14)

        self.show_grid: bool = True
        self.difficulty: str = "NORMAL"
        self.scores: List[int] = load_scores()
        self.high_score: int = self.scores[0] if self.scores else 0

        self.snake = Snake()
        self.food: Optional[Food] = None
        self.bonus_food: Optional[Food] = None
        self.obstacles: List[GridPos] = []
        self.particles: List[Particle] = []
        self.popups: List[ScorePopup] = []

        self.score: int = 0
        self.food_count: int = 0
        self.level: int = 1
        self.shake_timer: int = 0
        self.slow_timer_ms: int = 0
        self.bonus_spawn_timer_ms: int = random.randint(
            BONUS_SPAWN_MIN_MS, BONUS_SPAWN_MAX_MS
        )
        self.last_move_ms: int = 0
        self.state: str = self.MENU
        self.menu_snake_t: float = 0.0

    # -- lifecycle ----------------------------------------------------------
    def quit(self) -> None:
        pygame.quit()
        sys.exit()

    def start_game(self) -> None:
        self.snake.reset()
        self.score = 0
        self.food_count = 0
        self.level = 1
        self.obstacles = build_obstacles(1)
        self.particles = []
        self.popups = []
        self.bonus_food = None
        self.slow_timer_ms = 0
        self.shake_timer = 0
        self.bonus_spawn_timer_ms = random.randint(
            BONUS_SPAWN_MIN_MS, BONUS_SPAWN_MAX_MS
        )
        self.food = self._spawn_food(prefer_special=True)
        self.state = self.PLAYING
        self.last_move_ms = pygame.time.get_ticks()
        self.audio.play("ui")

    @property
    def cfg(self) -> Dict[str, int]:
        return DIFFICULTIES[self.difficulty]

    @property
    def move_interval_ms(self) -> int:
        fps = self.current_fps
        return max(1, int(1000 / fps))

    @property
    def current_fps(self) -> float:
        base = float(self.cfg["base"])
        maximum = float(self.cfg["max"])
        inc = float(self.cfg["inc"])
        speedups = self.food_count // SPEEDUP_EVERY
        fps = base + speedups * inc
        if self.slow_timer_ms > 0:
            fps = max(6.0, fps * 0.55)  # SLOW food effect
        return min(maximum, fps)

    @property
    def render_alpha(self) -> float:
        """0..1 progress toward the next grid step (for smooth movement)."""
        if self.state != self.PLAYING:
            return 1.0
        now = pygame.time.get_ticks()
        elapsed = now - self.last_move_ms
        return max(0.0, min(1.0, elapsed / self.move_interval_ms))

    # -- spawning -----------------------------------------------------------
    def _spawn_food(self, prefer_special: bool = False) -> Optional[Food]:
        occupied = set(self.snake.segments) | set(self.obstacles)
        if self.food is not None:
            occupied.add(self.food.position)
        if self.bonus_food is not None:
            occupied.add(self.bonus_food.position)

        free = [
            (x, y)
            for x in range(COLS)
            for y in range(ROWS)
            if (x, y) not in occupied
        ]
        if not free:
            return None

        roll = random.random()
        if prefer_special and roll < 0.35:
            kind = random.choice(["SLOW", "SHRINK"])
        else:
            kind = "NORMAL"
        return Food(random.choice(free), kind=kind, timed=False)

    def _tick_bonus_spawn(self, dt_ms: int) -> None:
        """Spawn bonus food on a random 5-15s timer (not tied to eating)."""
        self.bonus_spawn_timer_ms -= dt_ms
        if self.bonus_spawn_timer_ms > 0:
            return
        # Timer elapsed -> attempt spawn, then schedule the next random interval
        self.bonus_spawn_timer_ms = random.randint(
            BONUS_SPAWN_MIN_MS, BONUS_SPAWN_MAX_MS
        )
        if self.bonus_food is not None:
            return
        occupied = set(self.snake.segments) | set(self.obstacles)
        if self.food is not None:
            occupied.add(self.food.position)
        free = [
            (x, y)
            for x in range(COLS)
            for y in range(ROWS)
            if (x, y) not in occupied
        ]
        if free:
            self.bonus_food = Food(
                random.choice(free),
                kind="BONUS",
                timed=True,
                lifetime_ms=BONUS_DURATION_MS,
            )

    # -- scoring / effects --------------------------------------------------
    def _add_score(self, amount: int, pos: GridPos, color: Tuple[int, int, int]) -> None:
        self.score += amount
        if self.score > self.high_score:
            self.high_score = self.score
        px, py = grid_to_pixel(*pos)
        self.popups.append(
            ScorePopup(px + CELL // 2, py + CELL // 2, f"+{amount}", color, self.font_med)
        )
        for _ in range(10):
            self.particles.append(Particle(px + CELL // 2, py + CELL // 2, color))

    def _commit_score(self) -> None:
        if self.score <= 0:
            return
        self.scores = save_score(self.score)
        self.high_score = self.scores[0] if self.scores else self.high_score
        self.score = 0  # prevent double-saving the same run

    # -- input --------------------------------------------------------------
    def handle_events(self) -> None:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                self._commit_score()
                self.quit()

            if event.type != pygame.KEYDOWN:
                continue

            if event.key == pygame.K_ESCAPE:
                if self.state == self.PAUSED:
                    self.state = self.PLAYING
                    self.last_move_ms = pygame.time.get_ticks()
                    self.audio.play("ui")
                elif self.state in (self.PLAYING, self.PAUSED):
                    self._commit_score()
                    self.state = self.MENU
                    self.audio.play("ui")
                else:
                    self._commit_score()
                    self.quit()

            if event.key == pygame.K_m:
                on = self.audio.toggle()
                if on:
                    self.audio.play("ui")

            if event.key == pygame.K_g:
                self.show_grid = not self.show_grid

            if self.state == self.MENU:
                if event.key == pygame.K_SPACE:
                    self.start_game()
                elif event.key in (pygame.K_1, pygame.K_KP1):
                    self.difficulty = "EASY"
                    self.audio.play("ui")
                elif event.key in (pygame.K_2, pygame.K_KP2):
                    self.difficulty = "NORMAL"
                    self.audio.play("ui")
                elif event.key in (pygame.K_3, pygame.K_KP3):
                    self.difficulty = "HARD"
                    self.audio.play("ui")

            elif self.state == self.PLAYING:
                if event.key in KEY_BINDINGS:
                    self.snake.change_direction(KEY_BINDINGS[event.key])
                elif event.key in (pygame.K_p, pygame.K_SPACE):
                    self.state = self.PAUSED
                    self.audio.play("ui")

            elif self.state == self.PAUSED:
                if event.key in (pygame.K_p, pygame.K_SPACE):
                    self.state = self.PLAYING
                    self.last_move_ms = pygame.time.get_ticks()
                    self.audio.play("ui")
                elif event.key == pygame.K_q:
                    self._commit_score()
                    self.state = self.MENU

            elif self.state in (self.GAME_OVER, self.WIN):
                if event.key == pygame.K_r:
                    self.start_game()
                elif event.key == pygame.K_q:
                    self._commit_score()
                    self.state = self.MENU
                    self.audio.play("ui")

    # -- update -------------------------------------------------------------
    def update(self, dt_ms: int) -> None:
        self.menu_snake_t += dt_ms / 1000.0

        # Visual effects always animate
        self.particles = [p for p in self.particles if p.update()]
        self.popups = [p for p in self.popups if p.update()]
        if self.shake_timer > 0:
            self.shake_timer -= 1

        if self.state == self.PLAYING:
            self._tick_bonus_spawn(dt_ms)
            if self.food:
                self.food.update(dt_ms)
            if self.bonus_food:
                self.bonus_food.update(dt_ms)
                if self.bonus_food.expired:
                    self.bonus_food = None
            if self.slow_timer_ms > 0:
                self.slow_timer_ms = max(0, self.slow_timer_ms - dt_ms)

            # Grid-step movement on a fixed interval
            now = pygame.time.get_ticks()
            if now - self.last_move_ms < self.move_interval_ms:
                return
            self.last_move_ms = now
        else:
            return

        self.snake.update()

        if self.snake.hits_wall() or self.snake.hits_self(self.obstacles):
            self._on_death()
            return

        self._check_food_collision()

        # Level progression
        new_level = min(MAX_LEVEL, 1 + self.food_count // LEVEL_EVERY)
        if new_level != self.level:
            self.level = new_level
            self.obstacles = build_obstacles(self.level)
            # If new obstacles landed on the snake head, treat as death next step
            if self.snake.head in self.obstacles:
                self._on_death()
                return
            self.audio.play("level")
            px, py = grid_to_pixel(COLS // 2, 3)
            self.popups.append(
                ScorePopup(px, py, f"LEVEL {self.level}", COLOR_NEON, self.font_med)
            )

    def _check_food_collision(self) -> None:
        head = self.snake.head

        if self.food and head == self.food.position:
            kind = self.food.kind
            color = self.food.color
            value = self.food.value
            if kind == "SHRINK":
                self.snake.shrink()
                self._add_score(value, head, color)
                self.audio.play("eat")
            elif kind == "SLOW":
                self.slow_timer_ms = SLOW_DURATION_MS
                self._add_score(value, head, color)
                self.audio.play("eat")
                px, py = grid_to_pixel(*head)
                self.popups.append(
                    ScorePopup(px, py + 18, "SLOW!", COLOR_SLOW, self.font_small)
                )
            else:
                self.snake.grow()
                self._add_score(value, head, color)
                self.audio.play("eat")

            self.food_count += 1
            self.food = self._spawn_food(prefer_special=(self.food_count % 3 == 0))
            if self.food is None and self.bonus_food is None:
                self.state = self.WIN
                self._commit_score()
            return

        if self.bonus_food and head == self.bonus_food.position:
            self.snake.grow()
            self._add_score(self.bonus_food.value, head, COLOR_BONUS)
            self.audio.play("bonus")
            self.bonus_food = None

    def _on_death(self) -> None:
        self.state = self.GAME_OVER
        self.shake_timer = SHAKE_FRAMES
        self.audio.play("crash")
        # Burst particles at head
        px, py = grid_to_pixel(*self.snake.head)
        for _ in range(18):
            self.particles.append(
                Particle(px + CELL // 2, py + CELL // 2, COLOR_ACCENT)
            )
        self._commit_score()

    # -- rendering ----------------------------------------------------------
    def draw(self) -> None:
        self.screen.fill(COLOR_BG)

        shake_x = shake_y = 0
        if self.shake_timer > 0:
            intensity = max(1, int(self.shake_timer / 3))
            shake_x = random.randint(-intensity, intensity)
            shake_y = random.randint(-intensity, intensity)

        if self.state == self.MENU:
            self._draw_menu()
        else:
            self._draw_playfield(shake_x, shake_y)
            if self.state == self.PAUSED:
                self._draw_pause()
            elif self.state == self.GAME_OVER:
                self._draw_game_over()
            elif self.state == self.WIN:
                self._draw_win()

        pygame.display.flip()

    def _draw_playfield(self, shake_x: int, shake_y: int) -> None:
        field = pygame.Surface((WIDTH, HEIGHT - HUD_HEIGHT))
        field.fill(COLOR_BG)

        if self.show_grid:
            for x in range(0, WIDTH + 1, CELL):
                pygame.draw.line(field, COLOR_GRID, (x, 0), (x, HEIGHT - HUD_HEIGHT))
            for y in range(0, HEIGHT - HUD_HEIGHT + 1, CELL):
                pygame.draw.line(field, COLOR_GRID, (0, y), (WIDTH, y))

        # Obstacles
        for ox, oy in self.obstacles:
            px, py = grid_to_pixel(ox, oy)
            rect = pygame.Rect(px, py - HUD_HEIGHT, CELL, CELL)
            pygame.draw.rect(field, COLOR_WALL, rect.inflate(-1, -1), border_radius=3)
            pygame.draw.rect(field, COLOR_WALL_EDGE, rect.inflate(-1, -1), 1, border_radius=3)

        self._draw_food_local(field, self.food)
        self._draw_food_local(field, self.bonus_food)

        # Interpolated snake (local Y already offset inside helper via HUD adjust)
        alpha = self.render_alpha
        points = self.snake.interpolated_segments(alpha)
        local_points = [(px, py - HUD_HEIGHT) for px, py in points]
        if local_points:
            glow_w = max(10, CELL - 2)
            if len(local_points) >= 2:
                pygame.draw.lines(field, COLOR_SNAKE_GLOW, False, local_points, glow_w)
                pygame.draw.lines(field, COLOR_SNAKE, False, local_points, glow_w - 4)
            for px, py in local_points[1:-1]:
                pygame.draw.circle(field, COLOR_SNAKE, (int(px), int(py)), (glow_w - 4) // 2)
            hx, hy = local_points[0]
            head_rect = pygame.Rect(0, 0, CELL, CELL)
            head_rect.center = (int(hx), int(hy))
            pygame.draw.rect(field, COLOR_SNAKE_HEAD, head_rect, border_radius=6)
            self.snake._draw_eyes(field, head_rect)

        # Particles & popups (Y shifted to field-local coords)
        self._draw_fx(field)

        pygame.draw.rect(field, COLOR_NEON, field.get_rect(), 2)
        self.screen.blit(field, (shake_x, HUD_HEIGHT + shake_y))
        self._draw_hud()

    def _draw_food_local(self, surface: pygame.Surface, food: Optional[Food]) -> None:
        if food is None:
            return
        # Temporarily patch coordinates by drawing into a one-cell surface
        px, py = grid_to_pixel(*food.position)
        rect = pygame.Rect(px, py - HUD_HEIGHT, CELL, CELL)

        wave = abs(food.pulse - 30) / 30.0
        grow = int(6 + wave * 6)
        if food.timed and food.remaining_ratio < 0.35 and (food.pulse // 8) % 2 == 0:
            grow += 4
        glow_rect = rect.inflate(grow, grow)
        glow_surf = pygame.Surface(glow_rect.size, pygame.SRCALPHA)
        pygame.draw.ellipse(glow_surf, (*food.glow, 55), glow_surf.get_rect())
        surface.blit(glow_surf, glow_rect.topleft)

        pygame.draw.rect(surface, food.color, rect.inflate(-4, -4), border_radius=6)
        pygame.draw.circle(
            surface,
            tuple(min(255, c + 70) for c in food.color),
            (rect.centerx - 3, rect.centery - 3),
            2,
        )
        if food.timed:
            pygame.draw.arc(
                surface,
                food.color,
                rect.inflate(2, 2),
                math.pi / 2,
                math.pi / 2 + (1.0 - food.remaining_ratio) * math.tau,
                2,
            )
        center = rect.center
        if food.kind == "BONUS":
            Food._draw_star(surface, center, 5, 6, COLOR_BLACK)
        elif food.kind == "SLOW":
            pygame.draw.line(surface, COLOR_BLACK, (center[0] - 4, center[1]), (center[0] + 4, center[1]), 2)
            pygame.draw.line(surface, COLOR_BLACK, (center[0], center[1] - 4), (center[0], center[1] + 4), 2)
        elif food.kind == "SHRINK":
            pygame.draw.line(surface, COLOR_BLACK, (center[0] - 4, center[1]), (center[0] + 4, center[1]), 2)

    def _draw_fx(self, surface: pygame.Surface) -> None:
        # Particles
        for particle in self.particles:
            ratio = particle.life / particle.max_life
            radius = max(1, int(3 * ratio))
            alpha = int(255 * ratio)
            size = radius * 2 + 2
            overlay = pygame.Surface((size, size), pygame.SRCALPHA)
            pygame.draw.circle(
                overlay, (*particle.color, alpha), (size // 2, size // 2), radius
            )
            surface.blit(
                overlay,
                (int(particle.x) - size // 2, int(particle.y) - HUD_HEIGHT - size // 2),
            )

        # Score popups
        for popup in self.popups:
            ratio = popup.life / POPUP_LIFETIME
            alpha = max(0, min(255, int(255 * ratio * 1.5)))
            surf = popup.font.render(popup.text, True, popup.color)
            if alpha < 255:
                surf = surf.copy()
                surf.set_alpha(alpha)
            surface.blit(
                surf,
                surf.get_rect(
                    center=(int(popup.x), int(popup.y) - HUD_HEIGHT)
                ),
            )

    def _draw_hud(self) -> None:
        pygame.draw.rect(self.screen, COLOR_HUD_BG, (0, 0, WIDTH, HUD_HEIGHT))
        pygame.draw.line(
            self.screen, COLOR_NEON, (0, HUD_HEIGHT - 1), (WIDTH, HUD_HEIGHT - 1), 2
        )

        score_surf = self.font_med.render(f"SCORE {self.score:03d}", True, COLOR_TEXT)
        high_surf = self.font_med.render(f"HIGH {self.high_score:03d}", True, COLOR_TEXT)
        level_surf = self.font_small.render(f"Lv {self.level}", True, COLOR_NEON)
        spd_surf = self.font_small.render(f"SPD {self.current_fps:.0f}", True, COLOR_TEXT_DIM)
        sound = "ON" if self.audio.enabled else "OFF"
        snd_surf = self.font_tiny.render(f"SND {sound} [M]", True, COLOR_TEXT_DIM)

        self.screen.blit(score_surf, (12, 11))
        self.screen.blit(high_surf, (WIDTH // 2 - high_surf.get_width() // 2, 11))
        right_x = WIDTH - 12
        for surf in (snd_surf, spd_surf, level_surf):
            right_x -= surf.get_width()
            self.screen.blit(surf, (right_x, 14))
            right_x -= 14

        if self.slow_timer_ms > 0:
            bar_w = int((self.slow_timer_ms / SLOW_DURATION_MS) * 140)
            pygame.draw.rect(self.screen, (30, 50, 70), (12, HUD_HEIGHT - 6, 140, 4))
            pygame.draw.rect(self.screen, COLOR_SLOW, (12, HUD_HEIGHT - 6, bar_w, 4))

    def _draw_menu(self) -> None:
        pygame.draw.rect(self.screen, COLOR_NEON, (0, 0, WIDTH, HEIGHT), 3)

        # Decorative moving snake
        t = self.menu_snake_t
        body = []
        for i in range(12):
            x = int((t * 60 + i * 18) % (WIDTH + 80)) - 40
            y = int(HEIGHT - 70 + math.sin((x + i * 10) * 0.03) * 10)
            body.append((x, y))
        if len(body) >= 2:
            pygame.draw.lines(self.screen, COLOR_SNAKE_GLOW, False, body, 16)
            pygame.draw.lines(self.screen, COLOR_SNAKE, False, body, 10)
        for x, y in body[::3]:
            pygame.draw.circle(self.screen, COLOR_SNAKE, (x, y), 5)

        title = self.font_title.render("NOKIA SNAKE GAME", True, COLOR_TEXT)
        shadow = self.font_title.render("NOKIA SNAKE GAME", True, (0, 70, 60))
        title_rect = title.get_rect(center=(WIDTH // 2, 120))
        self.screen.blit(shadow, title_rect.move(3, 3))
        self.screen.blit(title, title_rect)

        sub = self.font_small.render("ENHANCED  •  smooth motion • mazes • power-ups", True, COLOR_TEXT_DIM)
        self.screen.blit(sub, sub.get_rect(center=(WIDTH // 2, 170)))

        # Difficulty selector
        diff_label = self.font_med.render("DIFFICULTY", True, COLOR_WHITE)
        self.screen.blit(diff_label, diff_label.get_rect(center=(WIDTH // 2, 230)))
        options = ["EASY", "NORMAL", "HARD"]
        x_start = WIDTH // 2 - 180
        for i, name in enumerate(options):
            rect = pygame.Rect(x_start + i * 120, 255, 110, 34)
            selected = self.difficulty == name
            pygame.draw.rect(
                self.screen,
                COLOR_NEON if selected else (40, 60, 70),
                rect,
                border_radius=6,
            )
            if not selected:
                pygame.draw.rect(self.screen, COLOR_TEXT_DIM, rect, 1, border_radius=6)
            label = self.font_small.render(f"{name} [{i + 1}]", True, COLOR_BLACK if selected else COLOR_TEXT_DIM)
            self.screen.blit(label, label.get_rect(center=rect.center))

        if (pygame.time.get_ticks() // 500) % 2 == 0:
            start = self.font_med.render("Press SPACE to Start", True, COLOR_WHITE)
            self.screen.blit(start, start.get_rect(center=(WIDTH // 2, 340)))

        legend = [
            "RED +1 grow   GOLD +5 timed (every 5-15s)   BLUE slow-mo   PURPLE shrink",
            "Arrows/WASD move   P pause   M sound   G grid   ESC menu",
            "Mazes appear as Level increases!",
        ]
        for i, line in enumerate(legend):
            surf = self.font_tiny.render(line, True, COLOR_TEXT_DIM)
            self.screen.blit(surf, surf.get_rect(center=(WIDTH // 2, 400 + i * 24)))

        # Leaderboard
        board_title = self.font_med.render("LEADERBOARD", True, COLOR_NEON)
        self.screen.blit(board_title, board_title.get_rect(center=(WIDTH // 2, 490)))
        if self.scores:
            for i, value in enumerate(self.scores[:5]):
                row = self.font_small.render(f"  {i + 1}.  {value:04d}", True, COLOR_WHITE)
                self.screen.blit(row, row.get_rect(center=(WIDTH // 2, 520 + i * 22)))
        else:
            empty = self.font_small.render("No scores yet - be the first!", True, COLOR_TEXT_DIM)
            self.screen.blit(empty, empty.get_rect(center=(WIDTH // 2, 525)))

    def _draw_overlay(self) -> None:
        overlay = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 175))
        self.screen.blit(overlay, (0, 0))

    def _draw_pause(self) -> None:
        self._draw_overlay()
        title = self.font_big.render("PAUSED", True, COLOR_TEXT)
        self.screen.blit(title, title.get_rect(center=(WIDTH // 2, 240)))
        if (pygame.time.get_ticks() // 500) % 2 == 0:
            prompt = self.font_med.render("SPACE / P to Resume    Q to Menu", True, COLOR_WHITE)
            self.screen.blit(prompt, prompt.get_rect(center=(WIDTH // 2, 320)))

    def _draw_game_over(self) -> None:
        self._draw_overlay()
        title = self.font_big.render("GAME OVER", True, COLOR_ACCENT)
        self.screen.blit(title, title.get_rect(center=(WIDTH // 2, 180)))

        lines = [
            f"Final Score :  {self.score}",
            f"High Score  :  {self.high_score}",
            f"Level       :  {self.level}     Food: {self.food_count}",
            f"Difficulty  :  {self.difficulty}",
        ]
        for i, line in enumerate(lines):
            surf = self.font_med.render(line, True, COLOR_WHITE)
            self.screen.blit(surf, surf.get_rect(center=(WIDTH // 2, 250 + i * 34)))

        board = self.font_small.render(
            "Leaderboard: " + "  ".join(str(v) for v in self.scores[:3]),
            True,
            COLOR_TEXT,
        )
        self.screen.blit(board, board.get_rect(center=(WIDTH // 2, 400)))

        if (pygame.time.get_ticks() // 500) % 2 == 0:
            prompt = self.font_med.render("R Restart    Q Menu", True, COLOR_TEXT)
            self.screen.blit(prompt, prompt.get_rect(center=(WIDTH // 2, 460)))

    def _draw_win(self) -> None:
        self._draw_overlay()
        title = self.font_big.render("PERFECT RUN!", True, COLOR_TEXT)
        self.screen.blit(title, title.get_rect(center=(WIDTH // 2, 200)))
        sub = self.font_med.render("Board cleared - you win!", True, COLOR_WHITE)
        self.screen.blit(sub, sub.get_rect(center=(WIDTH // 2, 270)))
        score_line = self.font_med.render(f"Score: {self.score}", True, COLOR_BONUS)
        self.screen.blit(score_line, score_line.get_rect(center=(WIDTH // 2, 320)))
        if (pygame.time.get_ticks() // 500) % 2 == 0:
            prompt = self.font_med.render("R Restart    Q Menu", True, COLOR_TEXT)
            self.screen.blit(prompt, prompt.get_rect(center=(WIDTH // 2, 400)))

    # -- main loop ----------------------------------------------------------
    def run(self) -> None:
        while True:
            dt = self.clock.tick(60)  # render at 60 FPS; logic uses intervals
            self.handle_events()
            self.update(dt)
            self.draw()


# ----------------------------------------------------------------------------
# Entry point
# ----------------------------------------------------------------------------
if __name__ == "__main__":
    Game().run()
