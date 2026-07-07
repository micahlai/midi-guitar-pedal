#!/usr/bin/env python3
"""Pre-render the boot artwork into raw framebuffer pixels (splash.fb).

boot-splash.service just `cat`s the output into /dev/fb0 at early boot —
no image decoding at boot time. Reads the live framebuffer geometry from
sysfs so the bytes match exactly; rerun after changing the artwork or the
display mode. Decodes the JPG with pygame (the Pi has no Pillow), so run it
with the app venv: /opt/midi-controller/venv/bin/python.

Env overrides (for testing off-device): SPLASH_FB_SYSFS, SPLASH_IMAGE,
SPLASH_OUT.
"""

import os
import sys

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

FB_SYSFS = os.environ.get("SPLASH_FB_SYSFS", "/sys/class/graphics/fb0")
IMAGE = os.environ.get(
    "SPLASH_IMAGE", "/opt/midi-controller/app/ui/assets/loading_screen.jpg")
OUT = os.environ.get(
    "SPLASH_OUT", "/opt/midi-controller/assets/splash.fb")


def read_sysfs(name: str) -> str:
    with open(os.path.join(FB_SYSFS, name)) as f:
        return f.read().strip()


def main() -> int:
    import pygame

    width, height = map(int, read_sysfs("virtual_size").split(","))
    bpp = int(read_sysfs("bits_per_pixel"))
    stride = int(read_sysfs("stride"))
    if bpp not in (16, 32):
        print(f"unsupported framebuffer depth {bpp} bpp", file=sys.stderr)
        return 1

    image = pygame.image.load(IMAGE)
    # Portrait-scan panel: the framebuffer is the transpose of the landscape
    # artwork, so rotate the artwork clockwise to match — must agree with
    # DISPLAY_ROTATION_DEGREES in app/hardware/constants.py (pygame's rotate
    # is counter-clockwise-positive, hence the negative angle).
    if height > width and image.get_width() > image.get_height():
        rotate_cw = int(os.environ.get("SPLASH_ROTATE_DEGREES", "90"))
        image = pygame.transform.rotate(image, -rotate_cw)
    # Aspect-fill and center-crop to the framebuffer.
    iw, ih = image.get_size()
    scale = max(width / iw, height / ih)
    image = pygame.transform.smoothscale(
        image, (max(round(iw * scale), width), max(round(ih * scale), height)))
    crop = pygame.Rect((image.get_width() - width) // 2,
                       (image.get_height() - height) // 2, width, height)
    image = image.subsurface(crop)

    if bpp == 32:  # XRGB little-endian: B,G,R,X per pixel
        pixels = pygame.image.tobytes(image, "BGRA")
        row_bytes = width * 4
    else:  # RGB565 little-endian
        rgb = pygame.image.tobytes(image, "RGB")
        packed = bytearray(width * height * 2)
        for i in range(width * height):
            r, g, b = rgb[3 * i], rgb[3 * i + 1], rgb[3 * i + 2]
            value = ((r >> 3) << 11) | ((g >> 2) << 5) | (b >> 3)
            packed[2 * i] = value & 0xFF
            packed[2 * i + 1] = value >> 8
        pixels = bytes(packed)
        row_bytes = width * 2

    pad = b"\0" * (stride - row_bytes)  # stride can exceed the visible row
    with open(OUT, "wb") as f:
        for y in range(height):
            f.write(pixels[y * row_bytes:(y + 1) * row_bytes])
            f.write(pad)
    print(f"splash.fb written: {width}x{height} @ {bpp} bpp, stride {stride} -> {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
