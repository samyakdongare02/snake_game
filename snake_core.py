#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
snake_core.py - shared, pure-Python Snake game logic
=====================================================

This module contains the platform-independent core of the Snake game:

    * direction vectors + State enum
    * the deterministic GameModel (movement, food, collisions, scoring,
      level / speed progression, input queue with reversal protection)
    * HighScoreStore (atomic, crash-safe persistence)
    * procedural sound synthesis (sine/square notes -> mono 16-bit PCM WAV)

It has **no dependency on Tkinter, Kivy, or any GUI toolkit**, so the exact
same logic drives the desktop build (snake.py) and the Android build
(main.py), and it can be unit-tested headlessly.

The logic here is the verified logic from the desktop `snake.py`, extracted
verbatim so the mobile port preserves gameplay behaviour exactly.
"""

from __future__ import annotations

import io
import math
import os
import random
import struct
import tempfile
import wave
from collections import deque
from enum import Enum, auto

# ===========================================================================
# Geometry / tuning constants
# ===========================================================================

COLS = 25
ROWS = 17
CELL = 32

MAX_QUEUED_TURNS = 2

TICK_START = 0.160
TICK_STEP = 0.012
TICK_MIN = 0.070
APPLES_PER_LEVEL = 5
SCORE_PER_APPLE = 10

SHAKE_TIME = 0.45

# --- Neon / retro arcade palette (shared by desktop and mobile) ------------
COL_BG = "#0B1220"
COL_PANEL = "#111C33"
COL_GRID = "#18233D"
COL_CHECK_A = "#0F172A"
COL_CHECK_B = "#0D1424"
COL_BORDER = "#1E3A5F"

COL_HEAD = "#38D9FF"
COL_BODY_HEAD = "#2BB8E6"
COL_BODY_TAIL = "#0E7490"

COL_FOOD = "#FF6B6B"
COL_FOOD_DARK = "#7A2F3A"
COL_FOOD_GLOW = "#3A1520"
COL_LEAF = "#4ADE80"

COL_TEXT = "#E9F2FF"
COL_TEXT_DIM = "#7C93B8"
COL_ACCENT = "#38D9FF"
COL_DANGER = "#FF4D6D"
COL_GOLD = "#FFD166"
COL_PURPLE = "#A78BFA"

SAMPLE_RATE = 44100
DEFAULT_VOLUME = 70

UP = (0, -1)
DOWN = (0, 1)
LEFT = (-1, 0)
RIGHT = (1, 0)


# ===========================================================================
# Helpers
# ===========================================================================

def hex_to_rgb(h: str):
    h = h.lstrip("#")
    return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))


def rgb_to_hex(rgb) -> str:
    return "#%02X%02X%02X" % tuple(max(0, min(255, int(round(c)))) for c in rgb)


def hex_to_rgba(h: str, a: float = 1.0):
    r, g, b = hex_to_rgb(h)
    return (r / 255.0, g / 255.0, b / 255.0, a)


def lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def lerp_color(c1: str, c2: str, t: float) -> str:
    t = max(0.0, min(1.0, t))
    a = hex_to_rgb(c1)
    b = hex_to_rgb(c2)
    return rgb_to_hex(tuple(lerp(a[i], b[i], t) for i in range(3)))


def lerp_rgba(c1: str, c2: str, t: float, a: float = 1.0):
    return hex_to_rgba(lerp_color(c1, c2, t), a)


def is_opposite(d1, d2) -> bool:
    return d1[0] == -d2[0] and d1[1] == -d2[1]


# ===========================================================================
# Game state
# ===========================================================================

class State(Enum):
    START = auto()
    RUNNING = auto()
    PAUSED = auto()
    GAME_OVER = auto()
    VICTORY = auto()


# ===========================================================================
# Game model
# ===========================================================================

class GameModel:
    """Headless Snake logic. The rendering layer reads from this object."""

    def __init__(self, cols: int = COLS, rows: int = ROWS, rng=None):
        self.cols = cols
        self.rows = rows
        self.rng = rng if rng is not None else random.Random()
        self.reset()

    # -- lifecycle ----------------------------------------------------------
    def reset(self) -> None:
        cx = self.cols // 2
        cy = self.rows // 2
        self.body = [(cx - i, cy) for i in range(3)]   # head first
        self.prev_body = list(self.body)
        self.direction = RIGHT
        self.dir_queue = deque()
        self.score = 0
        self.apples = 0
        self.level = 1
        self.state = State.START
        self.food = None
        self.death_reason = None

    # -- derived properties -------------------------------------------------
    @property
    def tick_interval(self) -> float:
        return max(TICK_MIN, TICK_START - TICK_STEP * (self.level - 1))

    @property
    def speed_multiplier(self) -> float:
        return TICK_START / self.tick_interval

    @property
    def head(self):
        return self.body[0]

    # -- input --------------------------------------------------------------
    def queue_direction(self, d) -> bool:
        """Queue a turn. Rejects no-ops and 180-degree reversals."""
        reference = self.dir_queue[-1] if self.dir_queue else self.direction
        if d == reference:
            return False
        if is_opposite(d, reference):
            return False
        if len(self.dir_queue) >= MAX_QUEUED_TURNS:
            return False
        self.dir_queue.append(d)
        return True

    # -- food ---------------------------------------------------------------
    def spawn_food(self) -> bool:
        occupied = set(self.body)
        free = [
            (x, y)
            for y in range(self.rows)
            for x in range(self.cols)
            if (x, y) not in occupied
        ]
        if not free:
            self.food = None
            return False
        self.food = self.rng.choice(free)
        return True

    # -- simulation ---------------------------------------------------------
    def step(self) -> str:
        """Advance one logic tick.

        Returns one of: 'none', 'eat', 'death', 'win'.
        """
        if self.state != State.RUNNING:
            return "none"

        if self.dir_queue:
            pending = self.dir_queue.popleft()
            if not is_opposite(pending, self.direction) and pending != self.direction:
                self.direction = pending

        hx, hy = self.body[0]
        dx, dy = self.direction
        new_head = (hx + dx, hy + dy)

        # Wall collision (solid walls, no wrap).
        if not (0 <= new_head[0] < self.cols and 0 <= new_head[1] < self.rows):
            self.prev_body = list(self.body)
            self.state = State.GAME_OVER
            self.death_reason = "wall"
            return "death"

        eating = self.food is not None and new_head == self.food

        # Body collision. When NOT eating, the current tail cell will be
        # vacated this tick, so moving into it is legal (fair-play rule).
        if not eating and new_head in self.body[:-1]:
            self.prev_body = list(self.body)
            self.state = State.GAME_OVER
            self.death_reason = "self"
            return "death"

        self.prev_body = list(self.body)
        self.body.insert(0, new_head)

        if eating:
            self.score += SCORE_PER_APPLE
            self.apples += 1
            self.level = 1 + self.apples // APPLES_PER_LEVEL
            if not self.spawn_food():
                self.state = State.VICTORY
                return "win"
            return "eat"

        self.body.pop()
        return "none"


# ===========================================================================
# High score persistence (atomic, crash-safe)
# ===========================================================================

class HighScoreStore:
    def __init__(self, path: str | None = None):
        if path is None:
            path = os.path.join(os.path.expanduser("~"), "snake_highscore.txt")
        self.path = path
        self.value = self.load()

    def load(self) -> int:
        try:
            with open(self.path, "r", encoding="utf-8") as fh:
                text = fh.read().strip()
            return max(0, int(text)) if text else 0
        except (OSError, ValueError):
            return 0

    def save(self, value: int) -> bool:
        value = max(0, int(value))
        self.value = value
        try:
            directory = os.path.dirname(os.path.abspath(self.path)) or "."
            fd, tmp = tempfile.mkstemp(dir=directory, prefix=".snake_hs_", suffix=".tmp")
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as fh:
                    fh.write(str(value))
                os.replace(tmp, self.path)
            except Exception:
                try:
                    os.remove(tmp)
                except OSError:
                    pass
                raise
            return True
        except Exception:
            return False


# ===========================================================================
# Procedural sound synthesis (no external audio assets)
# ===========================================================================

def _note(freq, dur, waveform="sine", vol=0.5, attack=0.008, release=0.03):
    """Render a single enveloped note as a list of floats in [-1, 1]."""
    n = max(1, int(SAMPLE_RATE * dur))
    out = []
    two_pi = 2.0 * math.pi
    for i in range(n):
        t = i / SAMPLE_RATE
        phase = two_pi * freq * t
        if waveform == "square":
            s = 1.0 if math.sin(phase) >= 0.0 else -1.0
        elif waveform == "saw":
            s = 2.0 * ((freq * t) % 1.0) - 1.0
        elif waveform == "tri":
            s = 2.0 / math.pi * math.asin(math.sin(phase))
        else:
            s = math.sin(phase)
        env = 1.0
        if attack > 0.0 and t < attack:
            env = t / attack
        if release > 0.0 and t > dur - release:
            env = min(env, max(0.0, (dur - t) / release))
        out.append(s * vol * env)
    return out


def _silence(dur):
    return [0.0] * int(SAMPLE_RATE * dur)


def _concat(*parts):
    out = []
    for p in parts:
        out.extend(p)
    return out


def build_sound_bank():
    """Return {name: [float samples]} for every required sound effect."""
    return {
        # Short rising two-note blip.
        "eat": _concat(
            _note(880.0, 0.055, "sine", 0.50),
            _silence(0.008),
            _note(1318.5, 0.075, "sine", 0.50),
        ),
        # Low harsh descending square buzz.
        "hit": _concat(
            _note(240.0, 0.090, "square", 0.42),
            _silence(0.005),
            _note(150.0, 0.140, "square", 0.42),
        ),
        # Three descending notes.
        "game_over": _concat(
            _note(523.25, 0.150, "sine", 0.45),
            _silence(0.020),
            _note(392.00, 0.150, "sine", 0.45),
            _silence(0.020),
            _note(261.63, 0.300, "sine", 0.45),
        ),
        # Quick ascending arpeggio.
        "level_up": _concat(
            _note(523.25, 0.070, "sine", 0.45),
            _note(659.25, 0.070, "sine", 0.45),
            _note(783.99, 0.070, "sine", 0.45),
            _note(1046.5, 0.160, "sine", 0.45),
        ),
    }


def samples_to_wav_bytes(samples, volume: float) -> bytes:
    """Convert float samples to a mono 16-bit PCM WAV byte buffer."""
    buf = io.BytesIO()
    scale = max(0.0, min(1.0, volume / 100.0))
    frames = bytearray()
    for s in samples:
        v = int(max(-1.0, min(1.0, s * scale)) * 32767)
        frames += struct.pack("<h", v)
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SAMPLE_RATE)
        w.writeframes(bytes(frames))
    return buf.getvalue()


# ===========================================================================
# Headless self-test
# ===========================================================================

def run_self_test() -> int:
    results = []

    def check(name, condition, detail=""):
        results.append((name, bool(condition), detail))
        mark = "PASS" if condition else "FAIL"
        line = "  [%s] %s" % (mark, name)
        if detail and not condition:
            line += "  -> %s" % detail
        print(line)

    print("=" * 68)
    print("snake_core self test")
    print("=" * 68)

    # reversal prevention
    m = GameModel()
    m.state = State.RUNNING
    m.spawn_food()
    m.direction = RIGHT
    check("snake cannot reverse into itself", m.queue_direction(LEFT) is False)
    check("valid turn is queued", m.queue_direction(UP) is True)
    m.queue_direction(LEFT)
    m.queue_direction(DOWN)
    check("input buffer is bounded", len(m.dir_queue) <= MAX_QUEUED_TURNS,
          "len=%d" % len(m.dir_queue))

    # food on empty cells only
    clean = True
    for seed in range(400):
        mm = GameModel(rng=random.Random(seed))
        if not mm.spawn_food() or mm.food in mm.body:
            clean = False
            break
    check("food spawns only on empty cells", clean)

    # wall collision
    m = GameModel()
    m.state = State.RUNNING
    m.body = [(COLS - 1, 5), (COLS - 2, 5), (COLS - 3, 5)]
    m.prev_body = list(m.body)
    m.direction = RIGHT
    m.spawn_food()
    ev = m.step()
    check("wall collision detected",
          ev == "death" and m.state == State.GAME_OVER and m.death_reason == "wall")

    # self collision
    m = GameModel()
    m.state = State.RUNNING
    m.body = [(3, 3), (2, 3), (2, 4), (3, 4), (4, 4), (4, 3)]
    m.prev_body = list(m.body)
    m.direction = DOWN
    m.spawn_food()
    ev = m.step()
    check("self collision detected",
          ev == "death" and m.state == State.GAME_OVER and m.death_reason == "self")

    # fair-play tail rule
    m = GameModel()
    m.state = State.RUNNING
    m.body = [(5, 5), (6, 5), (6, 6), (5, 6)]
    m.prev_body = list(m.body)
    m.direction = DOWN
    m.food = None
    check("moving into vacating tail is allowed", m.step() == "none")

    # eating
    m = GameModel()
    m.state = State.RUNNING
    m.direction = RIGHT
    m.food = (m.head[0] + 1, m.head[1])
    n0, s0 = len(m.body), m.score
    ev = m.step()
    check("eating grows snake and scores",
          ev == "eat" and len(m.body) == n0 + 1 and m.score == s0 + SCORE_PER_APPLE)

    # level / speed progression
    m = GameModel()
    m.state = State.RUNNING
    m.direction = RIGHT
    i0 = m.tick_interval
    for _ in range(APPLES_PER_LEVEL):
        m.food = (m.head[0] + 1, m.head[1])
        m.step()
    check("level increases every %d apples" % APPLES_PER_LEVEL, m.level == 2)
    check("speed increases with level", m.tick_interval < i0)
    check("speed floor respected", GameModel().tick_interval >= TICK_MIN)

    # victory
    m = GameModel(cols=3, rows=1)
    m.state = State.RUNNING
    m.body = [(1, 0), (0, 0)]
    m.prev_body = list(m.body)
    m.direction = RIGHT
    m.food = (2, 0)
    ev = m.step()
    check("board-full victory detected", ev == "win" and m.state == State.VICTORY)

    # high score persistence
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "hs.txt")
        check("high score saves and reloads",
              HighScoreStore(path).save(1234) and HighScoreStore(path).value == 1234)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("garbage")
        check("corrupt high score file handled", HighScoreStore(path).value == 0)
        check("missing high score file returns 0",
              HighScoreStore(os.path.join(d, "nope.txt")).value == 0)

    # audio synthesis
    data = samples_to_wav_bytes(build_sound_bank()["eat"], 70)
    check("WAV generation produces data", len(data) > 44, "%d bytes" % len(data))
    with wave.open(io.BytesIO(data), "rb") as w:
        check("WAV is mono 16-bit 44100Hz",
              w.getnchannels() == 1 and w.getsampwidth() == 2
              and w.getframerate() == SAMPLE_RATE)

    passed = sum(1 for _, ok, _ in results if ok)
    total = len(results)
    print("-" * 68)
    print("Checks: %d/%d passed" % (passed, total))
    overall = passed == total
    print("SELF-TEST: %s" % ("PASS" if overall else "FAIL"))
    print("=" * 68)
    return 0 if overall else 1


if __name__ == "__main__":
    raise SystemExit(run_self_test())
