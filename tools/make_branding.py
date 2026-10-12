#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
make_branding.py - procedurally generate the launcher icon and splash image.

The project ships **no binary image assets**: this script draws ``icon.png`` and
``presplash.png`` from scratch using nothing but the standard library (a tiny
RGBA PNG encoder plus signed-distance-function shape rasterisation).  It is run
automatically by CI before Buildozer, and can be run by hand::

    python tools/make_branding.py

The palette is copied from ``snake_core.py`` so the artwork matches the game.
"""

from __future__ import annotations

import math
import os
import struct
import sys
import zlib

# -- palette (kept in sync with snake_core.py) ------------------------------
COL_BG = "#0B1220"
COL_PANEL = "#111C33"
COL_BORDER = "#1E3A5F"
COL_HEAD = "#38D9FF"
COL_BODY_HEAD = "#2BB8E6"
COL_BODY_TAIL = "#0E7490"
COL_FOOD = "#FF6B6B"
COL_LEAF = "#4ADE80"
COL_GOLD = "#FFD166"


def rgb(hexstr):
    hexstr = hexstr.lstrip("#")
    return (int(hexstr[0:2], 16), int(hexstr[2:4], 16), int(hexstr[4:6], 16))


# -- minimal PNG encoder ----------------------------------------------------
def write_png(path, width, height, rows):
    """rows: list of ``height`` byte strings, each 4*width bytes (RGBA)."""

    def chunk(tag, data):
        out = struct.pack(">I", len(data)) + tag + data
        return out + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    raw = b"".join(b"\x00" + row for row in rows)
    png = (b"\x89PNG\r\n\x1a\n"
           + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
           + chunk(b"IDAT", zlib.compress(raw, 9))
           + chunk(b"IEND", b""))
    with open(path, "wb") as fh:
        fh.write(png)


# -- tiny anti-aliased rasteriser -------------------------------------------
class Canvas(object):
    """Float RGBA buffer with SDF-based shapes (1px analytic anti-aliasing)."""

    def __init__(self, width, height, bg):
        r, g, b = bg
        self.w = width
        self.h = height
        row = [r / 255.0, g / 255.0, b / 255.0, 1.0] * width
        self.px = [list(row) for _ in range(height)]

    def _blend(self, x, y, color, alpha):
        if alpha <= 0.0 or x < 0 or y < 0 or x >= self.w or y >= self.h:
            return
        if alpha > 1.0:
            alpha = 1.0
        row = self.px[y]
        i = x * 4
        row[i] += (color[0] / 255.0 - row[i]) * alpha
        row[i + 1] += (color[1] / 255.0 - row[i + 1]) * alpha
        row[i + 2] += (color[2] / 255.0 - row[i + 2]) * alpha

    def rounded_rect(self, x0, y0, x1, y1, radius, color, alpha=1.0):
        """Stroke-free filled rounded rectangle in pixel coordinates."""
        for y in range(max(0, int(y0) - 2), min(self.h, int(y1) + 3)):
            for x in range(max(0, int(x0) - 2), min(self.w, int(x1) + 3)):
                dx = max(x0 + radius - (x + 0.5), 0.0, (x + 0.5) - (x1 - radius))
                dy = max(y0 + radius - (y + 0.5), 0.0, (y + 0.5) - (y1 - radius))
                d = math.hypot(dx, dy) - radius
                self._blend(x, y, color, alpha * min(1.0, max(0.0, 0.5 - d)))

    def circle(self, cx, cy, r, color, alpha=1.0):
        for y in range(max(0, int(cy - r) - 2), min(self.h, int(cy + r) + 3)):
            for x in range(max(0, int(cx - r) - 2), min(self.w, int(cx + r) + 3)):
                d = math.hypot(x + 0.5 - cx, y + 0.5 - cy) - r
                self._blend(x, y, color, alpha * min(1.0, max(0.0, 0.5 - d)))

    def ring(self, cx, cy, r, width, color, alpha=1.0):
        for y in range(max(0, int(cy - r - width) - 2), min(self.h, int(cy + r + width) + 3)):
            for x in range(max(0, int(cx - r - width) - 2), min(self.w, int(cx + r + width) + 3)):
                d = abs(math.hypot(x + 0.5 - cx, y + 0.5 - cy) - r) - width * 0.5
                self._blend(x, y, color, alpha * min(1.0, max(0.0, 0.5 - d)))

    def to_rows(self):
        out = []
        for y in range(self.h):
            row = bytearray(self.w * 4)
            for x in range(self.w):
                p = self.px[y][x * 4:x * 4 + 4]
                row[x * 4] = int(max(0.0, min(1.0, p[0])) * 255.0 + 0.5)
                row[x * 4 + 1] = int(max(0.0, min(1.0, p[1])) * 255.0 + 0.5)
                row[x * 4 + 2] = int(max(0.0, min(1.0, p[2])) * 255.0 + 0.5)
                row[x * 4 + 3] = 255
            out.append(bytes(row))
        return out

    def save(self, path):
        write_png(path, self.w, self.h, self.to_rows())


def lerp(a, b, t):
    return a + (b - a) * t


def draw_logo(c, cx, cy, size):
    """Draw the snake + apple mark centred on (cx, cy), spanning ``size`` px."""
    bg = rgb(COL_BG)
    panel = rgb(COL_PANEL)
    border = rgb(COL_BORDER)
    head = rgb(COL_HEAD)
    body_a = rgb(COL_BODY_HEAD)
    body_b = rgb(COL_BODY_TAIL)
    food = rgb(COL_FOOD)
    leaf = rgb(COL_LEAF)

    half = size / 2.0
    # Panel with a glowing border.
    c.rounded_rect(cx - half, cy - half, cx + half, cy + half,
                   size * 0.22, panel)
    c.ring(cx, cy, size * 0.47, size * 0.022, border)

    # Serpentine path (normalised to the panel, y down).
    pts = [(0.20, 0.70), (0.52, 0.70), (0.52, 0.47),
           (0.27, 0.47), (0.27, 0.28), (0.60, 0.28)]

    def pt(t):
        """Position at parameter t in [0, 1] along the polyline."""
        segs = len(pts) - 1
        f = t * segs
        i = min(int(f), segs - 1)
        return (lerp(pts[i][0], pts[i + 1][0], f - i),
                lerp(pts[i][1], pts[i + 1][1], f - i))

    n = 46
    for k in range(n, 0, -1):
        u = (k - 1) / float(n - 1)
        nx, ny = pt(u)
        x = cx - half + nx * size
        y = cy - half + ny * size
        col = (int(lerp(body_b[0], body_a[0], u)),
               int(lerp(body_b[1], body_a[1], u)),
               int(lerp(body_b[2], body_a[2], u)))
        c.circle(x, y, size * lerp(0.038, 0.058, u), col)

    # Head.
    hx, hy = pt(1.0)
    hx = cx - half + hx * size
    hy = cy - half + hy * size
    c.circle(hx, hy, size * 0.078, head)
    eye = size * 0.017
    c.circle(hx - size * 0.020, hy - size * 0.024, eye, (7, 18, 32))
    c.circle(hx + size * 0.028, hy - size * 0.012, eye, (7, 18, 32))

    # Apple.
    ax, ay = cx - half + 0.74 * size, cy - half + 0.62 * size
    c.circle(ax, ay, size * 0.085, food)
    c.circle(ax - size * 0.028, ay - size * 0.030, size * 0.022, (255, 190, 190),
             alpha=0.75)
    # Leaf as two overlapping circles.
    lx, ly = ax + size * 0.012, ay - size * 0.090
    c.circle(lx - size * 0.020, ly, size * 0.026, leaf)
    c.circle(lx + size * 0.020, ly - size * 0.006, size * 0.026, leaf)


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    root = os.path.dirname(here)

    # Launcher icon: 512x512 with a small margin so it survives masking.
    icon_size = 512
    c = Canvas(icon_size, icon_size, rgb(COL_BG))
    draw_logo(c, icon_size / 2.0, icon_size / 2.0, icon_size * 0.92)
    icon_path = os.path.join(root, "icon.png")
    c.save(icon_path)

    # Splash: portrait canvas, logo centred, so it crops gracefully any way.
    sw, sh = 720, 1280
    c = Canvas(sw, sh, rgb(COL_BG))
    draw_logo(c, sw / 2.0, sh / 2.0, sw * 0.62)
    splash_path = os.path.join(root, "presplash.png")
    c.save(splash_path)

    print("wrote %s (%dx%d)" % (icon_path, icon_size, icon_size))
    print("wrote %s (%dx%d)" % (splash_path, sw, sh))
    return 0


if __name__ == "__main__":
    sys.exit(main())
