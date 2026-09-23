"""
NOKIA SNAKE GAME - Android / Touch Edition
===========================================
PC (dev test):
    pip install pygame
    python snake_game_android.py

Build Android APK (requires Linux/WSL + Android SDK):
    pip install buildozer cython
    buildozer init          # then merge with the buildozer.spec in this folder
    buildozer android debug
    # APK: bin/snakegameandroid-debug.apk  -> install on phone

Controls:
    Swipe        - Change direction
    Tap          - Start / Restart / Resume / Menu buttons
    (Keyboard still works on PC for testing)
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
# Android / portable paths
# ----------------------------------------------------------------------------
IS_ANDROID = bool(
    sys.platform == "android"
    or os.environ.get("ANDROID_ARGUMENT")
    or os.path.exists("/android")
)

if IS_ANDROID:
    # Writable app-private storage on Android
    BASE_DIR = os.environ.get("ANDROID_PRIVATE") or os.environ.get(
        "ANDROID_APP_HOME", os.path.expanduser("~")
    )
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

SCORES_FILE = os.path.join(BASE_DIR, "snake_scores.txt")

# ----------------------------------------------------------------------------
# Settings
# ----------------------------------------------------------------------------
WIDTH, HEIGHT = 800, 600
CELL = 20
HUD_HEIGHT = 44
COLS = WIDTH // CELL
ROWS = (HEIGHT - HUD_HEIGHT) // CELL

BASE_FPS = 15
MAX_FPS = 30
SPEEDUP_EVERY = 5
LEVEL_EVERY = 10
MAX_LEVEL = 5
SLOW_DURATION_MS = 4000
BONUS_DURATION_MS = 5000
BONUS_SPAWN_MIN_MS = 5000
BONUS_SPAWN_MAX_MS = 15000
POPUP_LIFETIME = 45
SHAKE_FRAMES = 18

# Touch tuning
SWIPE_MIN_DISTANCE = 24  # px before a drag counts as a swipe

DIFFICULTIES: Dict[str, Dict[str, int]] = {
    "EASY": {"base": 10, "max": 18, "inc": 1},
    "NORMAL": {"base": 15, "max": 30, "inc": 2},
    "HARD": {"base": 20, "max": 42, "inc": 3},
}

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
COLOR_BTN = (30, 70, 80)
COLOR_BTN_ON = (0, 255, 170)

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
    path = pygame.font.match_font(
        "dejavusans,dejavusansmono,consolas,couriernew,arial"
    )
    if path:
        font = pygame.font.Font(path, size)
        font.set_bold(bold)
        return font
    try:
        return pygame.font.SysFont("dejavusans,arial", size, bold=bold)
    except pygame.error:
        return pygame.font.Font(None, size)


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
) -> Optional[pygame.mixer.Sound]:
    try:
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
    except Exception:
        return None


class Audio:
    def __init__(self, enabled: bool = True) -> None:
        self.enabled = enabled
        self.available = False
        self.sounds: Dict[str, pygame.mixer.Sound] = {}
        try:
            pygame.mixer.init(frequency=22050, size=-16, channels=1, buffer=512)
            built = {
                "eat": generate_beep(660, 0.07, 0.22, square=False),
                "bonus": generate_beep(990, 0.12, 0.25, square=False),
                "crash": generate_beep(90, 0.30, 0.30, square=True),
                "ui": generate_beep(440, 0.05, 0.18, square=False),
                "level": generate_beep(880, 0.15, 0.20, square=False),
            }
            self.sounds = {k: v for k, v in built.items() if v is not None}
            self.available = bool(self.sounds)
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
# Touch input helper (swipe + tap)
# ----------------------------------------------------------------------------
class TouchInput:
    """Tracks drag/swipe and tap gestures for mobile."""

    def __init__(self) -> None:
        self.active: bool = False
        self.start_x: float = 0.0
        self.start_y: float = 0.0
        self.start_time: int = 0
        self.last_x: float = 0.0
        self.last_y: float = 0.0
        self.swipe_dir: Optional[str] = None
        self.tapped: bool = False
        self.tap_x: int = 0
        self.tap_y: int = 0

    def begin(self, x: float, y: float, now: int) -> None:
        self.active = True
        self.start_x = self.last_x = x
        self.start_y = self.last_y = y
        self.start_time = now

    def move(self, x: float, y: float) -> None:
        if not self.active:
            return
        dx = x - self.start_x
        dy = y - self.start_y
        if abs(dx) < SWIPE_MIN_DISTANCE and abs(dy) < SWIPE_MIN_DISTANCE:
            return
        if abs(dx) > abs(dy):
            self.swipe_dir = "RIGHT" if dx > 0 else "LEFT"
        else:
            self.swipe_dir = "DOWN" if dy > 0 else "UP"
        self.last_x, self.last_y = x, y

    def end(self, x: float, y: float, now: int) -> None:
        if not self.active:
            return
        self.active = False
        dx = x - self.start_x
        dy = y - self.start_y
        dist = math.hypot(dx, dy)
        # Short touch = tap (UI); longer directional drag = swipe already set
        if dist < SWIPE_MIN_DISTANCE and (now - self.start_time) < 400:
            self.tapped = True
            self.tap_x = int(x)
            self.tap_y = int(y)
        self.start_x = self.start_y = 0.0

    def consume_swipe(self) -> Optional[str]:
        direction = self.swipe_dir
        self.swipe_dir = None
        return direction

    def consume_tap(self) -> bool:
        tapped = self.tapped
        self.tapped = False
        return tapped


# ----------------------------------------------------------------------------
# Maze
# ----------------------------------------------------------------------------
def build_obstacles(level: int) -> List[GridPos]:
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

    if level >= 2:
        add_pillar(8, 8)
        add_pillar(COLS - 11, 8)
        add_pillar(8, ROWS - 11)
        add_pillar(COLS - 11, ROWS - 11)
    if level >= 3:
        add_line_horizontal(ROWS // 2, COLS // 2 - 7, COLS // 2 - 3)
        add_line_horizontal(ROWS // 2, COLS // 2 + 3, COLS // 2 + 7)
        for y in range(2, 8):
            cells.append((COLS // 2, y + ROWS // 2 - 4))
            cells.append((COLS // 2 - 1, y + ROWS // 2 - 4))
            cells.append((COLS // 2, ROWS - 1 - y))
            cells.append((COLS // 2 - 1, ROWS - 1 - y))
    if level >= 4:
        add_pillar(16, 6, 8, 2)
        add_pillar(16, ROWS - 8, 8, 2)
    if level >= 5:
        add_line_horizontal(ROWS // 2 - 6, 4, 14)
        add_line_horizontal(ROWS // 2 - 6, COLS - 15, COLS - 5)
        add_line_horizontal(ROWS // 2 + 5, 4, 14)
        add_line_horizontal(ROWS // 2 + 5, COLS - 15, COLS - 5)

    seen = set()
    unique: List[GridPos] = []
    for pos in cells:
        if pos not in seen:
            seen.add(pos)
            unique.append(pos)
    safe = {
        (c, r)
        for c in range(COLS // 2 - 4, COLS // 2 + 5)
        for r in range(ROWS // 2 - 3, ROWS // 2 + 4)
    }
    return [pos for pos in unique if pos not in safe]


# ----------------------------------------------------------------------------
# Snake
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
        if self.head in obstacles:
            return True
        return self.head in self.segments[1:]

    def interpolated_segments(self, alpha: float) -> List[PixelPos]:
        points: List[PixelPos] = []
        for i, (cx, cy) in enumerate(self.segments):
            if i < len(self.prev_segments):
                pcx, pcy = self.prev_segments[i]
                px = lerp(pcx * CELL + CELL // 2, cx * CELL + CELL // 2, alpha)
                py = lerp(pcy * CELL + CELL // 2, cy * CELL + CELL // 2, alpha)
            else:
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


class ScorePopup:
    __slots__ = ("x", "y", "text", "life", "color", "font")

    def __init__(
        self,
        x: float,
        y: float,
        text: str,
        color: Tuple[int, int, int],
        font: pygame.font.Font,
    ) -> None:
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

        # Android: fullscreen-ish display; PC: windowed 800x600
        if IS_ANDROID:
            pygame.display.set_caption("Nokia Snake")
            self.screen = pygame.display.set_mode((0, 0), pygame.FULLSCREEN)
            self.full_w, self.full_h = self.screen.get_size()
            # Scale virtual 800x600 surface to real screen
            self.scale = min(self.full_w / WIDTH, self.full_h / HEIGHT)
            self.view_w = int(WIDTH * self.scale)
            self.view_h = int(HEIGHT * self.scale)
            self.off_x = (self.full_w - self.view_w) // 2
            self.off_y = (self.full_h - self.view_h) // 2
            self.virt = pygame.Surface((WIDTH, HEIGHT))
            self.draw_surface = self.virt
        else:
            pygame.display.set_caption("NOKIA SNAKE GAME - Android Ready")
            self.screen = pygame.display.set_mode((WIDTH, HEIGHT))
            self.full_w, self.full_h = WIDTH, HEIGHT
            self.scale = 1.0
            self.view_w, self.view_h = WIDTH, HEIGHT
            self.off_x = self.off_y = 0
            self.virt = self.screen
            self.draw_surface = self.screen

        self.clock = pygame.time.Clock()
        self.audio = Audio(enabled=True)
        self.touch = TouchInput()

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

        # Tap-able UI rects (virtual coords)
        self._btn_diff_easy = pygame.Rect(WIDTH // 2 - 180, 255, 110, 34)
        self._btn_diff_norm = pygame.Rect(WIDTH // 2 - 60, 255, 110, 34)
        self._btn_diff_hard = pygame.Rect(WIDTH // 2 + 60, 255, 110, 34)
        self._btn_start = pygame.Rect(WIDTH // 2 - 140, 320, 280, 50)
        self._btn_pause = pygame.Rect(WIDTH - 58, 6, 48, 32)
        self._btn_restart = pygame.Rect(WIDTH // 2 - 150, 440, 140, 44)
        self._btn_menu = pygame.Rect(WIDTH // 2 + 10, 440, 140, 44)

    # -- coordinate transform (Android letterbox) ---------------------------
    def to_virtual(self, x: float, y: float) -> Tuple[int, int]:
        if IS_ANDROID:
            vx = (x - self.off_x) / self.scale
            vy = (y - self.off_y) / self.scale
            return int(vx), int(vy)
        return int(x), int(y)

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
        return max(1, int(1000 / self.current_fps))

    @property
    def current_fps(self) -> float:
        base = float(self.cfg["base"])
        maximum = float(self.cfg["max"])
        inc = float(self.cfg["inc"])
        speedups = self.food_count // SPEEDUP_EVERY
        fps = base + speedups * inc
        if self.slow_timer_ms > 0:
            fps = max(6.0, fps * 0.55)
        return min(maximum, fps)

    @property
    def render_alpha(self) -> float:
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
        self.bonus_spawn_timer_ms -= dt_ms
        if self.bonus_spawn_timer_ms > 0:
            return
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

    # -- effects ------------------------------------------------------------
    def _add_score(
        self, amount: int, pos: GridPos, color: Tuple[int, int, int]
    ) -> None:
        self.score += amount
        if self.score > self.high_score:
            self.high_score = self.score
        px, py = grid_to_pixel(*pos)
        self.popups.append(
            ScorePopup(
                px + CELL // 2, py + CELL // 2, f"+{amount}", color, self.font_med
            )
        )
        for _ in range(10):
            self.particles.append(Particle(px + CELL // 2, py + CELL // 2, color))

    def _commit_score(self) -> None:
        if self.score <= 0:
            return
        self.scores = save_score(self.score)
        self.high_score = self.scores[0] if self.scores else self.high_score
        self.score = 0

    # -- UI hit testing -----------------------------------------------------
    def _handle_tap(self, vx: int, vy: int) -> None:
        point = (vx, vy)
        if self.state == self.MENU:
            if self._btn_diff_easy.collidepoint(point):
                self.difficulty = "EASY"
                self.audio.play("ui")
            elif self._btn_diff_norm.collidepoint(point):
                self.difficulty = "NORMAL"
                self.audio.play("ui")
            elif self._btn_diff_hard.collidepoint(point):
                self.difficulty = "HARD"
                self.audio.play("ui")
            elif self._btn_start.collidepoint(point):
                self.start_game()
        elif self.state == self.PLAYING:
            if self._btn_pause.collidepoint(point):
                self.state = self.PAUSED
                self.audio.play("ui")
        elif self.state == self.PAUSED:
            if self._btn_start.collidepoint(point) or True:
                # Tap anywhere resumes (large touch target)
                self.state = self.PLAYING
                self.last_move_ms = pygame.time.get_ticks()
                self.audio.play("ui")
        elif self.state in (self.GAME_OVER, self.WIN):
            if self._btn_restart.collidepoint(point):
                self.start_game()
            elif self._btn_menu.collidepoint(point):
                self._commit_score()
                self.state = self.MENU
                self.audio.play("ui")

    # -- input --------------------------------------------------------------
    def handle_events(self) -> None:
        now = pygame.time.get_ticks()
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                self._commit_score()
                self.quit()

            # --- Android finger events ---
            if event.type == pygame.FINGERDOWN:
                px = event.x * self.full_w
                py = event.y * self.full_h
                self.touch.begin(px, py, now)
            elif event.type == pygame.FINGERMOTION:
                px = event.x * self.full_w
                py = event.y * self.full_h
                self.touch.move(px, py)
            elif event.type == pygame.FINGERUP:
                px = event.x * self.full_w
                py = event.y * self.full_h
                self.touch.end(px, py, now)

            # --- Mouse (PC / emulator) ---
            if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                self.touch.begin(event.pos[0], event.pos[1], now)
            elif event.type == pygame.MOUSEMOTION and self.touch.active:
                self.touch.move(event.pos[0], event.pos[1])
            elif event.type == pygame.MOUSEBUTTONUP and event.button == 1:
                self.touch.end(event.pos[0], event.pos[1], now)

            # --- Keyboard (PC testing) ---
            if event.type == pygame.KEYDOWN:
                self._handle_key(event.key)

        # Apply gestures
        swipe = self.touch.consume_swipe()
        if swipe:
            if self.state == self.PLAYING:
                self.snake.change_direction(swipe)
        if self.touch.consume_tap():
            vx, vy = self.to_virtual(self.touch.tap_x, self.touch.tap_y)
            self._handle_tap(vx, vy)

    def _handle_key(self, key: int) -> None:
        if key == pygame.K_ESCAPE:
            if self.state == self.PAUSED:
                self.state = self.PLAYING
                self.last_move_ms = pygame.time.get_ticks()
            elif self.state in (self.PLAYING, self.PAUSED):
                self._commit_score()
                self.state = self.MENU
            else:
                self._commit_score()
                self.quit()
            self.audio.play("ui")
            return

        if key == pygame.K_m:
            if self.audio.toggle():
                self.audio.play("ui")
        if key == pygame.K_g:
            self.show_grid = not self.show_grid

        if self.state == self.MENU:
            if key == pygame.K_SPACE:
                self.start_game()
            elif key in (pygame.K_1, pygame.K_KP1):
                self.difficulty = "EASY"
                self.audio.play("ui")
            elif key in (pygame.K_2, pygame.K_KP2):
                self.difficulty = "NORMAL"
                self.audio.play("ui")
            elif key in (pygame.K_3, pygame.K_KP3):
                self.difficulty = "HARD"
                self.audio.play("ui")
        elif self.state == self.PLAYING:
            if key in KEY_BINDINGS:
                self.snake.change_direction(KEY_BINDINGS[key])
            elif key in (pygame.K_p, pygame.K_SPACE):
                self.state = self.PAUSED
                self.audio.play("ui")
        elif self.state == self.PAUSED:
            if key in (pygame.K_p, pygame.K_SPACE):
                self.state = self.PLAYING
                self.last_move_ms = pygame.time.get_ticks()
                self.audio.play("ui")
            elif key == pygame.K_q:
                self._commit_score()
                self.state = self.MENU
        elif self.state in (self.GAME_OVER, self.WIN):
            if key == pygame.K_r:
                self.start_game()
            elif key == pygame.K_q:
                self._commit_score()
                self.state = self.MENU
                self.audio.play("ui")

    # -- update -------------------------------------------------------------
    def update(self, dt_ms: int) -> None:
        self.menu_snake_t += dt_ms / 1000.0

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

        new_level = min(MAX_LEVEL, 1 + self.food_count // LEVEL_EVERY)
        if new_level != self.level:
            self.level = new_level
            self.obstacles = build_obstacles(self.level)
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
        px, py = grid_to_pixel(*self.snake.head)
        for _ in range(18):
            self.particles.append(
                Particle(px + CELL // 2, py + CELL // 2, COLOR_ACCENT)
            )
        self._commit_score()

    # -- rendering ----------------------------------------------------------
    def draw(self) -> None:
        surf = self.draw_surface
        surf.fill(COLOR_BG)

        shake_x = shake_y = 0
        if self.shake_timer > 0:
            intensity = max(1, int(self.shake_timer / 3))
            shake_x = random.randint(-intensity, intensity)
            shake_y = random.randint(-intensity, intensity)

        if self.state == self.MENU:
            self._draw_menu(surf)
        else:
            self._draw_playfield(surf, shake_x, shake_y)
            if self.state == self.PAUSED:
                self._draw_pause(surf)
            elif self.state == self.GAME_OVER:
                self._draw_game_over(surf)
            elif self.state == self.WIN:
                self._draw_win(surf)

        # Present (scale on Android)
        if IS_ANDROID:
            self.screen.fill(COLOR_BLACK)
            scaled = pygame.transform.smoothscale(
                surf, (self.view_w, self.view_h)
            )
            self.screen.blit(scaled, (self.off_x, self.off_y))
        pygame.display.flip()

    def _draw_playfield(
        self, field_parent: pygame.Surface, shake_x: int, shake_y: int
    ) -> None:
        field = pygame.Surface((WIDTH, HEIGHT - HUD_HEIGHT))
        field.fill(COLOR_BG)

        if self.show_grid:
            for x in range(0, WIDTH + 1, CELL):
                pygame.draw.line(field, COLOR_GRID, (x, 0), (x, HEIGHT - HUD_HEIGHT))
            for y in range(0, HEIGHT - HUD_HEIGHT + 1, CELL):
                pygame.draw.line(field, COLOR_GRID, (0, y), (WIDTH, y))

        for ox, oy in self.obstacles:
            px, py = grid_to_pixel(ox, oy)
            rect = pygame.Rect(px, py - HUD_HEIGHT, CELL, CELL)
            pygame.draw.rect(field, COLOR_WALL, rect.inflate(-1, -1), border_radius=3)
            pygame.draw.rect(
                field, COLOR_WALL_EDGE, rect.inflate(-1, -1), 1, border_radius=3
            )

        self._draw_food_local(field, self.food)
        self._draw_food_local(field, self.bonus_food)

        alpha = self.render_alpha
        points = self.snake.interpolated_segments(alpha)
        local_points = [(px, py - HUD_HEIGHT) for px, py in points]
        if local_points:
            glow_w = max(10, CELL - 2)
            if len(local_points) >= 2:
                pygame.draw.lines(
                    field, COLOR_SNAKE_GLOW, False, local_points, glow_w
                )
                pygame.draw.lines(field, COLOR_SNAKE, False, local_points, glow_w - 4)
            for px, py in local_points[1:-1]:
                pygame.draw.circle(
                    field, COLOR_SNAKE, (int(px), int(py)), (glow_w - 4) // 2
                )
            hx, hy = local_points[0]
            head_rect = pygame.Rect(0, 0, CELL, CELL)
            head_rect.center = (int(hx), int(hy))
            pygame.draw.rect(field, COLOR_SNAKE_HEAD, head_rect, border_radius=6)
            self.snake._draw_eyes(field, head_rect)

        self._draw_fx(field)
        pygame.draw.rect(field, COLOR_NEON, field.get_rect(), 2)
        field_parent.blit(field, (shake_x, HUD_HEIGHT + shake_y))
        self._draw_hud(field_parent)

    def _draw_food_local(self, surface: pygame.Surface, food: Optional[Food]) -> None:
        if food is None:
            return
        px, py = grid_to_pixel(*food.position)
        rect = pygame.Rect(px, py - HUD_HEIGHT, CELL, CELL)

        wave = abs(food.pulse - 30) / 30.0
        grow = int(6 + wave * 6)
        if (
            food.timed
            and food.remaining_ratio < 0.35
            and (food.pulse // 8) % 2 == 0
        ):
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
            pygame.draw.line(
                surface,
                COLOR_BLACK,
                (center[0] - 4, center[1]),
                (center[0] + 4, center[1]),
                2,
            )
            pygame.draw.line(
                surface,
                COLOR_BLACK,
                (center[0], center[1] - 4),
                (center[0], center[1] + 4),
                2,
            )
        elif food.kind == "SHRINK":
            pygame.draw.line(
                surface,
                COLOR_BLACK,
                (center[0] - 4, center[1]),
                (center[0] + 4, center[1]),
                2,
            )

    def _draw_fx(self, surface: pygame.Surface) -> None:
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
                (
                    int(particle.x) - size // 2,
                    int(particle.y) - HUD_HEIGHT - size // 2,
                ),
            )

        for popup in self.popups:
            ratio = popup.life / POPUP_LIFETIME
            alpha = max(0, min(255, int(255 * ratio * 1.5)))
            text_surf = popup.font.render(popup.text, True, popup.color)
            if alpha < 255:
                text_surf = text_surf.copy()
                text_surf.set_alpha(alpha)
            surface.blit(
                text_surf,
                text_surf.get_rect(
                    center=(int(popup.x), int(popup.y) - HUD_HEIGHT)
                ),
            )

    def _draw_btn(
        self,
        surface: pygame.Surface,
        rect: pygame.Rect,
        label: str,
        active: bool = False,
        font: Optional[pygame.font.Font] = None,
    ) -> None:
        color = COLOR_BTN_ON if active else COLOR_BTN
        pygame.draw.rect(surface, color, rect, border_radius=8)
        pygame.draw.rect(surface, COLOR_NEON if active else COLOR_TEXT_DIM, rect, 2, border_radius=8)
        f = font or self.font_small
        label_surf = f.render(label, True, COLOR_BLACK if active else COLOR_WHITE)
        surface.blit(label_surf, label_surf.get_rect(center=rect.center))

    def _draw_hud(self, surface: pygame.Surface) -> None:
        pygame.draw.rect(surface, COLOR_HUD_BG, (0, 0, WIDTH, HUD_HEIGHT))
        pygame.draw.line(
            surface, COLOR_NEON, (0, HUD_HEIGHT - 1), (WIDTH, HUD_HEIGHT - 1), 2
        )

        score_surf = self.font_med.render(f"SCORE {self.score:03d}", True, COLOR_TEXT)
        high_surf = self.font_med.render(f"HIGH {self.high_score:03d}", True, COLOR_TEXT)
        level_surf = self.font_small.render(f"Lv {self.level}", True, COLOR_NEON)
        spd_surf = self.font_small.render(
            f"SPD {self.current_fps:.0f}", True, COLOR_TEXT_DIM
        )
        sound = "ON" if self.audio.enabled else "OFF"
        snd_surf = self.font_tiny.render(f"SND {sound}", True, COLOR_TEXT_DIM)

        surface.blit(score_surf, (12, 11))
        surface.blit(high_surf, (WIDTH // 2 - high_surf.get_width() // 2, 11))

        # Pause button (tap target)
        self._draw_btn(surface, self._btn_pause, "II", active=False, font=self.font_small)

        right_x = WIDTH - 70
        for surf in (snd_surf, spd_surf, level_surf):
            right_x -= surf.get_width()
            if right_x < 200:
                break
            surface.blit(surf, (right_x, 14))
            right_x -= 10

        if self.slow_timer_ms > 0:
            bar_w = int((self.slow_timer_ms / SLOW_DURATION_MS) * 140)
            pygame.draw.rect(surface, (30, 50, 70), (12, HUD_HEIGHT - 6, 140, 4))
            pygame.draw.rect(surface, COLOR_SLOW, (12, HUD_HEIGHT - 6, bar_w, 4))

    def _draw_menu(self, surface: pygame.Surface) -> None:
        pygame.draw.rect(surface, COLOR_NEON, (0, 0, WIDTH, HEIGHT), 3)

        t = self.menu_snake_t
        body = []
        for i in range(12):
            x = int((t * 60 + i * 18) % (WIDTH + 80)) - 40
            y = int(HEIGHT - 70 + math.sin((x + i * 10) * 0.03) * 10)
            body.append((x, y))
        if len(body) >= 2:
            pygame.draw.lines(surface, COLOR_SNAKE_GLOW, False, body, 16)
            pygame.draw.lines(surface, COLOR_SNAKE, False, body, 10)

        title = self.font_title.render("NOKIA SNAKE", True, COLOR_TEXT)
        shadow = self.font_title.render("NOKIA SNAKE", True, (0, 70, 60))
        title_rect = title.get_rect(center=(WIDTH // 2, 100))
        surface.blit(shadow, title_rect.move(3, 3))
        surface.blit(title, title_rect)

        sub = self.font_small.render(
            "Swipe to move  •  Tap buttons", True, COLOR_TEXT_DIM
        )
        surface.blit(sub, sub.get_rect(center=(WIDTH // 2, 155)))

        diff_label = self.font_med.render("DIFFICULTY", True, COLOR_WHITE)
        surface.blit(diff_label, diff_label.get_rect(center=(WIDTH // 2, 220)))

        self._draw_btn(
            surface, self._btn_diff_easy, "EASY", self.difficulty == "EASY"
        )
        self._draw_btn(
            surface, self._btn_diff_norm, "NORMAL", self.difficulty == "NORMAL"
        )
        self._draw_btn(
            surface, self._btn_diff_hard, "HARD", self.difficulty == "HARD"
        )

        # Big start button
        self._draw_btn(
            surface, self._btn_start, "TAP TO START", True, font=self.font_med
        )

        legend = [
            "RED +1   GOLD +5 timer   BLUE slow   PURPLE shrink",
            "Swipe to steer   Pause: II button",
        ]
        for i, line in enumerate(legend):
            surf = self.font_tiny.render(line, True, COLOR_TEXT_DIM)
            surface.blit(surf, surf.get_rect(center=(WIDTH // 2, 395 + i * 22)))

        board_title = self.font_med.render("LEADERBOARD", True, COLOR_NEON)
        surface.blit(board_title, board_title.get_rect(center=(WIDTH // 2, 460)))
        if self.scores:
            for i, value in enumerate(self.scores[:5]):
                row = self.font_small.render(
                    f"  {i + 1}.  {value:04d}", True, COLOR_WHITE
                )
                surface.blit(row, row.get_rect(center=(WIDTH // 2, 490 + i * 20)))
        else:
            empty = self.font_small.render(
                "No scores yet!", True, COLOR_TEXT_DIM
            )
            surface.blit(empty, empty.get_rect(center=(WIDTH // 2, 500)))

    def _draw_overlay(self, surface: pygame.Surface) -> None:
        overlay = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 175))
        surface.blit(overlay, (0, 0))

    def _draw_pause(self, surface: pygame.Surface) -> None:
        self._draw_overlay(surface)
        title = self.font_big.render("PAUSED", True, COLOR_TEXT)
        surface.blit(title, title.get_rect(center=(WIDTH // 2, 240)))
        self._draw_btn(
            surface, self._btn_start, "TAP TO RESUME", True, font=self.font_med
        )

    def _draw_game_over(self, surface: pygame.Surface) -> None:
        self._draw_overlay(surface)
        title = self.font_big.render("GAME OVER", True, COLOR_ACCENT)
        surface.blit(title, title.get_rect(center=(WIDTH // 2, 170)))

        lines = [
            f"Score :  {self.score}",
            f"High  :  {self.high_score}",
            f"Level :  {self.level}    Food: {self.food_count}",
        ]
        for i, line in enumerate(lines):
            surf = self.font_med.render(line, True, COLOR_WHITE)
            surface.blit(surf, surf.get_rect(center=(WIDTH // 2, 240 + i * 34)))

        board = self.font_small.render(
            "Top: " + "  ".join(str(v) for v in self.scores[:3]),
            True,
            COLOR_TEXT,
        )
        surface.blit(board, board.get_rect(center=(WIDTH // 2, 370)))

        self._draw_btn(surface, self._btn_restart, "RESTART", True, self.font_med)
        self._draw_btn(surface, self._btn_menu, "MENU", False, self.font_med)

    def _draw_win(self, surface: pygame.Surface) -> None:
        self._draw_overlay(surface)
        title = self.font_big.render("PERFECT RUN!", True, COLOR_TEXT)
        surface.blit(title, title.get_rect(center=(WIDTH // 2, 200)))
        score_line = self.font_med.render(f"Score: {self.score}", True, COLOR_BONUS)
        surface.blit(score_line, score_line.get_rect(center=(WIDTH // 2, 280)))
        self._draw_btn(surface, self._btn_restart, "RESTART", True, self.font_med)
        self._draw_btn(surface, self._btn_menu, "MENU", False, self.font_med)

    # -- main loop ----------------------------------------------------------
    def run(self) -> None:
        while True:
            dt = self.clock.tick(60)
            self.handle_events()
            self.update(dt)
            self.draw()


# ----------------------------------------------------------------------------
# Buildozer / Android entry point
# ----------------------------------------------------------------------------
def main() -> None:
    Game().run()


if __name__ == "__main__":
    main()
