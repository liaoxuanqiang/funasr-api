#!/usr/bin/env python3
"""Generate the FunASR PWA app icons using only the Python standard library.

Produces rounded-square PNG app icons (with a microphone glyph) so the
Progressive Web App can be installed on home screens. Run from the repo root:

    python pwa/generate_icons.py

The generated PNGs are committed to the repository, so the workflow does not
need to run this script at deploy time.
"""

import os
import struct
import zlib

ROOT = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(ROOT, "icons")

# Brand colors (top -> bottom gradient background)
COLOR_TOP = (79, 124, 255)      # #4F7CFF
COLOR_BOTTOM = (30, 58, 138)    # #1E3A8A
COLOR_GLYPH = (255, 255, 255)   # white mic


def lerp(color_a, color_b, t):
    return tuple(int(a + (b - a) * t) for a, b in zip(color_a, color_b))


def make_png(size, data):
    """Encode an RGBA pixel buffer (list of rows of tuples) as a PNG byte string."""
    raw = b""
    for row in data:
        raw += b"\x00" + b"".join(
            struct.pack("4B", *(px if len(px) == 4 else (*px, 255))) for px in row
        )

    def chunk(tag, payload):
        return (
            struct.pack(">I", len(payload))
            + tag
            + payload
            + struct.pack(">I", zlib.crc32(tag + payload) & 0xFFFFFFFF)
        )

    ihdr = struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", zlib.compress(raw, 9))
        + chunk(b"IEND", b"")
    )


def rounded_rect(pixels, size, x0, y0, x1, y1, radius, color):
    """Fill a rounded rectangle (inclusive) with a solid color."""
    x0, y0 = max(0, x0), max(0, y0)
    x1, y1 = min(size - 1, x1), min(size - 1, y1)
    for y in range(y0, y1 + 1):
        for x in range(x0, x1 + 1):
            # Distance to the nearest corner for the rounded effect.
            cx = min(max(x, x0 + radius), x1 - radius)
            cy = min(max(y, y0 + radius), y1 - radius)
            if (x - cx) ** 2 + (y - cy) ** 2 <= radius * radius:
                pixels[y][x] = color


def draw_rect(pixels, size, x0, y0, x1, y1, color):
    for y in range(max(0, y0), min(size, y1 + 1)):
        for x in range(max(0, x0), min(size, x1 + 1)):
            pixels[y][x] = color


def draw_icon(size):
    pad = round(size * 0.06)
    radius = round(size * 0.18)
    pixels = [[(0, 0, 0, 0)] * size for _ in range(size)]

    # Gradient rounded-square background.
    for y in range(size):
        t = y / max(1, size - 1)
        color = lerp(COLOR_TOP, COLOR_BOTTOM, t)
        rounded_rect(pixels, size, pad, pad, size - 1 - pad, size - 1 - pad,
                     radius, color)

    # --- Microphone glyph (centered, ~62% of icon width) ---
    cx = size // 2
    # Capsule: vertical rounded rectangle.
    cap_w = round(size * 0.30)          # width of the mic body
    cap_h = round(size * 0.42)          # height of the mic body
    cap_r = cap_w // 2                  # fully rounded ends
    cap_x0 = cx - cap_w // 2
    cap_y0 = round(size * 0.24)
    cap_x1 = cx + cap_w // 2
    cap_y1 = cap_y0 + cap_h
    rounded_rect(pixels, size, cap_x0, cap_y0, cap_x1, cap_y1, cap_r,
                 COLOR_GLYPH)

    # U-shaped frame around the capsule.
    frame_t = round(size * 0.30)        # top of the frame legs
    frame_b = round(size * 0.66)        # bottom of the frame (and capsule)
    leg_w = round(size * 0.055)         # thickness of the frame legs
    gap = round(size * 0.035)           # gap between capsule and frame
    draw_rect(pixels, size, cap_x0 - gap - leg_w, frame_t,
              cap_x0 - gap, frame_b, COLOR_GLYPH)          # left leg
    draw_rect(pixels, size, cap_x1 + gap, frame_t,
              cap_x1 + gap + leg_w, frame_b, COLOR_GLYPH)  # right leg
    draw_rect(pixels, size, cap_x0 - gap - leg_w, frame_b - leg_w,
              cap_x1 + gap + leg_w, frame_b, COLOR_GLYPH)  # bottom connector

    # Stand below the frame.
    stand_w = round(size * 0.055)
    stand_t = frame_b
    stand_b = round(size * 0.80)
    draw_rect(pixels, size, cx - stand_w // 2, stand_t,
              cx + stand_w // 2, stand_b, COLOR_GLYPH)

    # Base.
    base_h = round(size * 0.035)
    base_w = round(size * 0.24)
    draw_rect(pixels, size, cx - base_w // 2, stand_b - base_h,
              cx + base_w // 2, stand_b, COLOR_GLYPH)

    return pixels


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    for size in (192, 512):
        out = os.path.join(OUT_DIR, f"icon-{size}.png")
        with open(out, "wb") as fh:
            fh.write(make_png(size, draw_icon(size)))
        print(f"Wrote {out} ({size}x{size})")


if __name__ == "__main__":
    main()