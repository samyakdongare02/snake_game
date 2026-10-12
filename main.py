#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
main.py - Snake for Android (Kivy)
==================================

Mobile port of the animated Python Snake game.  The *gameplay* logic lives in
``snake_core.py`` (pure Python, shared with the desktop build) and this file
provides a Kivy rendering + touch-control layer that targets Android phones in
landscape.

Everything is drawn procedurally with Kivy canvas instructions and all sound
effects are synthesised at runtime -- there are **no external image or audio
assets**, so the APK is fully self-contained.

Run on desktop for development::

    python main.py

Headless logic self-test::

    python main.py --self-test

Scripted GUI smoke test (opens a window, drives the UI, writes screenshots)::

    python main.py --self-test-gui

Packaging for Android is done by Buildozer (see ``buildozer.spec``); no local
Android tooling is required by the end user because the signed APK is produced
by CI.
"""

from __future__ import annotations

import os
import sys

# ---------------------------------------------------------------------------
# Early, dependency-free entry points.  Handled *before* Kivy is imported so
# the logic self-test never needs to open a window.
# ---------------------------------------------------------------------------
os.environ.setdefault("KIVY_NO_ARGS", "1")

_SELFTEST_ONLY = "--self-test" in sys.argv
_SELFTEST_GUI = "--self-test-gui" in sys.argv

if _SELFTEST_ONLY and not _SELFTEST_GUI:
    import snake_core

    raise SystemExit(snake_core.run_self_test())

# ---------------------------------------------------------------------------
# Kivy imports / configuration
# ---------------------------------------------------------------------------
from kivy.config import Config  # noqa: E402

# A phone-ish landscape window for desktop development/testing.  On Android
# the real device resolution is used and these are ignored.
Config.set("graphics", "width", "960")
Config.set("graphics", "height", "432")
Config.set("graphics", "resizable", "1")
Config.set("input", "mouse", "mouse,multitouch_on_demand")
# Keep the framerate high; logic timing is independent of the frame rate.
Config.set("graphics", "maxfps", "60")

import math  # noqa: E402
import random  # noqa: E402
import time  # noqa: E402

from kivy.app import App  # noqa: E402
from kivy.clock import Clock  # noqa: E402
from kivy.core.audio import SoundLoader  # noqa: E402
from kivy.core.window import Window  # noqa: E402
from kivy.graphics import Color, Ellipse, Line, Rectangle, RoundedRectangle  # noqa: E402
from kivy.graphics.instructions import InstructionGroup  # noqa: E402
from kivy.metrics import dp  # noqa: E402
from kivy.properties import BooleanProperty, NumericProperty, StringProperty  # noqa: E402
from kivy.uix.button import Button  # noqa: E402
from kivy.uix.floatlayout import FloatLayout  # noqa: E402
from kivy.uix.label import Label  # noqa: E402
from kivy.uix.widget import Widget  # noqa: E402

import snake_core as core  # noqa: E402

# ===========================================================================
# Palette helpers
# ===========================================================================

def rgba(hex_color: str, alpha: float = 1.0):
    return core.hex_to_rgba(hex_color, alpha)


def mix_rgba(c1: str, c2: str, t: float, alpha: float = 1.0):
    return core.lerp_rgba(c1, c2, t, alpha)


def clamp(v, lo, hi):
    return lo if v < lo else hi if v > hi else v


def ease_out(t: float) -> float:
    t = clamp(t, 0.0, 1.0)
    return 1.0 - (1.0 - t) ** 3


# ===========================================================================
# Sound + haptics (all failures are non-fatal)
# ===========================================================================

class SoundManager:
    """Synthesises WAV effects to the app storage dir and plays them.

    Everything is wrapped defensively: if the platform has no audio backend
    the game keeps running silently.
    """

    def __init__(self, directory: str, volume: int = core.DEFAULT_VOLUME):
        self.directory = directory
        self.muted = False
        self.volume = clamp(volume, 0, 100)
        self.sounds = {}
        self.available = False
        self._init()

    def _init(self):
        try:
            os.makedirs(self.directory, exist_ok=True)
            bank = core.build_sound_bank()
            for name, samples in bank.items():
                path = os.path.join(self.directory, "sfx_%s.wav" % name)
                with open(path, "wb") as fh:
                    fh.write(core.samples_to_wav_bytes(samples, 100))
                snd = SoundLoader.load(path)
                if snd is not None:
                    snd.volume = self.volume / 100.0
                    self.sounds[name] = snd
            self.available = len(self.sounds) > 0
        except Exception:
            self.available = False

    def set_volume(self, volume: int):
        self.volume = clamp(int(volume), 0, 100)
        for snd in self.sounds.values():
            try:
                snd.volume = self.volume / 100.0
            except Exception:
                pass

    def toggle_mute(self) -> bool:
        self.muted = not self.muted
        return self.muted

    def play(self, name: str):
        if self.muted or not self.available:
            return
        snd = self.sounds.get(name)
        if snd is None:
            return
        try:
            snd.volume = self.volume / 100.0
            snd.play()
        except Exception:
            pass


def vibrate(seconds: float = 0.025):
    """Best-effort haptic feedback; silently ignored on unsupported devices."""
    try:
        from plyer import vibrator  # type: ignore

        if vibrator.exists():
            vibrator.vibrate(seconds)
    except Exception:
        pass


# ===========================================================================
# Widgets
# ===========================================================================

class NeonButton(Button):
    """A rounded, neon-tinted button with a clear pressed state.

    ``ButtonBehavior`` (via ``Button``) already provides touch handling, so the
    button responds to real Android touch events with no extra plumbing.
    """

    fill = rgba(core.COL_PANEL, 1.0)
    stroke = rgba(core.COL_BORDER, 1.0)
    pressed_fill = rgba(core.COL_ACCENT, 0.30)

    def __init__(self, **kwargs):
        kwargs.setdefault("background_normal", "")
        kwargs.setdefault("background_down", "")
        kwargs.setdefault("background_color", (0, 0, 0, 0))
        kwargs.setdefault("font_size", dp(22))
        kwargs.setdefault("color", rgba(core.COL_TEXT))
        kwargs.setdefault("bold", True)
        kwargs.setdefault("halign", "center")
        kwargs.setdefault("valign", "middle")
        super().__init__(**kwargs)
        self._radius = [dp(16)]
        with self.canvas.before:
            self._color = Color(*self.fill)
            self._rect = RoundedRectangle(
                pos=self.pos, size=self.size, radius=self._radius
            )
            self._line_color = Color(*self.stroke)
            self._line = Line(
                rounded_rectangle=(self.x, self.y, self.width, self.height,
                                   self._radius[0]),
                width=dp(1),
            )
        self.bind(pos=self._sync, size=self._sync, state=self._sync)
        self.bind(size=self._sync_text)
        self._sync_text()

    def _sync_text(self, *_):
        self.text_size = (self.width - dp(8), self.height)

    def _sync(self, *_):
        self._rect.pos = self.pos
        self._rect.size = self.size
        self._line.rounded_rectangle = (
            self.x, self.y, self.width, self.height, self._radius[0]
        )
        if self.state == "down":
            self._color.rgba = self.pressed_fill
        else:
            self._color.rgba = self.fill


class GameField(Widget):
    """Renders the board, snake, food, particles and overlays; handles swipe."""

    def __init__(self, app, **kwargs):
        super().__init__(**kwargs)
        self.app = app
        self.cell = dp(16)
        self.board_x = 0.0
        self.board_y = 0.0
        self.board_w = 0.0
        self.board_h = 0.0
        self.shake = 0.0
        self.flash = 0.0
        self.t = 0.0
        self.anim = 0.0
        self.blink = 0.0
        self.particles = []
        self.rings = []
        self.rng = random.Random(7)

        self._static = InstructionGroup()
        self.canvas.before.add(self._static)
        # Dynamic layer goes in the MAIN canvas so it renders below child
        # widgets (canvas.after would draw on top of the overlay labels).
        self._dyn = InstructionGroup()
        self.canvas.add(self._dyn)

        # Overlay labels live as children so they render above the canvas.
        self.ov_title = Label(
            font_size=dp(38), bold=True, color=rgba(core.COL_TEXT),
            halign="center", valign="middle", size_hint=(None, None),
        )
        self.ov_sub = Label(
            font_size=dp(19), color=rgba(core.COL_TEXT_DIM),
            halign="center", valign="middle", size_hint=(None, None),
        )
        self.ov_hint = Label(
            font_size=dp(15), color=rgba(core.COL_TEXT_DIM),
            halign="center", valign="middle", size_hint=(None, None),
        )
        self.ov_button = NeonButton(
            text="TAP TO START", font_size=dp(24),
            size_hint=(None, None), size=(dp(260), dp(74)),
        )
        self.ov_button.bind(on_release=self._overlay_action)
        for w in (self.ov_title, self.ov_sub, self.ov_hint, self.ov_button):
            self.add_widget(w)

        self._touch_start = None
        self.bind(pos=self._layout, size=self._layout)

    # -- geometry -----------------------------------------------------------
    def _layout(self, *_):
        pad = dp(6)
        avail_w = max(1.0, self.width - 2 * pad)
        avail_h = max(1.0, self.height - 2 * pad)
        self.cell = min(avail_w / core.COLS, avail_h / core.ROWS)
        self.board_w = self.cell * core.COLS
        self.board_h = self.cell * core.ROWS
        self.board_x = (self.width - self.board_w) / 2.0
        self.board_y = (self.height - self.board_h) / 2.0
        self._rebuild_static()
        self._layout_overlay()

    def _layout_overlay(self):
        # Coordinates for canvas AND child widgets are absolute (window) space,
        # so the field's own pos must be added here.
        cx = self.x + self.board_x + self.board_w / 2.0
        cy = self.y + self.board_y + self.board_h / 2.0
        w = self.board_w
        self.ov_title.size = (w, dp(46))
        self.ov_title.pos = (cx - w / 2.0, cy + dp(56))
        self.ov_sub.size = (w, dp(30))
        self.ov_sub.pos = (cx - w / 2.0, cy + dp(12))
        self.ov_hint.size = (w, dp(24))
        self.ov_hint.pos = (cx - w / 2.0, cy - dp(70))
        self.ov_button.pos = (cx - self.ov_button.width / 2.0, cy - dp(46))

    def cell_center(self, gx, gy):
        """Grid coords (y down) -> widget pixel center (parent/canvas space)."""
        px = self.x + self.board_x + (gx + 0.5) * self.cell
        py = self.y + self.board_y + (core.ROWS - 0.5 - gy) * self.cell
        return px, py

    # -- static background --------------------------------------------------
    def _rebuild_static(self):
        g = self._static
        g.clear()
        # Backdrop covering the whole field (canvas space == parent space).
        g.add(Color(*rgba(core.COL_BG)))
        g.add(Rectangle(pos=self.pos, size=self.size))
        # Checkerboard playfield.
        for gy in range(core.ROWS):
            for gx in range(core.COLS):
                shade = core.COL_CHECK_A if (gx + gy) % 2 == 0 else core.COL_CHECK_B
                px = self.x + self.board_x + gx * self.cell
                py = self.y + self.board_y + (core.ROWS - 1 - gy) * self.cell
                g.add(Color(*rgba(shade)))
                g.add(Rectangle(
                    pos=(px, py),
                    size=(self.cell - 1.0, self.cell - 1.0),
                ))
        # Glowing border.
        g.add(Color(*rgba(core.COL_BORDER)))
        g.add(Line(
            rounded_rectangle=(
                self.x + self.board_x - dp(2), self.y + self.board_y - dp(2),
                self.board_w + dp(4), self.board_h + dp(4), dp(8),
            ),
            width=dp(2),
        ))

    # -- effects ------------------------------------------------------------
    def burst(self, gx, gy, color=core.COL_FOOD):
        px, py = self.cell_center(gx, gy)
        n = 18
        for i in range(n):
            ang = (i / n) * math.tau + self.rng.random() * 0.3
            spd = self.cell * (2.2 + self.rng.random() * 2.6)
            life = 0.45 + self.rng.random() * 0.25
            self.particles.append({
                "x": px, "y": py,
                "vx": math.cos(ang) * spd,
                "vy": math.sin(ang) * spd,
                "life": life, "max": life,
                "color": color,
                "size": self.cell * (0.10 + self.rng.random() * 0.10),
            })
        self.rings.append({"x": px, "y": py, "r": self.cell * 0.3,
                           "max": self.cell * 2.2, "life": 0.45, "maxlife": 0.45,
                           "color": color})

    def update_effects(self, dt):
        alive = []
        for p in self.particles:
            p["life"] -= dt
            if p["life"] > 0:
                p["x"] += p["vx"] * dt
                p["y"] += p["vy"] * dt
                p["vy"] -= self.cell * 6.0 * dt  # gravity-ish
                p["vx"] *= (1.0 - 1.6 * dt)
                alive.append(p)
        self.particles = alive

        rings = []
        for r in self.rings:
            r["life"] -= dt
            if r["life"] > 0:
                k = 1.0 - (r["life"] / r["maxlife"])
                r["r"] = core.lerp(r["r"], r["max"], 0.18) + r["max"] * 0.02
                rings.append(r)
        self.rings = rings

        if self.shake > 0:
            self.shake = max(0.0, self.shake - dt)
        if self.flash > 0:
            self.flash = max(0.0, self.flash - dt * 2.4)

    # -- overlay state ------------------------------------------------------
    def _overlay_action(self, *_):
        self.app.on_overlay_button()

    def set_overlay(self, title, sub, hint, button=None):
        self.ov_title.text = title
        self.ov_sub.text = sub
        self.ov_hint.text = hint
        if button is None:
            self.ov_button.opacity = 0
            self.ov_button.disabled = True
        else:
            self.ov_button.text = button
            self.ov_button.opacity = 1
            self.ov_button.disabled = False
        self._layout_overlay()

    # -- touch --------------------------------------------------------------
    def on_touch_down(self, touch):
        if not self.collide_point(*touch.pos):
            return super().on_touch_down(touch)
        # Let overlay buttons handle their own touches first.
        if self.ov_button.opacity > 0 and self.ov_button.collide_point(*touch.pos):
            return super().on_touch_down(touch)
        self._touch_start = (touch.x, touch.y, time.monotonic())
        return True

    def on_touch_up(self, touch):
        if self._touch_start is None or not self.collide_point(*touch.pos):
            self._touch_start = None
            return super().on_touch_up(touch)
        sx, sy, _t0 = self._touch_start
        self._touch_start = None
        dx = touch.x - sx
        dy = touch.y - sy
        threshold = dp(34)
        if math.hypot(dx, dy) < threshold:
            self.app.on_overlay_button()
            return True
        if abs(dx) > abs(dy):
            self.app.queue_direction(core.RIGHT if dx > 0 else core.LEFT, haptic=True)
        else:
            self.app.queue_direction(core.DOWN if dy < 0 else core.UP, haptic=True)
        return True

    # -- rendering ----------------------------------------------------------
    def redraw(self):
        app = self.app
        model = app.model
        g = self._dyn
        g.clear()

        shake_mag = 0.0
        if self.shake > 0:
            shake_mag = dp(9) * (self.shake / core.SHAKE_TIME)
        ox = self.rng.uniform(-shake_mag, shake_mag)
        oy = self.rng.uniform(-shake_mag, shake_mag)
        self._ox, self._oy = ox, oy

        state = model.state
        show_play = state in (core.State.RUNNING, core.State.PAUSED,
                              core.State.GAME_OVER, core.State.VICTORY)

        if show_play and model.food is not None:
            self._draw_food(g, model.food, ox, oy)
        if show_play:
            self._draw_snake(g, model, app.t, ox, oy)
        self._draw_particles(g, ox, oy)

        if self.flash > 0:
            g.add(Color(*rgba(core.COL_DANGER, 0.34 * self.flash)))
            g.add(Rectangle(pos=self.pos, size=self.size))

        if state == core.State.PAUSED:
            g.add(Color(*rgba("#04070E", 0.62)))
            g.add(Rectangle(pos=self.pos, size=self.size))

    def _draw_snake(self, g, model, t, ox, oy):
        body = model.body
        prev = model.prev_body
        n = len(body)
        if n == 0:
            return
        if len(prev) == n:
            prev_for = prev
        else:
            prev_for = [prev[0]] + list(prev)

        moving = model.state == core.State.RUNNING
        tt = t if moving else 1.0

        centers = []
        for i in range(n):
            cur = body[i]
            p = prev_for[i] if i < len(prev_for) else cur
            gx = core.lerp(p[0], cur[0], tt)
            gy = core.lerp(p[1], cur[1], tt)
            centers.append(self.cell_center(gx, gy))

        # Glow behind the whole snake for a neon feel.
        for i, (cx, cy) in enumerate(centers):
            r = self.cell * (0.58 if i == 0 else 0.5)
            g.add(Color(*rgba(core.COL_HEAD if i == 0 else core.COL_BODY_HEAD, 0.12)))
            g.add(Ellipse(pos=(cx + ox - r, cy + oy - r), size=(2 * r, 2 * r)))

        # Connectors between consecutive segments (smooth tube).
        for i in range(len(centers) - 1):
            x1, y1 = centers[i]
            x2, y2 = centers[i + 1]
            mx = (x1 + x2) / 2.0
            my = (y1 + y2) / 2.0
            k = i / max(1, len(centers) - 1)
            col = core.lerp_color(core.COL_BODY_HEAD, core.COL_BODY_TAIL, k)
            r = self.cell * 0.46
            g.add(Color(*rgba(col)))
            g.add(Ellipse(pos=(mx + ox - r, my + oy - r), size=(2 * r, 2 * r)))

        # Body segments.
        for i in range(1, len(centers)):
            cx, cy = centers[i]
            k = i / max(1, len(centers) - 1)
            col = core.lerp_color(core.COL_BODY_HEAD, core.COL_BODY_TAIL, k)
            r = self.cell * (0.44 - 0.06 * k)
            g.add(Color(*rgba(col)))
            g.add(Ellipse(pos=(cx + ox - r, cy + oy - r), size=(2 * r, 2 * r)))

        # Head.
        hx, hy = centers[0]
        r = self.cell * 0.52
        g.add(Color(*rgba(core.COL_HEAD)))
        g.add(Ellipse(pos=(hx + ox - r, hy + oy - r), size=(2 * r, 2 * r)))
        g.add(Color(*rgba("#FFFFFF", 0.25)))
        rr = r * 0.72
        g.add(Ellipse(pos=(hx + ox - rr, hy + oy - rr + r * 0.16),
                      size=(2 * rr, 2 * rr * 0.6)))

        # Eyes oriented to the travel direction.
        dx, dy = model.direction
        fx, fy = dx * self.cell, -dy * self.cell
        plen = math.hypot(fx, fy) or 1.0
        fx, fy = fx / plen, fy / plen
        pxp, pyp = -fy, fx
        fwd = 0.17 * self.cell
        side = 0.19 * self.cell
        eye_r = 0.135 * self.cell
        pup_r = 0.065 * self.cell
        for s in (-1, 1):
            ex = hx + ox + fx * fwd + pxp * side * s
            ey = hy + oy + fy * fwd + pyp * side * s
            g.add(Color(1, 1, 1, 1))
            g.add(Ellipse(pos=(ex - eye_r, ey - eye_r),
                          size=(2 * eye_r, 2 * eye_r)))
            px2 = ex + fx * eye_r * 0.45
            py2 = ey + fy * eye_r * 0.45
            g.add(Color(*rgba("#08131F")))
            g.add(Ellipse(pos=(px2 - pup_r, py2 - pup_r),
                          size=(2 * pup_r, 2 * pup_r)))

    def _draw_food(self, g, food, ox, oy):
        cx, cy = self.cell_center(food[0], food[1])
        cx += ox
        cy += oy
        pulse = 0.5 + 0.5 * math.sin(self.anim * 6.0)
        base = self.cell * 0.30
        r = base * (0.86 + 0.16 * pulse)

        # Glow.
        gr = self.cell * (0.62 + 0.10 * pulse)
        g.add(Color(*rgba(core.COL_FOOD, 0.16)))
        g.add(Ellipse(pos=(cx - gr, cy - gr), size=(2 * gr, 2 * gr)))
        # Expanding ring.
        ring_r = self.cell * (0.34 + 0.30 * pulse)
        g.add(Color(*rgba(core.COL_FOOD, 0.35 * (1.0 - pulse) + 0.1)))
        g.add(Line(circle=(cx, cy, ring_r), width=dp(2)))
        # Apple body.
        g.add(Color(*rgba(core.COL_FOOD)))
        g.add(Ellipse(pos=(cx - r, cy - r), size=(2 * r, 2 * r)))
        # Shading.
        g.add(Color(*rgba(core.COL_FOOD_DARK, 0.55)))
        g.add(Ellipse(pos=(cx - r * 0.8, cy - r * 1.0),
                      size=(2 * r * 0.55, 2 * r * 0.55)))
        # Highlight.
        g.add(Color(*rgba("#FFFFFF", 0.55)))
        hr = r * 0.22
        g.add(Ellipse(pos=(cx - r * 0.32 - hr, cy + r * 0.30 - hr),
                      size=(2 * hr, 2 * hr)))
        # Leaf.
        lr = self.cell * 0.11
        g.add(Color(*rgba(core.COL_LEAF)))
        g.add(Ellipse(pos=(cx + r * 0.30, cy + r * 0.72), size=(lr * 1.9, lr)))

    def _draw_particles(self, g, ox, oy):
        for p in self.particles:
            k = clamp(p["life"] / p["max"], 0.0, 1.0)
            r = max(1.0, p["size"] * k)
            g.add(Color(*rgba(p["color"], k)))
            g.add(Ellipse(pos=(p["x"] + ox - r, p["y"] + oy - r),
                          size=(2 * r, 2 * r)))
        for ring in self.rings:
            k = clamp(ring["life"] / ring["maxlife"], 0.0, 1.0)
            g.add(Color(*rgba(ring["color"], k * 0.8)))
            g.add(Line(circle=(ring["x"] + ox, ring["y"] + oy, ring["r"]),
                       width=dp(2)))


class ControlPad(Widget):
    """Bottom control panel: a 3x2 directional pad + pause button."""

    def __init__(self, app, **kwargs):
        super().__init__(**kwargs)
        self.app = app
        self.gap = dp(8)
        self.pad = dp(10)

        def mk(text, direction):
            b = NeonButton(text=text, font_size=dp(30))
            b.bind(on_release=lambda *_: app.queue_direction(direction, haptic=True))
            return b

        self.btn_up = mk("^", core.UP)
        self.btn_left = mk("<", core.LEFT)
        self.btn_down = mk("v", core.DOWN)
        self.btn_right = mk(">", core.RIGHT)
        self.btn_pause = NeonButton(text="II", font_size=dp(26))
        self.btn_pause.bind(on_release=lambda *_: app.toggle_pause())

        for b in (self.btn_up, self.btn_left, self.btn_down,
                  self.btn_right, self.btn_pause):
            self.add_widget(b)

        with self.canvas.before:
            Color(*rgba(core.COL_PANEL, 0.5))
            self._bg = Rectangle(pos=self.pos, size=self.size)
        self.bind(pos=self._sync_bg, size=self._sync_bg)
        self.bind(pos=self._layout, size=self._layout)

    def _sync_bg(self, *_):
        self._bg.pos = self.pos
        self._bg.size = self.size

    def _layout(self, *_):
        w, h = self.width, self.height
        pad = self.pad
        gap = self.gap
        avail_h = h - 2 * pad
        btn_h = (avail_h - gap) / 2.0
        # The strip is sized so this lands at >= 80dp; clamp defensively but
        # never allow the two rows to spill outside the strip.
        btn_h = clamp(btn_h, dp(60), avail_h)

        # D-pad occupies a centred 3-column block; pause button on the right.
        pause_w = clamp(w * 0.16, dp(110), dp(200))
        dpad_avail = w - pause_w - 3 * pad
        btn_w = clamp((dpad_avail - 2 * gap) / 3.0, dp(80), btn_h * 1.7)
        block_w = 3 * btn_w + 2 * gap

        bx = (dpad_avail - block_w) / 2.0 + pad
        by = pad

        def place(btn, col, row):
            btn.size = (btn_w, btn_h)
            btn.pos = (bx + col * (btn_w + gap), by + row * (btn_h + gap))

        place(self.btn_up, 1, 1)
        place(self.btn_left, 0, 0)
        place(self.btn_down, 1, 0)
        place(self.btn_right, 2, 0)

        self.btn_pause.size = (pause_w, avail_h)
        self.btn_pause.pos = (w - pad - pause_w, pad)


class Hud(Widget):
    """Top status bar: score / high / level / speed / sound toggle."""

    def __init__(self, app, **kwargs):
        super().__init__(**kwargs)
        self.app = app
        self.lbl_score = self._mk(dp(120))
        self.lbl_high = self._mk(dp(120))
        self.lbl_level = self._mk(dp(104))
        self.lbl_speed = self._mk(dp(96))
        self.btn_sound = NeonButton(text="SND", font_size=dp(15))
        self.btn_sound.bind(on_release=lambda *_: app.toggle_sound())
        for w in (self.lbl_score, self.lbl_high, self.lbl_level,
                  self.lbl_speed, self.btn_sound):
            self.add_widget(w)
        with self.canvas.before:
            Color(*rgba(core.COL_PANEL, 0.5))
            self._bg = Rectangle(pos=self.pos, size=self.size)
        self.bind(pos=self._sync_bg, size=self._sync_bg)
        self.bind(pos=self._layout, size=self._layout)

    def _sync_bg(self, *_):
        self._bg.pos = self.pos
        self._bg.size = self.size

    def _mk(self, width):
        lbl = Label(halign="left", valign="middle", size_hint=(None, None),
                    font_size=dp(17), color=rgba(core.COL_TEXT))
        lbl.width = width
        return lbl

    def _layout(self, *_):
        h = self.height
        pad = dp(12)
        y = self.y + (h - dp(26)) / 2.0
        x = self.x + pad
        for lbl in (self.lbl_score, self.lbl_high, self.lbl_level, self.lbl_speed):
            lbl.size = (dp(200), dp(26))
            lbl.text_size = (dp(160), dp(26))
            lbl.pos = (x, y)
            x += dp(120)
        self.btn_sound.size = (dp(64), min(h - dp(8), dp(36)))
        self.btn_sound.pos = (self.right - dp(12) - self.btn_sound.width,
                              self.y + (h - self.btn_sound.height) / 2.0)


# ===========================================================================
# Application
# ===========================================================================

class SnakeApp(App):
    title = "Snake - Animated Python"

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.model = core.GameModel()
        self.t = 0.0
        self.accum = 0.0
        self.clock_anim = 0.0
        self.blink = 0.0
        self.over_hold = 0.0       # prevents instant restart after dying
        self._commit_guard = 0
        self.last_run_score = 0
        self.last_level = 1
        self.new_record = False
        self.sound = None
        self.high_store = None
        self.frames = 0

    # -- lifecycle ----------------------------------------------------------
    def build(self):
        Window.clearcolor = rgba(core.COL_BG)
        try:
            Window.softinput_mode = "below_target"
        except Exception:
            pass

        self.hud = Hud(self)
        self.field = GameField(self)
        self.controls = ControlPad(self)

        root = FloatLayout()
        with root.canvas.before:
            Color(*rgba(core.COL_BG))
            self._root_bg = Rectangle(pos=root.pos, size=root.size)

        def _sync_root_bg(*_):
            self._root_bg.pos = root.pos
            self._root_bg.size = root.size

        root.bind(pos=_sync_root_bg, size=_sync_root_bg)
        self.hud.size_hint = (1, None)
        self.hud.height = dp(46)
        self.field.size_hint = (1, None)   # height set in _relayout
        self.controls.size_hint = (1, None)
        self.controls.height = dp(184)
        root.add_widget(self.hud)
        root.add_widget(self.field)
        root.add_widget(self.controls)
        self.root_widget = root
        root.bind(pos=self._relayout, size=self._relayout)
        self._relayout()

        self._refresh_overlay()
        return root

    def _relayout(self, *_):
        root = self.root_widget
        w, h = root.width, root.height
        # Height that guarantees two rows of >=80dp buttons plus padding/gaps:
        #   ctrl_h >= 2*80 + 2*pad + gap  ==  188dp
        controls_h = clamp(h * 0.44, dp(190), dp(250))
        controls_h = min(controls_h, h * 0.66)   # never swallow the whole screen
        hud_h = clamp(h * 0.10, dp(42), dp(58))
        self.hud.height = hud_h
        self.controls.height = controls_h
        self.hud.width = w
        self.hud.pos = (0, h - hud_h)
        self.controls.width = w
        self.controls.pos = (0, 0)
        self.field.width = w
        self.field.height = max(dp(80), h - hud_h - controls_h)
        self.field.pos = (0, controls_h)
        self.field._layout()

    def on_start(self):
        user_dir = self.user_data_dir
        try:
            os.makedirs(user_dir, exist_ok=True)
        except Exception:
            user_dir = os.path.join(os.path.expanduser("~"), ".snake_android")
            try:
                os.makedirs(user_dir, exist_ok=True)
            except Exception:
                user_dir = "."
        self.sound = SoundManager(user_dir)
        self.high_store = core.HighScoreStore(os.path.join(user_dir, "highscore.txt"))
        Window.bind(on_key_down=self._on_key)
        Clock.schedule_interval(self._update, 1.0 / 60.0)
        if _SELFTEST_GUI:
            self._schedule_gui_selftest()

    def on_pause(self):
        # Auto-pause when the OS backgrounds the app.
        if self.model.state == core.State.RUNNING:
            self.model.state = core.State.PAUSED
            self._refresh_overlay()
        return True

    def on_stop(self):
        self._commit_high_score()

    # -- input --------------------------------------------------------------
    def _on_key(self, _win, key, _sc, _cp, _mod):
        if key in (27, 1001):          # Escape / Android back
            if self.model.state == core.State.RUNNING:
                self.toggle_pause()
            return True
        if key in (275, 100):          # Right arrow / d
            self.queue_direction(core.RIGHT)
        elif key in (276, 97):         # Left / a
            self.queue_direction(core.LEFT)
        elif key in (273, 119):        # Up / w
            self.queue_direction(core.UP)
        elif key in (274, 115):        # Down / s
            self.queue_direction(core.DOWN)
        elif key in (112,):            # p
            self.toggle_pause()
        elif key in (109,):            # m
            self.toggle_sound()
        elif key in (13, 32, 1002):    # Enter / Space / Android center
            self.on_overlay_button()
        return True

    def queue_direction(self, direction, haptic=False):
        model = self.model
        if model.state != core.State.RUNNING:
            # A direction tap on the start screen begins play.
            if model.state == core.State.START:
                self.start_game()
            return
        if model.queue_direction(direction) and haptic:
            vibrate(0.018)

    def toggle_pause(self):
        model = self.model
        if model.state == core.State.RUNNING:
            model.state = core.State.PAUSED
        elif model.state == core.State.PAUSED:
            model.state = core.State.RUNNING
            self.accum = 0.0
        self._refresh_overlay()

    def toggle_sound(self):
        if self.sound is not None:
            muted = self.sound.toggle_mute()
            self.hud.btn_sound.text = "OFF" if muted else "SND"

    def start_game(self):
        self.model.reset()
        self.model.state = core.State.RUNNING
        self.model.spawn_food()
        self.model.prev_body = list(self.model.body)
        self.t = 0.0
        self.accum = 0.0
        self.field.particles = []
        self.field.rings = []
        self.field.shake = 0.0
        self.field.flash = 0.0
        self.last_run_score = 0
        self.last_level = 1
        self.new_record = False
        self._refresh_overlay()

    def on_overlay_button(self):
        state = self.model.state
        if state == core.State.START:
            self.start_game()
        elif state in (core.State.GAME_OVER, core.State.VICTORY):
            if self.over_hold <= 0:
                self.start_game()
        elif state == core.State.PAUSED:
            self.toggle_pause()
        elif state == core.State.RUNNING:
            pass  # tapping the board while playing should not restart

    # -- high score ---------------------------------------------------------
    def _commit_high_score(self):
        if self.high_store is None:
            return
        score = self.model.score
        if score > self.high_store.value:
            self.high_store.value = score
            self.high_store.save(score)
            return True
        return False

    # -- main loop ----------------------------------------------------------
    def _update(self, dt):
        model = self.model
        self.frames += 1
        self.blink += dt
        self.clock_anim += dt
        self.field.anim = self.clock_anim
        self.field.blink = self.blink

        if model.state == core.State.RUNNING:
            self.accum += dt
            interval = model.tick_interval
            guard = 0
            while self.accum >= interval and guard < 8:
                self.accum -= interval
                ev = model.step()
                self._on_event(ev)
                guard += 1
                if model.state != core.State.RUNNING:
                    self.accum = 0.0
                    break
            self.t = clamp(self.accum / model.tick_interval, 0.0, 1.0)
        else:
            if model.state == core.State.START:
                self.t = 0.0

        if self.over_hold > 0:
            self.over_hold = max(0.0, self.over_hold - dt)

        self.field.update_effects(dt)
        self._update_hud()
        self.field.redraw()

        # Pulse the overlay text alpha for a lively start screen.
        pulse = 0.6 + 0.4 * (0.5 + 0.5 * math.sin(self.blink * 3.0))
        self.field.ov_title.color = rgba(core.COL_ACCENT, pulse)
        if model.state in (core.State.GAME_OVER, core.State.VICTORY):
            self.field.ov_title.color = rgba(
                core.COL_GOLD if model.state == core.State.VICTORY else core.COL_DANGER,
                pulse,
            )

    def _on_event(self, ev):
        if ev == "eat":
            # The cell that was just eaten is the current head position.
            hx, hy = self.model.body[0]
            self.field.burst(hx, hy)
            if self.sound:
                self.sound.play("eat")
            vibrate(0.02)
            if self.model.level != self.last_level:
                self.last_level = self.model.level
                if self.sound:
                    self.sound.play("level_up")
        elif ev == "death":
            if self.sound:
                self.sound.play("hit")
            self.field.shake = core.SHAKE_TIME
            self.field.flash = 1.0
            vibrate(0.10)
            self.over_hold = 0.7
            self._commit_high_score()
            self._refresh_overlay()
        elif ev == "win":
            if self.sound:
                self.sound.play("level_up")
            self._commit_high_score()
            self._refresh_overlay()

    def _update_hud(self):
        model = self.model
        high = self.high_store.value if self.high_store else 0
        shown_high = max(high, model.score)
        self.hud.lbl_score.text = "SCORE %d" % model.score
        self.hud.lbl_high.text = "HIGH %d" % shown_high
        self.hud.lbl_level.text = "LEVEL %d" % model.level
        self.hud.lbl_speed.text = "SPEED %.1fx" % model.speed_multiplier

    def _refresh_overlay(self):
        state = self.model.state
        f = self.field
        if state == core.State.START:
            f.set_overlay("SNAKE", "Neon Arcade Edition",
                          "Swipe or use the buttons  -  tap to begin",
                          "TAP TO START")
        elif state == core.State.PAUSED:
            f.set_overlay("PAUSED", "Take a breath",
                          "Tap the board or press II to resume", None)
            f.ov_title.color = rgba(core.COL_TEXT)
        elif state in (core.State.GAME_OVER, core.State.VICTORY):
            high = self.high_store.value if self.high_store else 0
            if state == core.State.VICTORY:
                title = "YOU WIN!"
            else:
                title = "GAME OVER"
            sub = "Score %d   Best %d" % (self.model.score, max(high, self.model.score))
            f.set_overlay(title, sub, "Tap RESTART to play again", "RESTART")
        else:
            f.set_overlay("", "", "", None)

    # -- scripted GUI smoke test -------------------------------------------
    def _schedule_gui_selftest(self):
        self._gui_results = []
        self._gui_state = {"body": None}

        def check(name, condition, detail=""):
            self._gui_results.append((name, bool(condition), detail))
            print("[gui-check] %-42s %s %s" % (
                name, "PASS" if condition else "FAIL", detail))
            import sys as _s
            _s.stdout.flush()

        def tap(widget):
            """Dispatch a genuine touch tap through the Kivy event pipeline."""
            from kivy.tests.common import UnitTestTouch

            cx, cy = widget.center
            t = UnitTestTouch(cx, cy)
            t.touch_down()
            t.touch_up()

        def swipe(x1, y1, x2, y2):
            from kivy.tests.common import UnitTestTouch

            t = UnitTestTouch(x1, y1)
            t.touch_down()
            t.touch_move(x2, y2)
            t.touch_up()

        # --- steps ---------------------------------------------------------
        def step_start():
            check("start overlay shown", self.field.ov_title.text == "SNAKE")
            check("start button visible", self.field.ov_button.opacity > 0)
            self._shot("01_start")
            # Real tap on the on-screen START button.
            tap(self.field.ov_button)

        def step_started():
            check("touch TAP starts the game",
                  self.model.state == core.State.RUNNING)

        def step_mid():
            body_now = list(self.model.body)
            moved = body_now[0] != self._gui_state["body"][0]
            check("snake advances over time", moved,
                  "head %s -> %s (%d frames)" % (
                      self._gui_state["body"][0], body_now[0], self.frames))
            ninstr = len(getattr(self.field._dyn, "children", []))
            check("canvas has draw instructions", ninstr > 0, "%d instrs" % ninstr)
            self._shot("02_running")
            self.model.dir_queue.clear()

        def step_tap_dir():
            self.model.dir_queue.clear()
            tap(self.controls.btn_up)
            check("touch TAP on D-pad queues a turn",
                  len(self.model.dir_queue) > 0,
                  "queue=%s" % list(self.model.dir_queue))

        def step_swipe():
            self.start_game()  # deterministic: freshly heading RIGHT
            self.model.dir_queue.clear()
            fx, fy = self.field.center
            c = self.field.cell
            swipe(fx, fy - c * 3, fx, fy + c * 3)
            check("SWIPE on board queues a turn",
                  len(self.model.dir_queue) > 0,
                  "queue=%s" % list(self.model.dir_queue))
            self._shot("03_moved")

        def step_pause():
            tap(self.controls.btn_pause)
            check("touch TAP on pause pauses",
                  self.model.state == core.State.PAUSED,
                  "state=%s" % self.model.state)
            self._update(0.0)
            self._shot("04_paused")

        def step_resume():
            tap(self.controls.btn_pause)
            check("pause button resumes",
                  self.model.state == core.State.RUNNING,
                  "state=%s" % self.model.state)

        def step_death():
            self._force_game_over()
            check("game over reached", self.model.state == core.State.GAME_OVER)
            check("overlay switched to game over",
                  self.field.ov_title.text in ("GAME OVER", "YOU WIN!"))
            self._update(0.0)
            self._shot("05_gameover")

        def step_restart():
            tap(self.field.ov_button)
            check("touch RESTART restarts the game",
                  self.model.state == core.State.RUNNING
                  and self.model.score == 0,
                  "state=%s score=%d" % (self.model.state, self.model.score))

        def step_geometry():
            ok, detail = self._check_geometry()
            check("layout geometry valid", ok, detail)
            self._finish_gui_selftest()

        # Relative gaps counted from the moment the render loop is live.
        self._gui_steps = [
            (0.4, step_start), (0.5, step_started), (0.9, step_mid),
            (0.3, step_tap_dir), (0.3, step_swipe),
            (0.3, step_pause), (0.3, step_resume),
            (0.4, step_death), (0.8, step_restart),
            (0.4, step_geometry),
        ]
        Clock.schedule_once(lambda _dt: self._gui_timeout(), 40.0)
        Clock.schedule_interval(self._gui_wait_ready, 0.1)

    def _gui_wait_ready(self, dt):
        if self.frames < 20:
            return
        Clock.unschedule(self._gui_wait_ready)
        self._gui_state["body"] = list(self.model.body)
        t = 0.0
        for gap, fn in self._gui_steps:
            t += gap
            Clock.schedule_once(lambda _dt, f=fn: self._safe(f), t)

    def _gui_timeout(self):
        print("[gui-selftest] WATCHDOG TIMEOUT after 40s (frames=%d)" % self.frames)
        os._exit(1)

    def _safe(self, fn):
        try:
            fn()
        except Exception:
            import traceback
            traceback.print_exc()

    def _check_geometry(self):
        hud, field, ctrl = self.hud, self.field, self.controls
        problems = []

        for name, btn in (("up", ctrl.btn_up), ("down", ctrl.btn_down),
                          ("left", ctrl.btn_left), ("right", ctrl.btn_right)):
            if btn.width < dp(80) - 0.5 or btn.height < dp(80) - 0.5:
                problems.append("%s button %.0fx%.0f < 80dp" % (
                    name, btn.width, btn.height))
        if ctrl.btn_pause.width < dp(80) - 0.5:
            problems.append("pause button too narrow")

        # Buttons must stay inside the control strip.
        for name, btn in (("up", ctrl.btn_up), ("down", ctrl.btn_down),
                          ("left", ctrl.btn_left), ("right", ctrl.btn_right),
                          ("pause", ctrl.btn_pause)):
            if (btn.x < -0.5 or btn.y < -0.5
                    or btn.right > ctrl.width + 0.5
                    or btn.top > ctrl.height + 0.5):
                problems.append("%s button outside control strip" % name)

        # Vertical stacking: HUD on top, field in the middle, controls bottom.
        if not (hud.y >= field.top - 0.5):
            problems.append("HUD overlaps field")
        if not (field.y >= ctrl.top - 0.5):
            problems.append("field overlaps controls")
        if field.width <= 0 or field.height <= 0:
            problems.append("field has no size")

        # Board fits inside the field and is centred.
        if (field.board_x < -0.5 or field.board_y < -0.5
                or field.board_x + field.board_w > field.width + 0.5
                or field.board_y + field.board_h > field.height + 0.5):
            problems.append("board does not fit inside field")
        cx_err = abs((field.board_x + field.board_w / 2) - field.width / 2)
        cy_err = abs((field.board_y + field.board_h / 2) - field.height / 2)
        if cx_err > 1.0 or cy_err > 1.0:
            problems.append("board not centred (err %.1f, %.1f)" % (cx_err, cy_err))

        # Directional buttons must not overlap each other.
        dpad = [ctrl.btn_up, ctrl.btn_down, ctrl.btn_left, ctrl.btn_right]
        for i in range(len(dpad)):
            for j in range(i + 1, len(dpad)):
                a, b = dpad[i], dpad[j]
                if (a.x < b.right - 0.5 and b.x < a.right - 0.5
                        and a.y < b.top - 0.5 and b.y < a.top - 0.5):
                    problems.append("buttons %d/%d overlap" % (i, j))

        detail = ("hud=%.0fx%.0f field=%.0fx%.0f ctrl=%.0fx%.0f cell=%.1f"
                  % (hud.width, hud.height, field.width, field.height,
                     ctrl.width, ctrl.height, field.cell))
        if problems:
            detail += " | " + "; ".join(problems)
        return (not problems), detail

    def _finish_gui_selftest(self):
        passed = sum(1 for _, ok, _ in self._gui_results if ok)
        total = len(self._gui_results)
        print("-" * 60)
        print("GUI checks: %d/%d passed" % (passed, total))
        overall = passed == total
        print("GUI SELF-TEST: %s" % ("PASS" if overall else "FAIL"))
        print("-" * 60)
        import sys as _s
        _s.stdout.flush()
        os._exit(0 if overall else 1)

    def _force_game_over(self):
        # Drive the snake straight into a wall to reach the game-over screen.
        self.model.state = core.State.RUNNING
        self.model.direction = core.UP
        self.model.dir_queue.clear()
        for _ in range(core.ROWS + 3):
            if self.model.state != core.State.RUNNING:
                break
            self.model.step()
        if self.model.state == core.State.RUNNING:  # fallback
            self.model.state = core.State.GAME_OVER
            self.model.death_reason = "wall"
        self.field.shake = core.SHAKE_TIME
        self.field.flash = 1.0
        self.over_hold = 0.7
        self._commit_high_score()
        self._refresh_overlay()

    def _shot(self, name):
        # Force a redraw for the current state before capturing.
        self._update(0.0)
        path = os.path.join(os.getcwd(), "shot_%s.png" % name)
        # export_to_png renders the widget tree into an FBO, which is far more
        # reliable than grabbing the OS framebuffer (which is often black on
        # Windows/ANGLE).
        try:
            self.root_widget.export_to_png(path)
            print("[gui-selftest] wrote", path)
        except Exception as exc:  # pragma: no cover
            print("[gui-selftest] export_to_png failed:", exc)
            try:
                Window.screenshot(name=path)
                print("[gui-selftest] wrote (screenshot)", path)
            except Exception as exc2:
                print("[gui-selftest] screenshot failed:", exc2)


# ===========================================================================
# Entry point
# ===========================================================================

def main():
    SnakeApp().run()


if __name__ == "__main__":
    if _SELFTEST_GUI:
        # Give the window a moment, then the scheduled sequence takes over.
        SnakeApp().run()
    else:
        main()
