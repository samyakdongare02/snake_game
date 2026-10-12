#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Snake - Animated Python
=======================

A polished, smoothly animated Snake game built with the Python standard
library only (Option A):

    * Tkinter   -> window, canvas rendering, UI, 60 FPS animation loop, input
    * winsound  -> audio playback on Windows (best-effort fallbacks elsewhere)
    * wave/math -> procedural sound generation (no external audio files)

Everything (visuals and sound) is generated at runtime. No assets required.

Run:
    python snake.py
    python snake.py --self-test

Controls:
    Arrow keys / WASD   move
    P                   pause / resume
    M                   mute / unmute
    - / +               volume down / up
    Enter / Space       start / restart
    Esc                 quit
"""

from __future__ import annotations

import io
import math
import os
import random
import shutil
import struct
import subprocess
import sys
import tempfile
import time
import traceback
import wave
from collections import deque
from enum import Enum, auto

# ---------------------------------------------------------------------------
# Tkinter is part of the standard library but importing it can fail on a truly
# headless build. Guard it so pure-logic self-tests can still run.
# ---------------------------------------------------------------------------
try:
    import tkinter as tk
    from tkinter import font as tkfont

    _TK_IMPORT_ERROR = None
except Exception as _tk_exc:  # pragma: no cover - depends on environment
    tk = None
    tkfont = None
    _TK_IMPORT_ERROR = _tk_exc


# ===========================================================================
# Constants
# ===========================================================================

APP_NAME = "Snake - Animated Python"
APP_TITLE = "Snake \u2014 Animated Python"
__version__ = "1.0.0"

WINDOW_W = 800
WINDOW_H = 600
HUD_H = 56

COLS = 25
ROWS = 17
CELL = 32

PLAY_X = 0
PLAY_Y = HUD_H
PLAY_W = COLS * CELL          # 800
PLAY_H = ROWS * CELL          # 544

FRAME_MS = 16                 # ~60 FPS render loop
MAX_QUEUED_TURNS = 2          # input buffer depth

# Speed / level tuning
TICK_START = 0.160            # seconds per logic step at level 1
TICK_STEP = 0.012             # seconds shaved per level
TICK_MIN = 0.070              # fastest logic step
APPLES_PER_LEVEL = 5
SCORE_PER_APPLE = 10

SHAKE_TIME = 0.45

# --- Colour palette (neon / retro arcade) ---------------------------------
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

# Directions as unit vectors. Compared by value.
UP = (0, -1)
DOWN = (0, 1)
LEFT = (-1, 0)
RIGHT = (1, 0)


# ===========================================================================
# Small helpers
# ===========================================================================

def hex_to_rgb(h: str):
    h = h.lstrip("#")
    return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))


def rgb_to_hex(rgb) -> str:
    return "#%02X%02X%02X" % tuple(max(0, min(255, int(round(c)))) for c in rgb)


def lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def lerp_color(c1: str, c2: str, t: float) -> str:
    t = max(0.0, min(1.0, t))
    a = hex_to_rgb(c1)
    b = hex_to_rgb(c2)
    return rgb_to_hex(tuple(lerp(a[i], b[i], t) for i in range(3)))


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
# Game model (pure logic, no Tkinter -> fully unit testable)
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
        # Food never spawns on the snake, so an eating move is never blocked
        # by this check.
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
# High score storage (atomic, crash safe)
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
# Procedural audio engine
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


class AudioEngine:
    """Generates WAV data in memory and plays it safely. Never raises."""

    def __init__(self, volume: int = DEFAULT_VOLUME, muted: bool = False):
        self.volume = int(max(0, min(100, volume)))
        self.muted = bool(muted)
        self.available = False
        self.backend = None
        self.error = None
        self._tmp = None
        self._bank = {}
        self._files = {}
        self._winsound = None
        self._player = None
        try:
            self._init_backend()
            self._bank = build_sound_bank()
            # Pre-validate that we can encode audio at all.
            samples_to_wav_bytes(self._bank["eat"], 1.0)
            self.available = True
        except Exception as exc:  # pragma: no cover - platform dependent
            self.error = str(exc)
            self.available = False
            if self._tmp is not None:
                try:
                    self._tmp.cleanup()
                except Exception:
                    pass
                self._tmp = None

    def _init_backend(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="snake_audio_")
        if sys.platform.startswith("win"):
            import winsound  # part of the standard library on Windows

            self._winsound = winsound
            self.backend = "winsound"
            return
        # Best-effort fallback for macOS / Linux.
        for player in ("afplay", "paplay", "aplay", "ffplay"):
            path = shutil.which(player)
            if path:
                self._player = path
                self.backend = player
                return
        raise RuntimeError("no system audio player found")

    def _ensure_file(self, name: str, volume: int) -> str:
        bucket = int(round(volume / 10.0))
        key = (name, bucket)
        existing = self._files.get(key)
        if existing and os.path.exists(existing):
            return existing
        data = samples_to_wav_bytes(self._bank[name], bucket * 10)
        path = os.path.join(self._tmp.name, "%s_%d.wav" % (name, bucket))
        with open(path, "wb") as fh:
            fh.write(data)
        self._files[key] = path
        return path

    def play(self, name: str) -> None:
        if not self.available or self.muted or self.volume <= 0:
            return
        if name not in self._bank:
            return
        try:
            path = self._ensure_file(name, self.volume)
            if self.backend == "winsound":
                self._winsound.PlaySound(
                    path,
                    self._winsound.SND_FILENAME
                    | self._winsound.SND_ASYNC
                    | self._winsound.SND_NODEFAULT,
                )
            elif self._player:
                subprocess.Popen(
                    [self._player, path],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
        except Exception:
            # Audio must never crash gameplay.
            pass

    def stop(self) -> None:
        try:
            if self.backend == "winsound" and self._winsound is not None:
                self._winsound.PlaySound(None, self._winsound.SND_PURGE)
        except Exception:
            pass

    def close(self) -> None:
        self.stop()
        if self._tmp is not None:
            try:
                self._tmp.cleanup()
            except Exception:
                pass
            self._tmp = None


# ===========================================================================
# The Tkinter application
# ===========================================================================

class SnakeApp:
    def __init__(self, highscore_path: str | None = None, muted: bool = False):
        if tk is None:  # pragma: no cover
            raise RuntimeError("Tkinter is not available: %s" % _TK_IMPORT_ERROR)

        self.root = tk.Tk()
        self.root.title(APP_TITLE)
        self.root.resizable(False, False)
        self.root.configure(bg=COL_BG)
        self._center_window()

        self.canvas = tk.Canvas(
            self.root,
            width=WINDOW_W,
            height=WINDOW_H,
            bg=COL_BG,
            highlightthickness=0,
            bd=0,
        )
        self.canvas.pack(fill="both", expand=True)
        self.canvas.focus_set()

        # Fonts
        self.font_hud = tkfont.Font(family="Consolas", size=14, weight="bold")
        self.font_hud_label = tkfont.Font(family="Consolas", size=9)
        self.font_title = tkfont.Font(family="Consolas", size=64, weight="bold")
        self.font_big = tkfont.Font(family="Consolas", size=34, weight="bold")
        self.font_med = tkfont.Font(family="Consolas", size=17, weight="bold")
        self.font_small = tkfont.Font(family="Consolas", size=12)

        # Systems
        self.model = GameModel()
        self.high_store = HighScoreStore(highscore_path)
        self.highscore = self.high_store.value
        self.new_record = False
        self.audio = AudioEngine(muted=muted)

        # Animation / timing
        self._last = time.perf_counter()
        self.accum = 0.0
        self.t = 0.0
        self.anim_phase = 0.0
        self.blink_phase = 0.0
        self.shake = 0.0
        self.flash = 0.0
        self.particles = []
        self.rings = []
        self.closing = False
        self.after_id = None
        self._pending = set()
        self.rng = random.Random()
        self.frames_rendered = 0
        # Self-tuning frame scheduler: adapts the requested after() delay so the
        # realised frame period converges on FRAME_MS on any machine/timer.
        self._frame_budget = FRAME_MS / 1000.0
        self._sched_ms = float(FRAME_MS)
        self._last_loop = None

        # Bindings
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.root.bind("<Key>", self._on_key)

        self._draw_static()

    # -- window -------------------------------------------------------------
    def _center_window(self):
        self.root.update_idletasks()
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        x = max(0, (sw - WINDOW_W) // 2)
        y = max(0, (sh - WINDOW_H) // 2)
        self.root.geometry("%dx%d+%d+%d" % (WINDOW_W, WINDOW_H, x, y))

    # -- scheduling ---------------------------------------------------------
    def _schedule(self, ms: int, fn):
        if self.closing:
            return None
        holder = {}

        def wrap():
            self._pending.discard(holder.get("id"))
            if not self.closing:
                try:
                    fn()
                except Exception:
                    traceback.print_exc()

        aid = self.root.after(ms, wrap)
        holder["id"] = aid
        self._pending.add(aid)
        return aid

    def _cancel_pending(self):
        for aid in list(self._pending):
            try:
                self.root.after_cancel(aid)
            except Exception:
                pass
        self._pending.clear()

    # -- input --------------------------------------------------------------
    def _on_key(self, event):
        key = (event.keysym or "").lower()
        state = self.model.state

        # Global keys
        if key == "m":
            self.audio.muted = not self.audio.muted
            return
        if key == "escape":
            self.close()
            return
        if key in ("minus", "underscore"):
            self._change_volume(-10)
            return
        if key in ("equal", "plus"):
            self._change_volume(10)
            return

        if key in ("up", "w"):
            self._queue_dir(UP)
        elif key in ("down", "s"):
            self._queue_dir(DOWN)
        elif key in ("left", "a"):
            self._queue_dir(LEFT)
        elif key in ("right", "d"):
            self._queue_dir(RIGHT)

        if key in ("return", "kp_enter", "space"):
            if state == State.START or state == State.GAME_OVER or state == State.VICTORY:
                self._start_game()
            elif state == State.PAUSED:
                self._toggle_pause()

        if key == "p":
            self._toggle_pause()

    def _queue_dir(self, d):
        if self.model.state == State.RUNNING:
            return self.model.queue_direction(d)
        return False

    def _change_volume(self, delta):
        self.audio.volume = int(max(0, min(100, self.audio.volume + delta)))
        if self.audio.muted and self.audio.volume > 0:
            self.audio.muted = False
        self.audio.play("eat")  # audible feedback at the new level

    # -- state transitions --------------------------------------------------
    def _start_game(self):
        self.model.reset()
        self.model.spawn_food()
        self.model.state = State.RUNNING
        self.accum = 0.0
        self.t = 0.0
        self.shake = 0.0
        self.flash = 0.0
        self.particles.clear()
        self.rings.clear()
        self.new_record = False

    def _toggle_pause(self):
        if self.model.state == State.RUNNING:
            self.model.state = State.PAUSED
        elif self.model.state == State.PAUSED:
            self.model.state = State.RUNNING
            self._last = time.perf_counter()

    def _on_death(self):
        self.shake = SHAKE_TIME
        self.flash = 0.35
        self.audio.play("hit")
        self._schedule(200, lambda: self.audio.play("game_over"))
        self._commit_high_score()

    def _on_victory(self):
        self.audio.play("level_up")
        self._commit_high_score()

    def _commit_high_score(self):
        if self.model.score > self.high_store.value:
            self.high_store.save(self.model.score)
            self.highscore = self.model.score
            self.new_record = True

    # -- logic tick ---------------------------------------------------------
    def _tick(self):
        food_before = self.model.food
        level_before = self.model.level
        event = self.model.step()

        if event == "eat":
            self.audio.play("eat")
            if food_before is not None:
                cx = PLAY_X + (food_before[0] + 0.5) * CELL
                cy = PLAY_Y + (food_before[1] + 0.5) * CELL
                self._spawn_particles(cx, cy)
            if self.model.level > level_before:
                self._schedule(120, lambda: self.audio.play("level_up"))
        elif event == "death":
            self._on_death()
        elif event == "win":
            self._on_victory()

    # -- particles ----------------------------------------------------------
    def _spawn_particles(self, x, y):
        for _ in range(16):
            angle = self.rng.uniform(0, math.tau)
            speed = self.rng.uniform(60, 220)
            self.particles.append(
                {
                    "x": x,
                    "y": y,
                    "vx": math.cos(angle) * speed,
                    "vy": math.sin(angle) * speed,
                    "life": 0.55,
                    "max": 0.55,
                    "size": self.rng.uniform(2.5, 5.5),
                    "color": self.rng.choice([COL_FOOD, COL_GOLD, "#FFB4A2", "#FFFFFF"]),
                }
            )
        self.rings.append({"x": x, "y": y, "life": 0.45, "max": 0.45, "rmax": CELL * 2.2})

    def _update_particles(self, dt):
        alive = []
        for p in self.particles:
            p["life"] -= dt
            if p["life"] <= 0:
                continue
            p["x"] += p["vx"] * dt
            p["y"] += p["vy"] * dt
            dump = 1.0 - 5.0 * dt
            if dump < 0.0:
                dump = 0.0
            p["vx"] *= dump
            p["vy"] *= dump
            p["vy"] += 190.0 * dt  # slight gravity
            alive.append(p)
        self.particles = alive

        rings = []
        for r in self.rings:
            r["life"] -= dt
            if r["life"] > 0:
                rings.append(r)
        self.rings = rings

    # -- main loop ----------------------------------------------------------
    def _frame(self):
        now = time.perf_counter()
        dt = now - self._last
        self._last = now
        if dt < 0:
            dt = 0.0
        if dt > 0.1:
            dt = 0.1

        self._update(dt)
        self._render()
        self.frames_rendered += 1

    def _update(self, dt):
        # Food / world animation freezes while paused; the pause overlay uses
        # blink_phase so it still shimmers for polish.
        if self.model.state != State.PAUSED:
            self.anim_phase += dt
        self.blink_phase += dt

        if self.shake > 0:
            self.shake = max(0.0, self.shake - dt)
        if self.flash > 0:
            self.flash = max(0.0, self.flash - dt)

        self._update_particles(dt)

        if self.model.state == State.RUNNING:
            self.accum += dt
            guard = 0
            while guard < 5:
                interval = self.model.tick_interval
                if self.accum < interval:
                    break
                self.accum -= interval
                self._tick()
                guard += 1
                if self.model.state != State.RUNNING:
                    self.accum = 0.0
                    break
            if self.model.state == State.RUNNING:
                interval = self.model.tick_interval
                self.t = self.accum / interval if interval > 0 else 0.0
                if self.t > 1.0:
                    self.t = 1.0
            else:
                self.t = 1.0

    def _loop(self):
        self.after_id = None
        if self.closing:
            return
        start = time.perf_counter()
        if self._last_loop is not None:
            period = start - self._last_loop
            err_ms = (self._frame_budget - period) * 1000.0
            self._sched_ms = min(40.0, max(1.0, self._sched_ms + err_ms * 0.25))
        self._last_loop = start
        try:
            self._frame()
        except Exception:
            traceback.print_exc()
        if not self.closing:
            self.after_id = self.root.after(int(round(self._sched_ms)), self._loop)

    # ======================================================================
    # Rendering
    # ======================================================================
    def _draw_static(self):
        c = self.canvas
        c.delete("static")

        # HUD panel
        c.create_rectangle(0, 0, WINDOW_W, HUD_H, fill=COL_PANEL, outline="", tags="static")
        c.create_rectangle(0, 0, 6, HUD_H, fill=COL_ACCENT, outline="", tags="static")
        c.create_line(0, HUD_H, WINDOW_W, HUD_H, fill=COL_GRID, width=2, tags="static")

        # Checkerboard playfield
        for y in range(ROWS):
            for x in range(COLS):
                color = COL_CHECK_A if (x + y) % 2 == 0 else COL_CHECK_B
                px = PLAY_X + x * CELL
                py = PLAY_Y + y * CELL
                c.create_rectangle(px, py, px + CELL, py + CELL, fill=color, outline="", tags="static")

        # Subtle grid lines
        for x in range(COLS + 1):
            gx = PLAY_X + x * CELL
            c.create_line(gx, PLAY_Y, gx, PLAY_Y + PLAY_H, fill=COL_GRID, tags="static")
        for y in range(ROWS + 1):
            gy = PLAY_Y + y * CELL
            c.create_line(PLAY_X, gy, PLAY_X + PLAY_W, gy, fill=COL_GRID, tags="static")

        # Playfield border
        c.create_rectangle(
            PLAY_X + 1, PLAY_Y + 1, PLAY_X + PLAY_W - 1, PLAY_Y + PLAY_H - 1,
            outline=COL_BORDER, width=2, tags="static",
        )

    def _pulse_color(self, c1, c2, speed=3.0, phase_offset=0.0, phase=None):
        ph = self.anim_phase if phase is None else phase
        v = 0.5 + 0.5 * math.sin(ph * speed + phase_offset)
        return lerp_color(c1, c2, v)

    def _render(self):
        c = self.canvas
        c.delete("ui")
        ox, oy = self._shake_offset()
        state = self.model.state

        if state != State.START:
            self._draw_food(ox, oy)
            self._draw_particles(ox, oy)
            self._draw_snake(ox, oy)

        if self.flash > 0:
            stipple = "gray50" if self.flash > 0.18 else "gray25"
            c.create_rectangle(
                PLAY_X, PLAY_Y, PLAY_X + PLAY_W, PLAY_Y + PLAY_H,
                fill=COL_DANGER, outline="", stipple=stipple, tags="ui",
            )

        if state == State.START:
            self._draw_start_overlay()
        elif state == State.PAUSED:
            self._draw_pause_overlay()
        elif state == State.GAME_OVER:
            self._draw_gameover_overlay()
        elif state == State.VICTORY:
            self._draw_victory_overlay()

        self._draw_hud()

    def _shake_offset(self):
        if self.shake <= 0:
            return 0.0, 0.0
        amp = 9.0 * (self.shake / SHAKE_TIME)
        return self.rng.uniform(-amp, amp), self.rng.uniform(-amp, amp)

    def _draw_snake(self, ox, oy):
        c = self.canvas
        body = self.model.body
        prev = self.model.prev_body
        t = self.t
        n = len(body)
        if n == 0:
            return

        pts = []
        for i, (cx, cy) in enumerate(body):
            if i < len(prev):
                px, py = prev[i]
            else:
                px, py = prev[-1]
            x = PLAY_X + (px + (cx - px) * t + 0.5) * CELL + ox
            y = PLAY_Y + (py + (cy - py) * t + 0.5) * CELL + oy
            pts.append((x, y))

        # Body: thick round-capped segments from tail to head (head on top).
        for i in range(n - 1, 0, -1):
            f = i / (n - 1) if n > 1 else 0.0
            color = lerp_color(COL_BODY_HEAD, COL_BODY_TAIL, f)
            width = CELL * 0.80 * (1.0 - 0.22 * f)
            c.create_line(
                pts[i][0], pts[i][1], pts[i - 1][0], pts[i - 1][1],
                fill=color, width=width, capstyle=tk.ROUND, joinstyle=tk.ROUND,
                tags="ui",
            )

        # Head
        hx, hy = pts[0]
        r = CELL * 0.50
        glow = lerp_color(COL_HEAD, "#FFFFFF", 0.25)
        c.create_oval(hx - r, hy - r, hx + r, hy + r, fill=COL_HEAD, outline=glow, width=2, tags="ui")

        dx, dy = self.model.direction
        perp = (-dy, dx)
        for sign in (-1, 1):
            ex = hx + dx * CELL * 0.13 + perp[0] * sign * CELL * 0.20
            ey = hy + dy * CELL * 0.13 + perp[1] * sign * CELL * 0.20
            er = CELL * 0.15
            c.create_oval(ex - er, ey - er, ex + er, ey + er, fill="#EAF7FF", outline="", tags="ui")
            pr = CELL * 0.075
            ppx = ex + dx * CELL * 0.05
            ppy = ey + dy * CELL * 0.05
            c.create_oval(ppx - pr, ppy - pr, ppx + pr, ppy + pr, fill="#0B1220", outline="", tags="ui")

    def _draw_food(self, ox, oy):
        c = self.canvas
        food = self.model.food
        if food is None:
            return
        fx = PLAY_X + (food[0] + 0.5) * CELL + ox
        fy = PLAY_Y + (food[1] + 0.5) * CELL + oy
        pulse = 1.0 + 0.10 * math.sin(self.anim_phase * 6.0)
        r = CELL * 0.30 * pulse

        c.create_oval(fx - r * 1.75, fy - r * 1.75, fx + r * 1.75, fy + r * 1.75,
                      outline=COL_FOOD_GLOW, width=2, tags="ui")
        c.create_oval(fx - r * 1.40, fy - r * 1.40, fx + r * 1.40, fy + r * 1.40,
                      outline=COL_FOOD_DARK, width=2, tags="ui")
        c.create_oval(fx - r, fy - r, fx + r, fy + r,
                      fill=COL_FOOD, outline="#FFB4A2", width=2, tags="ui")

        # Stem + leaf
        c.create_line(fx, fy - r * 0.85, fx + r * 0.18, fy - r * 1.5,
                      fill="#8B5E34", width=3, capstyle=tk.ROUND, tags="ui")
        lx = fx + r * 0.18
        ly = fy - r * 1.5
        c.create_oval(lx - r * 0.35, ly - r * 0.22, lx + r * 0.35, ly + r * 0.22,
                      fill=COL_LEAF, outline="", tags="ui")

        # Highlight
        hr = r * 0.30
        c.create_oval(fx - r * 0.45 - hr, fy - r * 0.45 - hr, fx - r * 0.45 + hr, fy - r * 0.45 + hr,
                      fill="#FFD8D0", outline="", tags="ui")

    def _draw_particles(self, ox, oy):
        c = self.canvas
        for r in self.rings:
            frac = 1.0 - (r["life"] / r["max"])
            rad = r["rmax"] * frac
            color = lerp_color("#FFB4A2", COL_BG, frac)
            c.create_oval(r["x"] - rad + ox, r["y"] - rad + oy, r["x"] + rad + ox, r["y"] + rad + oy,
                          outline=color, width=3, tags="ui")
        for p in self.particles:
            frac = p["life"] / p["max"]
            size = p["size"] * frac
            if size < 0.6:
                continue
            color = lerp_color(COL_BG, p["color"], frac)
            c.create_oval(p["x"] - size + ox, p["y"] - size + oy,
                          p["x"] + size + ox, p["y"] + size + oy,
                          fill=color, outline="", tags="ui")

    def _dim(self, fill, stipple="gray50"):
        self.canvas.create_rectangle(
            PLAY_X, PLAY_Y, PLAY_X + PLAY_W, PLAY_Y + PLAY_H,
            fill=fill, outline="", stipple=stipple, tags="ui",
        )

    def _draw_start_overlay(self):
        c = self.canvas
        self._dim(COL_BG, "gray50")

        cx = WINDOW_W / 2.0
        title = "SNAKE"
        # Per-letter animated bob, centred using measured widths.
        widths = [self.font_title.measure(ch) for ch in title]
        total = sum(widths)
        x = cx - total / 2.0
        top = PLAY_Y + PLAY_H * 0.24
        for i, ch in enumerate(title):
            bob = math.sin(self.anim_phase * 2.2 + i * 0.7) * 7.0
            col = self._pulse_color(COL_HEAD, COL_PURPLE, 2.2, i * 0.5)
            c.create_text(x + widths[i] / 2.0, top + bob, text=ch, fill=col,
                          font=self.font_title, tags="ui")
            x += widths[i]

        c.create_text(cx, top + 78, text="A N I M A T E D   P Y T H O N",
                      fill=COL_TEXT_DIM, font=self.font_med, tags="ui")

        prompt_col = self._pulse_color(COL_TEXT, COL_TEXT_DIM, 4.0)
        c.create_text(cx, top + 170, text="PRESS  ENTER  OR  SPACE  TO  START",
                      fill=prompt_col, font=self.font_med, tags="ui")

        c.create_text(cx, PLAY_Y + PLAY_H - 92,
                      text="ARROWS / WASD  -  MOVE        P  -  PAUSE",
                      fill=COL_TEXT_DIM, font=self.font_small, tags="ui")
        c.create_text(cx, PLAY_Y + PLAY_H - 66,
                      text="M  -  MUTE        - / +  -  VOLUME        ESC  -  QUIT",
                      fill=COL_TEXT_DIM, font=self.font_small, tags="ui")

        if not self.audio.available:
            c.create_text(cx, PLAY_Y + PLAY_H - 34, text="Audio unavailable",
                          fill=COL_DANGER, font=self.font_small, tags="ui")

    def _draw_pause_overlay(self):
        c = self.canvas
        self._dim(COL_BG, "gray50")
        cx = WINDOW_W / 2.0
        cy = PLAY_Y + PLAY_H / 2.0
        col = self._pulse_color(COL_ACCENT, COL_PURPLE, 3.0, phase=self.blink_phase)
        c.create_text(cx, cy - 20, text="PAUSED", fill=col, font=self.font_big, tags="ui")
        c.create_text(cx, cy + 40, text="Press P to resume",
                      fill=COL_TEXT, font=self.font_small, tags="ui")

    def _draw_gameover_overlay(self):
        c = self.canvas
        self._dim("#1A0A12", "gray50")
        cx = WINDOW_W / 2.0
        top = PLAY_Y + PLAY_H * 0.24
        reason = "Hit the wall" if self.model.death_reason == "wall" else "Ate yourself"
        c.create_text(cx, top, text="GAME OVER", fill=COL_DANGER, font=self.font_big, tags="ui")
        c.create_text(cx, top + 46, text=reason, fill=COL_TEXT_DIM, font=self.font_small, tags="ui")
        c.create_text(cx, top + 100, text="SCORE   %d" % self.model.score,
                      fill=COL_TEXT, font=self.font_med, tags="ui")
        c.create_text(cx, top + 132, text="HIGH    %d" % self.highscore,
                      fill=COL_TEXT, font=self.font_med, tags="ui")
        if self.new_record:
            glow = self._pulse_color(COL_GOLD, "#FFFFFF", 6.0)
            c.create_text(cx, top + 172, text="NEW HIGH SCORE!",
                          fill=glow, font=self.font_med, tags="ui")
        prompt_col = self._pulse_color(COL_TEXT, COL_TEXT_DIM, 4.0)
        c.create_text(cx, top + 226, text="Press ENTER to play again",
                      fill=prompt_col, font=self.font_small, tags="ui")

    def _draw_victory_overlay(self):
        c = self.canvas
        self._dim("#0A1A12", "gray50")
        cx = WINDOW_W / 2.0
        top = PLAY_Y + PLAY_H * 0.26
        c.create_text(cx, top, text="YOU WIN!", fill=COL_GOLD, font=self.font_big, tags="ui")
        c.create_text(cx, top + 50, text="The board is full - perfect snake!",
                      fill=COL_TEXT_DIM, font=self.font_small, tags="ui")
        c.create_text(cx, top + 104, text="FINAL SCORE   %d" % self.model.score,
                      fill=COL_TEXT, font=self.font_med, tags="ui")
        if self.new_record:
            c.create_text(cx, top + 144, text="NEW HIGH SCORE!", fill=COL_GOLD,
                          font=self.font_med, tags="ui")
        c.create_text(cx, top + 200, text="Press ENTER to play again",
                      fill=COL_TEXT, font=self.font_small, tags="ui")

    def _draw_hud(self):
        c = self.canvas
        model = self.model
        display_high = max(self.highscore, model.score)

        def stat(x, label, value, value_color=COL_TEXT):
            c.create_text(x, 14, text=label, anchor="w", fill=COL_TEXT_DIM,
                          font=self.font_hud_label, tags="ui")
            c.create_text(x, 34, text=value, anchor="w", fill=value_color,
                          font=self.font_hud, tags="ui")

        stat(24, "SCORE", "%d" % model.score, COL_HEAD)
        stat(190, "HIGH", "%d" % display_high, COL_GOLD)
        stat(340, "LEVEL", "%d" % model.level, COL_TEXT)
        stat(470, "SPEED", "x%.1f" % model.speed_multiplier, COL_ACCENT)

        if not self.audio.available:
            vol_value, vol_col = "--", COL_TEXT_DIM
        elif self.audio.muted:
            vol_value, vol_col = "MUTE", COL_TEXT_DIM
        else:
            vol_value, vol_col = "%d" % self.audio.volume, COL_LEAF
        stat(600, "VOL", vol_value, vol_col)

        # Right hand status
        if not self.audio.available:
            status = "AUDIO OFF"
            col = COL_DANGER
        elif self.audio.muted:
            status = "SOUND: MUTED"
            col = COL_TEXT_DIM
        else:
            status = "SOUND: ON"
            col = COL_LEAF
        c.create_text(WINDOW_W - 20, 40, text="M  " + status, anchor="e", fill=col,
                      font=self.font_hud_label, tags="ui")
        c.create_text(WINDOW_W - 20, 12, text="-/+  VOLUME", anchor="e",
                      fill=COL_TEXT_DIM, font=self.font_hud_label, tags="ui")

    # -- run / shutdown -----------------------------------------------------
    def run(self):
        self._last = time.perf_counter()
        self.after_id = self.root.after(FRAME_MS, self._loop)
        self.root.mainloop()

    def close(self):
        if self.closing:
            return
        self.closing = True
        self._cancel_pending()
        if self.after_id is not None:
            try:
                self.root.after_cancel(self.after_id)
            except Exception:
                pass
            self.after_id = None
        try:
            self.audio.close()
        except Exception:
            pass
        try:
            self.root.destroy()
        except Exception:
            pass


# ===========================================================================
# Self test
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
    print("Snake %s - self test" % __version__)
    print("Python %s on %s" % (sys.version.split()[0], sys.platform))
    print("=" * 68)

    # -- 1. imports ---------------------------------------------------------
    check("standard library imports", True)
    check("tkinter imported", tk is not None, str(_TK_IMPORT_ERROR))

    # -- 2. audio -----------------------------------------------------------
    audio = AudioEngine()
    if audio.available:
        check("audio engine initialised", True, "backend=%s" % audio.backend)
        data = samples_to_wav_bytes(build_sound_bank()["eat"], 70)
        check("WAV generation produces data", len(data) > 44, "%d bytes" % len(data))
        # Verify the WAV header is well formed.
        with wave.open(io.BytesIO(data), "rb") as w:
            check("WAV is mono 16-bit 44100Hz",
                  w.getnchannels() == 1 and w.getsampwidth() == 2
                  and w.getframerate() == SAMPLE_RATE)
        audio.play("eat")
        time.sleep(0.05)
    else:
        check("audio engine graceful fallback (non-fatal)", True,
              "unavailable: %s" % audio.error)
    audio.close()

    # -- 3. reversal prevention --------------------------------------------
    m = GameModel()
    m.state = State.RUNNING
    m.spawn_food()
    m.direction = RIGHT
    rejected = m.queue_direction(LEFT) is False
    check("snake cannot reverse into itself", rejected)
    check("valid turn is queued", m.queue_direction(UP) is True)
    # Fill the buffer and confirm it is capped.
    m.queue_direction(LEFT)
    m.queue_direction(DOWN)
    check("input buffer is bounded", len(m.dir_queue) <= MAX_QUEUED_TURNS,
          "len=%d" % len(m.dir_queue))

    # -- 4. food never spawns on the snake ---------------------------------
    clean = True
    for _ in range(400):
        mm = GameModel(rng=random.Random(_))
        if not mm.spawn_food():
            clean = False
            break
        if mm.food in mm.body:
            clean = False
            break
    check("food spawns only on empty cells", clean)

    # -- 5. wall collision --------------------------------------------------
    m = GameModel()
    m.state = State.RUNNING
    m.body = [(COLS - 1, 5), (COLS - 2, 5), (COLS - 3, 5)]
    m.prev_body = list(m.body)
    m.direction = RIGHT
    m.spawn_food()
    ev = m.step()
    check("wall collision detected",
          ev == "death" and m.state == State.GAME_OVER and m.death_reason == "wall")

    # -- 6. self collision --------------------------------------------------
    m = GameModel()
    m.state = State.RUNNING
    m.body = [(3, 3), (2, 3), (2, 4), (3, 4), (4, 4), (4, 3)]
    m.prev_body = list(m.body)
    m.direction = DOWN  # -> (3, 4) which is body[3]
    m.spawn_food()
    ev = m.step()
    check("self collision detected",
          ev == "death" and m.state == State.GAME_OVER and m.death_reason == "self")

    # -- 7. fair-play tail rule --------------------------------------------
    m = GameModel()
    m.state = State.RUNNING
    m.body = [(5, 5), (6, 5), (6, 6), (5, 6)]  # head (5,5); tail (5,6)
    m.prev_body = list(m.body)
    m.direction = DOWN  # -> (5, 6) the tail cell, which vacates this tick
    m.food = None
    ev = m.step()
    check("moving into vacating tail is allowed (not a death)", ev == "none",
          "ev=%s" % ev)

    # -- 8. eating increases score and length ------------------------------
    m = GameModel()
    m.state = State.RUNNING
    m.direction = RIGHT
    m.food = (m.head[0] + 1, m.head[1])
    before_len = len(m.body)
    before_score = m.score
    ev = m.step()
    check("eating food grows snake and scores",
          ev == "eat" and len(m.body) == before_len + 1
          and m.score == before_score + SCORE_PER_APPLE)

    # -- 9. level / speed progression --------------------------------------
    m = GameModel()
    m.state = State.RUNNING
    m.direction = RIGHT
    start_interval = m.tick_interval
    for _ in range(APPLES_PER_LEVEL):
        m.food = (m.head[0] + 1, m.head[1])
        m.step()
    check("level increases every %d apples" % APPLES_PER_LEVEL, m.level == 2,
          "level=%d" % m.level)
    check("speed increases with level", m.tick_interval < start_interval,
          "%.3f -> %.3f" % (start_interval, m.tick_interval))
    check("speed floor respected", GameModel().tick_interval >= TICK_MIN)

    # -- 10. high score file -----------------------------------------------
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "hs.txt")
        store = HighScoreStore(path)
        saved = store.save(1234)
        reloaded = HighScoreStore(path)
        check("high score saves and reloads", saved and reloaded.value == 1234,
              "got %d" % reloaded.value)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("not-a-number")
        check("corrupt high score file is handled", HighScoreStore(path).value == 0)
        missing = HighScoreStore(os.path.join(d, "does_not_exist.txt"))
        check("missing high score file returns 0", missing.value == 0)

    # -- 11. victory detection ---------------------------------------------
    m = GameModel(cols=3, rows=1)
    m.state = State.RUNNING
    m.body = [(1, 0), (0, 0)]
    m.prev_body = list(m.body)
    m.direction = RIGHT
    m.food = (2, 0)
    ev = m.step()  # eats the final free cell -> board full -> victory
    check("board-full victory detected", ev == "win" and m.state == State.VICTORY,
          "ev=%s" % ev)

    # -- 12. GUI smoke test -------------------------------------------------
    if tk is None:
        check("GUI smoke test", True, "skipped - tkinter unavailable")
    else:
        gui_ok, gui_detail = _gui_selftest()
        if gui_ok is None:
            check("GUI smoke test", True, "skipped - %s" % gui_detail)
        else:
            check("GUI smoke test (window, frames, input, pause, death, high-score save)",
                  gui_ok, gui_detail)

    # -- summary ------------------------------------------------------------
    passed = sum(1 for _, ok, _ in results if ok)
    total = len(results)
    print("-" * 68)
    print("Checks: %d/%d passed" % (passed, total))
    overall = passed == total
    print("SELF-TEST: %s" % ("PASS" if overall else "FAIL"))
    print("=" * 68)
    return 0 if overall else 1


def _gui_selftest():
    """Open a real window, drive a few frames, then close cleanly."""
    try:
        probe = tk.Tk()
        probe.destroy()
    except Exception as exc:
        return None, "no display (%s)" % exc

    app = None
    try:
        with tempfile.TemporaryDirectory() as d:
            hs_path = os.path.join(d, "hs.txt")
            app = SnakeApp(highscore_path=hs_path, muted=True)
            app._start_game()
            for _ in range(6):
                app._frame()
                app.root.update()

            assert app.model.state == State.RUNNING

            # Direction change through the public input path.
            assert app._queue_dir(UP) is True
            app._frame()
            app.root.update()
            app._tick()
            assert app.model.direction == UP

            # Pause / resume.
            app._toggle_pause()
            app._frame()
            app.root.update()
            assert app.model.state == State.PAUSED
            app._toggle_pause()
            assert app.model.state == State.RUNNING

            # Eating path drives particles + score.
            ddx, ddy = app.model.direction
            app.model.food = (app.model.head[0] + ddx, app.model.head[1] + ddy)
            app._tick()
            assert app.model.score >= SCORE_PER_APPLE
            assert len(app.particles) > 0
            app._frame()
            app.root.update()

            # Force a wall death and render the game over screen.
            app.model.body = [(COLS - 1, 5), (COLS - 2, 5), (COLS - 3, 5)]
            app.model.prev_body = list(app.model.body)
            app.model.direction = RIGHT
            app._tick()
            assert app.model.state == State.GAME_OVER
            app._frame()
            app.root.update()
            final_score = app.model.score

            # Restart from game over.
            app._start_game()
            assert app.model.state == State.RUNNING
            app._frame()
            app.root.update()

            app.close()

            # The app must have persisted the score on death.
            saved = HighScoreStore(hs_path).value
            assert saved == final_score, "saved %d != score %d" % (saved, final_score)
        return True, "ok (score %d persisted)" % final_score
    except Exception:
        if app is not None:
            try:
                app.close()
            except Exception:
                pass
        return False, traceback.format_exc()


# ===========================================================================
# Entry point
# ===========================================================================

def main(argv=None) -> int:
    argv = list(sys.argv[1:]) if argv is None else list(argv)

    if "--self-test" in argv or "-t" in argv:
        return run_self_test()

    if "--help" in argv or "-h" in argv:
        print(APP_NAME)
        print("Usage: python snake.py [--self-test]")
        print("  --self-test   run the built-in verification suite")
        return 0

    muted = "--mute" in argv

    if tk is None:  # pragma: no cover
        print("ERROR: Tkinter is not available in this Python: %s" % _TK_IMPORT_ERROR)
        return 2

    app = None
    try:
        app = SnakeApp(muted=muted)
        app.run()
        return 0
    except KeyboardInterrupt:
        if app is not None:
            app.close()
        return 0
    except Exception:
        traceback.print_exc()
        if app is not None:
            try:
                app.close()
            except Exception:
                pass
        return 1


if __name__ == "__main__":
    sys.exit(main())
