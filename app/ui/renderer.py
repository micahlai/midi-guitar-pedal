"""Fullscreen 1920x480 UI renderer (pygame on KMSDRM, no desktop needed).

Milestone 2: draw the 5x2 button panel grid and the right expression strip
placeholder. Panels show placeholder labels plus the required bottom status
rectangle; B10 (bottom-right) is the Shift/Menu panel and shows the current
menu. Runs its own render thread at ~30 fps.

Debug: SIGUSR1 makes the render thread save the next frame to
/tmp/controller-frame.png (usable over ssh to "see" the screen).
"""

import logging
import os
import threading
import time
from pathlib import Path

from config.model import get_primary, get_secondary_action, get_slot, resolve_color
from web.images import image_path
from hardware import battery
from hardware.constants import (DISPLAY_HEIGHT, DISPLAY_ROTATION_DEGREES,
                                DISPLAY_WIDTH)
from state.manager import StateManager
from ui.gles import CanvasPresenter
from version import FIRMWARE_VERSION

log = logging.getLogger("controller.ui")

FPS = 30
HOLD_FPS = 60  # target while a hold bar animates, for a smoother fill
GRID_COLS = 5
GRID_ROWS = 2
PANEL_MARGIN = 8
STATUS_BAR_HEIGHT = 22
HEADER_HEIGHT = 52  # top strip: current patch, tempo, power (Milestone 16)
FLICKER_PERIOD_S = 2.0  # primary+secondary both active -> alternate on_colors
TEMPO_STALE_SECONDS = 2.0  # blank the BPM readout when the clock stops
SCREENSHOT_PATH = "/tmp/controller-frame.png"

# Boot screen: artwork with startup messages bottom-left and the firmware
# version bottom-right. Startup finishes before the display is even up, so
# hold the screen a minimum time once visible.
BOOT_IMAGE_PATH = Path(__file__).parent / "assets" / "loading_screen.jpg"
BOOT_MIN_SECONDS = 2.5
BOOT_MESSAGE_COUNT = 4  # most recent messages shown
BOOT_MARGIN = 28

# Hold progress bar (Milestone 13.5): starts growing this long after the
# press and is rescaled so it still reaches the top exactly at the hold time.
HOLD_GROW_DELAY_S = 0.2
HOLD_BAR_COLOR = "#4E4E4E"  # light gray, behind text and status color


def hold_progress(pressed_at: float, hold_seconds: float, now: float) -> float:
    """0.0-1.0 fill fraction of the hold bar; 0 during the initial delay,
    exactly 1.0 at pressed_at + hold_seconds."""
    span = hold_seconds - HOLD_GROW_DELAY_S
    if span <= 0:  # hold shorter than the delay: jump straight to full
        return 1.0 if now - pressed_at >= hold_seconds else 0.0
    fraction = (now - pressed_at - HOLD_GROW_DELAY_S) / span
    return max(0.0, min(1.0, fraction))


class UiRenderer:
    def __init__(self, state: StateManager):
        self.state = state
        self._thread: threading.Thread | None = None
        self._running = False
        self.screenshot_requested = False
        self._pygame = None  # set once the render thread imports pygame
        self._font_cache: dict[int, object] = {}
        # asset_id -> loaded Surface (None = load failed/missing; new uploads
        # always get fresh ids so entries never go stale).
        self._image_cache: dict[str, object] = {}
        # (asset_id, w, h) -> scaled Surface for the last-used target size.
        self._scaled_cache: dict[tuple, object] = {}
        self._display_up_at: float | None = None
        self._boot_background_cache: tuple | None = None  # (size, Surface|None)

    @property
    def theme(self) -> dict:
        # Read live: a preset load swaps config["ui"] for a new dict.
        return self.state.config["ui"]["theme"]

    def start(self) -> None:
        self._running = True
        self._thread = threading.Thread(target=self._run, name="ui", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._running = False
        if self._thread:
            self._thread.join(timeout=2)
        log.info("UI renderer stopped")

    def request_screenshot(self) -> None:
        self.screenshot_requested = True

    # --- render thread -----------------------------------------------------

    def _run(self) -> None:
        os.environ.setdefault("SDL_VIDEODRIVER", "kmsdrm")
        import pygame

        try:
            pygame.display.init()
            pygame.font.init()
            # The UI is always rendered at exactly 1920x480 on a canvas
            # surface, centered and unscaled on whatever mode we get. Pick the
            # smallest advertised mode that fits the canvas on both axes (the
            # real panel matches exactly; a desk monitor gets e.g. 1920x1080
            # for debugging). The production panel is PORTRAIT-scan (480x1920
            # only — no landscape mode in its EDID), so when nothing fits
            # normally, look for a transposed fit and let the GL presenter
            # rotate the canvas. If neither fits, keep the current mode
            # (cropped).
            modes = pygame.display.list_modes() or []
            fitting = [m for m in modes
                       if m[0] >= DISPLAY_WIDTH and m[1] >= DISPLAY_HEIGHT]
            rotation = 0
            if fitting:
                target = min(fitting, key=lambda m: m[0] * m[1])
            else:
                transposed = [m for m in modes
                              if m[0] >= DISPLAY_HEIGHT and m[1] >= DISPLAY_WIDTH]
                if transposed:
                    target = min(transposed, key=lambda m: m[0] * m[1])
                    rotation = DISPLAY_ROTATION_DEGREES
                else:
                    target = (0, 0)
            # OPENGL mode + the GLES presenter: SDL's plain 2D present leaves
            # the scanout plane's alpha at zero, which vc4 composites as a
            # black screen. See ui/gles.py.
            screen = pygame.display.set_mode(
                target, pygame.FULLSCREEN | pygame.OPENGL | pygame.DOUBLEBUF
            )
            pygame.mouse.set_visible(False)
        except pygame.error as e:
            log.error("display init failed: %s", e)
            return

        w, h = screen.get_size()
        canvas = pygame.Surface((DISPLAY_WIDTH, DISPLAY_HEIGHT))
        swizzle, direct = self._canvas_upload_mode(canvas)
        try:
            presenter = CanvasPresenter((w, h), canvas.get_size(),
                                        swizzle=swizzle, rotation=rotation)
        except (OSError, RuntimeError) as e:
            log.error("GLES presenter init failed: %s", e)
            pygame.quit()
            return
        log.info(
            "display up: mode %dx%d, driver %s, UI canvas %dx%d centered, "
            "rotation %d°",
            w, h, pygame.display.get_driver(), DISPLAY_WIDTH, DISPLAY_HEIGHT,
            rotation,
        )
        self._display_up_at = time.monotonic()

        font_big = pygame.font.Font(None, 72)
        font_small = pygame.font.Font(None, 36)
        self._font_cache = {72: font_big, 36: font_small}
        self._pygame = pygame
        clock = pygame.time.Clock()

        def present() -> None:
            # Zero-copy when the canvas layout allows it: hand the surface's
            # pixel buffer straight to glTexSubImage2D (the shader swizzles
            # channel order) instead of a per-frame tobytes convert+copy of
            # the whole 1920x480 canvas.
            if direct:
                canvas.lock()
                try:
                    presenter.present(canvas._pixels_address)
                finally:
                    canvas.unlock()
            else:
                presenter.present(pygame.image.tobytes(canvas, "RGBA"))
            pygame.display.flip()

        # Milestone 16: skip the draw + GL upload when nothing on screen can
        # have changed (signature compare) — the last flipped frame stays on
        # scanout. This takes the render thread from ~90% of a core to near
        # idle between interactions. While a hold bar animates, the static
        # frame is kept on a cached base surface and only the held panels are
        # redrawn per frame on top of a base blit. A draw failure shows an
        # error screen instead of killing the UI thread.
        base = pygame.Surface(canvas.get_size())
        last_signature = object()
        while self._running:
            pygame.event.pump()
            holds = dict(self.state.hold_started)
            signature = self._frame_signature(time.monotonic())
            base_dirty = signature != last_signature
            if base_dirty:
                last_signature = signature
                try:
                    self._draw(pygame, base, font_big, font_small)
                except Exception:
                    log.exception("draw failed")
                    self._draw_error_screen(pygame, base, font_big, font_small)
            if base_dirty or holds or self.screenshot_requested:
                canvas.blit(base, (0, 0))
                if holds:
                    try:
                        self._draw_holds(pygame, canvas, font_big, font_small, holds)
                    except Exception:
                        log.exception("draw failed")
                        self._draw_error_screen(pygame, canvas, font_big, font_small)
                present()
                if self.screenshot_requested:
                    self.screenshot_requested = False
                    pygame.image.save(canvas, SCREENSHOT_PATH)
                    log.info("frame saved to %s", SCREENSHOT_PATH)
            clock.tick(HOLD_FPS if holds else FPS)

        pygame.quit()

    @staticmethod
    def _canvas_upload_mode(canvas) -> tuple[str, bool]:
        """(shader swizzle, direct) for uploading the canvas to GL. direct
        means the raw pixel buffer is GL-uploadable as-is: 4 bytes/pixel with
        no row padding and a channel order the shader can unswizzle."""
        r, g, b, _a = canvas.get_masks()
        if (canvas.get_bytesize() == 4
                and canvas.get_pitch() == canvas.get_width() * 4):
            if (r, g, b) == (0x00FF0000, 0x0000FF00, 0x000000FF):
                return "bgr", True  # XRGB8888: bytes are B,G,R,X
            if (r, g, b) == (0x000000FF, 0x0000FF00, 0x00FF0000):
                return "rgb", True  # XBGR8888: bytes are R,G,B,X
        return "rgb", False  # unknown layout: tobytes("RGBA") fallback

    def _frame_signature(self, now: float):
        """Everything the BASE frame depends on, cheap to compute. Hold bars
        are excluded on purpose: while one animates, the base is reused and
        only the held panels are redrawn per frame. Time-driven visuals
        (flicker, tempo staleness) enter as coarse buckets so an idle screen
        redraws at most a couple of times per second."""
        state = self.state
        if self._boot_active(now):
            # Only new boot messages repaint; leaving boot changes the shape.
            return ("boot", tuple(state.boot_messages))
        return (
            state.config_version,
            state.current_menu,
            state.current_program,
            tuple(sorted(state.effect_states.items())),
            state.expression_detected,
            round(state.expression_value, 3),
            state.expression_mode,
            state.shift_held,
            tuple(sorted(state.pressed_buttons)),
            tuple(sorted(state.secondary_pressed)),
            state.settings_open,
            state.settings_view,
            state.settings_index,
            tuple(state.settings_rows),
            self._tempo_text(now),
            int(now / (FLICKER_PERIOD_S / 2)),
        )

    def _boot_active(self, now: float) -> bool:
        """Boot screen stays up while main.py starts modules AND for a
        minimum time after the display comes up (startup usually beats the
        display init, which would flash the artwork for a frame or two)."""
        if self.state.booting:
            return True
        return (self._display_up_at is not None
                and now < self._display_up_at + BOOT_MIN_SECONDS)

    def _boot_background(self, pygame, size):
        """The boot artwork scaled to cover the canvas (cached), or None if
        the file is missing/unreadable."""
        if self._boot_background_cache and self._boot_background_cache[0] == size:
            return self._boot_background_cache[1]
        surface = None
        try:
            image = pygame.image.load(str(BOOT_IMAGE_PATH))
            try:
                image = image.convert()
            except pygame.error:
                pass  # headless harness: no display mode set
            w, h = image.get_size()
            scale = max(size[0] / w, size[1] / h)
            surface = pygame.transform.smoothscale(
                image, (max(int(w * scale), 1), max(int(h * scale), 1)))
        except Exception as e:
            log.warning("boot image %s failed to load: %s", BOOT_IMAGE_PATH, e)
        self._boot_background_cache = (size, surface)
        return surface

    def _draw_boot(self, pygame, surface, font_small) -> None:
        surface.fill(pygame.Color("#000000"))
        image = self._boot_background(pygame, surface.get_size())
        if image is not None:
            surface.blit(image, image.get_rect(
                center=(surface.get_width() // 2, surface.get_height() // 2)))

        def blit_shadowed(text, x, y):
            for offset, color in ((2, "#000000"), (0, "#FFFFFF")):
                rendered = font_small.render(text, True, pygame.Color(color))
                surface.blit(rendered, (x + offset, y + offset))
            return rendered

        # Startup messages bottom-left, newest at the bottom.
        y = surface.get_height() - BOOT_MARGIN
        for message in reversed(self.state.boot_messages[-BOOT_MESSAGE_COUNT:]):
            y -= font_small.get_height() + 6
            blit_shadowed(message, BOOT_MARGIN, y)

        # Firmware version bottom-right.
        version = f"v{FIRMWARE_VERSION}"
        width = font_small.size(version)[0]
        blit_shadowed(version, surface.get_width() - BOOT_MARGIN - width,
                      surface.get_height() - BOOT_MARGIN - font_small.get_height())

    def _draw(self, pygame, surface, font_big, font_small) -> None:
        if self._boot_active(time.monotonic()):
            self._draw_boot(pygame, surface, font_small)
            return
        theme = self.theme
        surface.fill(pygame.Color(theme["background"]))
        if self.state.settings_open:
            self._draw_settings(pygame, surface, font_big, font_small)
            return

        self._draw_header(pygame, surface, font_small)

        # Expression strip: only when the pedal/pot is detected; the grid
        # takes the full width otherwise (docs/08_EXPRESSION_PEDAL_SPEC.md).
        grid_width, cell_w, cell_h = self._grid_layout(surface)
        if self.state.expression_detected:
            self._draw_expression(pygame, surface, font_small, grid_width,
                                  surface.get_width() - grid_width)

        # 5x2 button panel grid below the header. Physical numbering: top row
        # B1-B5, bottom B6-B10. Hold bars are not part of the base frame; they
        # are composed per animation frame (_draw_holds).
        for i in range(GRID_COLS * GRID_ROWS):
            button_num = i + 1
            rect = self._panel_rect(pygame, button_num, cell_w, cell_h)
            self._draw_panel(pygame, surface, font_big, font_small, rect,
                             button_num, {})

    def _grid_layout(self, surface) -> tuple[int, int, int]:
        """(grid_width, cell_w, cell_h) for the panel grid below the header."""
        show_exp = self.state.expression_detected
        exp_ratio = self.state.config["ui"]["expression_panel_width_ratio"]
        exp_width = int(surface.get_width() * exp_ratio) if show_exp else 0
        grid_width = surface.get_width() - exp_width
        return (grid_width, grid_width // GRID_COLS,
                (surface.get_height() - HEADER_HEIGHT) // GRID_ROWS)

    def _panel_rect(self, pygame, button_num: int, cell_w: int, cell_h: int):
        i = button_num - 1
        col, row = i % GRID_COLS, i // GRID_COLS
        return pygame.Rect(
            col * cell_w + PANEL_MARGIN,
            HEADER_HEIGHT + row * cell_h + PANEL_MARGIN,
            cell_w - 2 * PANEL_MARGIN,
            cell_h - 2 * PANEL_MARGIN,
        )

    def _draw_panel(self, pygame, surface, font_big, font_small, rect,
                    button_num: int, holds: dict) -> None:
        """One complete panel: background, hold bar (if arming), content."""
        pygame.draw.rect(surface, pygame.Color(self.theme["panel_background"]),
                         rect, border_radius=12)
        self._draw_hold_bar(pygame, surface, rect, button_num, holds)
        if button_num == 10:
            self._draw_shift_panel(pygame, surface, font_small, rect)
        else:
            self._draw_assignable_panel(pygame, surface, font_big, font_small, rect, button_num)

    def _draw_shift_panel(self, pygame, surface, font_small, rect) -> None:
        # Shift/Menu panel: menu name with "MENU n" beneath it in the
        # small ("hold for") font, never a user assignment.
        theme = self.theme
        menu_id = self.state.current_menu
        menu = next((m for m in self.state.config["menus"] if m["id"] == menu_id), {})
        name = (menu.get("name") or f"Menu {menu_id}").upper()
        text = self._fit_text(name, rect.width - 32, 72)
        surface.blit(text, text.get_rect(centerx=rect.centerx, centery=rect.centery - 36))
        sub = font_small.render(f"MENU {menu_id}", True, pygame.Color(theme["disabled"]))
        surface.blit(sub, sub.get_rect(centerx=rect.centerx, centery=rect.centery + 14))
        # Current program as received via MIDI, shown in the rig's
        # numbering (wire value + program_display_base).
        program = self.state.current_program
        if program is not None:
            program += self.state.config["midi"]["program_display_base"]
        pgm = font_small.render(
            f"PGM {'—' if program is None else program}", True,
            pygame.Color(theme["disabled"]),
        )
        surface.blit(pgm, pgm.get_rect(centerx=rect.centerx, centery=rect.centery + 54))
        if self.state.shift_held:
            pygame.draw.rect(surface, pygame.Color(theme["text"]), rect, width=4, border_radius=12)

    def _draw_holds(self, pygame, surface, font_big, font_small, holds: dict) -> None:
        """Redraw just the panels with an arming hold bar on top of the
        blitted base frame — the only draw work per animation frame."""
        if self._boot_active(time.monotonic()) or self.state.settings_open:
            return  # no hold bars on these screens
        _grid_width, cell_w, cell_h = self._grid_layout(surface)
        for button_num in holds:
            rect = self._panel_rect(pygame, button_num, cell_w, cell_h)
            self._draw_panel(pygame, surface, font_big, font_small, rect,
                             button_num, holds)

    def _tempo_text(self, now: float) -> str:
        bpm = self.state.tempo_bpm
        if bpm is None or now - self.state.tempo_updated_at > TEMPO_STALE_SECONDS:
            return "--- BPM"
        return f"{bpm:.0f} BPM"

    def _program_label(self, wire_program: int) -> str | None:
        """Label of the first program_change assignment (any menu, primary or
        secondary) targeting the current program — names the patch in the
        header."""
        base = self.state.config["midi"]["program_display_base"]
        for menu in self.state.config["menus"]:
            for slot in menu.get("slots", {}).values():
                actions = [slot.get("primary"),
                           (slot.get("secondary") or {}).get("action")]
                for action in actions:
                    if (action and action.get("type") == "program_change"
                            and action["program_number"] - base == wire_program):
                        return action.get("label") or None
        return None

    def _draw_header(self, pygame, surface, font_small) -> None:
        """Top strip (Milestone 16): current patch on the left, tempo and
        battery/charging status in the top right."""
        theme = self.theme
        pygame.draw.line(surface, pygame.Color(theme["panel_background"]),
                         (0, HEADER_HEIGHT - 1),
                         (surface.get_width(), HEADER_HEIGHT - 1), width=2)

        program = self.state.current_program
        if program is None:
            patch = "PATCH —"
        else:
            display = program + self.state.config["midi"]["program_display_base"]
            label = self._program_label(program)
            patch = f"PATCH {display}" + (f"  ·  {label}" if label else "")
        text = font_small.render(patch, True, pygame.Color(theme["text"]))
        surface.blit(text, text.get_rect(left=16, centery=HEADER_HEIGHT // 2))

        # Right side: power/battery status rightmost, tempo to its left.
        info = battery.read()
        if info is None:
            power = "AC"  # no battery hardware yet (BMS milestone)
        else:
            power = f"{info['percent']}%" + (" CHG" if info["charging"] else "")
        right = surface.get_width() - 16
        text = font_small.render(power, True, pygame.Color(theme["text"]))
        surface.blit(text, text.get_rect(right=right, centery=HEADER_HEIGHT // 2))
        right -= text.get_width() + 48
        tempo = self._tempo_text(time.monotonic())
        color = theme["disabled"] if tempo.startswith("---") else theme["text"]
        text = font_small.render(tempo, True, pygame.Color(color))
        surface.blit(text, text.get_rect(right=right, centery=HEADER_HEIGHT // 2))

    def _draw_error_screen(self, pygame, surface, font_big, font_small) -> None:
        """Shown instead of a dead UI thread when _draw raises: the app keeps
        running (MIDI/web unaffected) and the journal has the traceback."""
        surface.fill(pygame.Color("#200000"))
        title = font_big.render("UI ERROR", True, pygame.Color("#FF5555"))
        surface.blit(title, (40, 24))
        lines = [
            "The display renderer hit an error; see the journal:",
            "    journalctl -u midi-controller",
            "MIDI and the web editor are still running.",
        ]
        for i, line in enumerate(lines):
            text = font_small.render(line, True, pygame.Color("#FFFFFF"))
            surface.blit(text, (44, 130 + i * 48))

    def _draw_assignable_panel(self, pygame, surface, font_big, font_small, rect, button_num) -> None:
        theme = self.theme
        primary = get_primary(self.state.config, self.state.current_menu, button_num)
        slot = get_slot(self.state.config, self.state.current_menu, button_num)

        secondary = get_secondary_action(slot) if slot else None

        # Content area: panel minus status bar, and minus the hint line when a
        # secondary exists — images/labels must never spill over either.
        content_bottom = rect.bottom - STATUS_BAR_HEIGHT - 16
        if secondary:
            content_bottom -= font_small.get_height() + 16
        content_center = (rect.centerx, (rect.top + 8 + content_bottom) // 2)

        # Image (if assigned and loadable) replaces the label on the display —
        # purely visual, everything else still refers to the label. Falls back
        # to the label if the asset is missing. Text auto-fits the panel.
        image = self._panel_image(
            (primary or {}).get("image_asset_id"),
            (rect.width - 32, content_bottom - rect.top - 16),
        )
        if image is not None:
            surface.blit(image, image.get_rect(center=content_center))
        else:
            label = (primary or {}).get("label") or (f"B{button_num}" if primary is None else "")
            if label:
                color = theme["disabled"] if (primary or {}).get("type") == "nothing" or primary is None else theme["text"]
                text = self._fit_text(label, rect.width - 24, 72, color)
                surface.blit(text, text.get_rect(center=content_center))
        if secondary:
            hint = font_small.render(f"Hold for {secondary.get('label', '')}", True,
                                     pygame.Color(theme["disabled"]))
            surface.blit(hint, hint.get_rect(centerx=rect.centerx, bottom=rect.bottom - STATUS_BAR_HEIGHT - 20))

        # Required bottom status rectangle, color per action type.
        status = pygame.Rect(
            rect.left + 12,
            rect.bottom - STATUS_BAR_HEIGHT - 12,
            rect.width - 24,
            STATUS_BAR_HEIGHT,
        )
        pygame.draw.rect(
            surface, self._color(self._slot_status_color(slot, button_num)),
            status, border_radius=6,
        )

    def _fit_text(self, text, max_width, start_size, color=None):
        """Render text at the largest cached font size that fits max_width
        (shared by the menu panel and, later, label auto-fit)."""
        pygame = self._pygame
        color = pygame.Color(color or self.theme["text"])
        size = start_size
        while True:
            font = self._font_cache.get(size)
            if font is None:
                font = self._font_cache[size] = pygame.font.Font(None, size)
            if font.size(text)[0] <= max_width or size <= 16:
                return font.render(text, True, color)
            size = max(16, int(size * 0.85))

    def _draw_hold_bar(self, pygame, surface, rect, button_num, holds: dict) -> None:
        """Light gray progress fill growing upward from the panel bottom while
        a hold action is arming (buttons with a secondary, and Shift toward
        Menu 4). Drawn right after the panel background so text/status sit on
        top of it. `holds` is the loop's snapshot of state.hold_started."""
        started = holds.get(button_num)
        if started is None:
            return
        fraction = hold_progress(started[0], started[1], time.monotonic())
        fill_h = int(rect.height * fraction)
        if fill_h <= 0:
            return
        fill = pygame.Rect(rect.left, rect.bottom - fill_h, rect.width, fill_h)
        radius = 12 if fill_h >= rect.height else 0
        pygame.draw.rect(surface, pygame.Color(HOLD_BAR_COLOR), fill,
                         border_radius=radius,
                         border_bottom_left_radius=12, border_bottom_right_radius=12)

    def _panel_image(self, asset_id, max_size):
        """Loaded + aspect-fit-scaled Surface for an asset id, or None. The
        scaled result is cached per target size (panel sizes are stable
        between frames)."""
        if not asset_id:
            return None
        pygame = self._pygame
        if asset_id not in self._image_cache:
            try:
                self._image_cache[asset_id] = pygame.image.load(
                    str(image_path(asset_id))).convert_alpha()
            except Exception as e:
                log.warning("image %s failed to load: %s", asset_id, e)
                self._image_cache[asset_id] = None
        original = self._image_cache[asset_id]
        if original is None:
            return None
        max_w, max_h = max(int(max_size[0]), 1), max(int(max_size[1]), 1)
        key = (asset_id, max_w, max_h)
        if key not in self._scaled_cache:
            w, h = original.get_size()
            scale = min(max_w / w, max_h / h)
            self._scaled_cache[key] = pygame.transform.smoothscale(
                original, (max(int(w * scale), 1), max(int(h * scale), 1)))
        return self._scaled_cache[key]

    def _color(self, value):
        """pygame.Color for a stored color (resolves palette references)."""
        return self._pygame.Color(resolve_color(self.state.config, value))

    def _slot_status_color(self, slot: dict | None, button_num: int) -> str:
        """Status bar color for the whole slot (docs/03_UI_SPEC.md).

        Primary actions carry off_color + on_color; secondaries carry
        on_color only. Secondary active -> its on_color; primary active ->
        its on_color; BOTH active -> flicker between the two on_colors with
        a 2 s period; neither -> the primary's off_color.
        """
        primary = slot.get("primary") if slot else None
        if primary is None:
            return self.theme["disabled"]
        secondary = get_secondary_action(slot)
        p_active = self._action_active(primary, button_num, "primary")
        s_active = secondary is not None and self._action_active(secondary, button_num, "secondary")
        if p_active and s_active:
            first_half = time.monotonic() % FLICKER_PERIOD_S < FLICKER_PERIOD_S / 2
            return primary["on_color"] if first_half else secondary["on_color"]
        if s_active:
            return secondary["on_color"]
        if p_active:
            return primary["on_color"]
        return primary.get("off_color") or primary.get("color") or self.theme["disabled"]

    def _action_active(self, action: dict, button_num: int, role: str) -> bool:
        state = self.state
        kind = action.get("type")
        if kind == "effect_cc":
            return bool(state.effect_states.get((action["midi_channel"], action["cc_number"])))
        if kind == "action_cc":
            if role == "secondary":
                return button_num in state.secondary_pressed
            return (button_num in state.pressed_buttons
                    and button_num not in state.secondary_pressed)
        if kind == "program_change":
            base = state.config["midi"]["program_display_base"]
            return state.current_program == action["program_number"] - base
        if kind == "expression_pedal":
            return state.effective_expression_mode() == (state.current_menu, button_num, role)
        return False  # nothing

    def _draw_expression(self, pygame, surface, font_small, grid_width, exp_width) -> None:
        theme = self.theme
        action = self.state.get_expression_action()
        exp_rect = pygame.Rect(
            grid_width + PANEL_MARGIN,
            HEADER_HEIGHT + PANEL_MARGIN,
            exp_width - 2 * PANEL_MARGIN,
            surface.get_height() - HEADER_HEIGHT - 2 * PANEL_MARGIN,
        )
        pygame.draw.rect(surface, pygame.Color(theme["panel_background"]), exp_rect, border_radius=12)

        label_text = action.get("label", "EXP") if action else "EXP"
        bar_color = action.get("on_color", "#3399FF") if action else theme["disabled"]
        # Expression assignments can carry an image too (Milestone 13); it
        # replaces the label at the top of the strip, fit to the strip width.
        image = self._panel_image(
            (action or {}).get("image_asset_id"), (exp_rect.width - 20, 80))
        if image is not None:
            surface.blit(image, image.get_rect(centerx=exp_rect.centerx, top=exp_rect.top + 12))
        else:
            label = self._fit_text(label_text, exp_rect.width - 16, 36)
            surface.blit(label, label.get_rect(centerx=exp_rect.centerx, top=exp_rect.top + 16))

        bar = exp_rect.inflate(-exp_rect.width // 2, -120)
        bar.bottom = exp_rect.bottom - 16
        pygame.draw.rect(surface, pygame.Color(theme["disabled"]), bar, border_radius=8)

        value = self.state.expression_value
        reverse = bool(action and action.get("reverse"))
        fill_h = int(bar.height * value)
        if fill_h > 0:
            if reverse:  # bar grows from the top when reversed
                fill = pygame.Rect(bar.left, bar.top, bar.width, fill_h)
            else:
                fill = pygame.Rect(bar.left, bar.bottom - fill_h, bar.width, fill_h)
            pygame.draw.rect(surface, self._color(bar_color), fill, border_radius=8)

        # Home value marker line (docs/08: value rendered as distance from home).
        if action and action.get("has_home"):
            span = max(action["value_max"] - action["value_min"], 1)
            home_frac = (action["home_value"] - action["value_min"]) / span
            if reverse:
                home_frac = 1.0 - home_frac
            y = bar.bottom - int(bar.height * home_frac)
            pygame.draw.line(surface, pygame.Color(theme["text"]),
                             (bar.left - 8, y), (bar.right + 8, y), width=3)

    def _draw_settings(self, pygame, surface, font_big, font_small) -> None:
        theme = self.theme
        in_presets = self.state.settings_view == "presets"
        title = font_big.render("PRESETS" if in_presets else "SETTINGS",
                                True, pygame.Color(theme["text"]))
        surface.blit(title, (40, 24))

        # (label, value) rows from SettingsLogic, label left / value right,
        # scrolled so the selected row stays visible (preset lists can be
        # longer than the screen).
        rows = self.state.settings_rows or [("…", "")]
        index = min(self.state.settings_index, len(rows) - 1)
        item_top, item_h, list_width = 100, 46, 1300
        max_visible = max((surface.get_height() - item_top - 10) // item_h, 1)
        first = max(0, index - max_visible + 1)
        for i, (label, value) in enumerate(rows[first:first + max_visible]):
            selected = first + i == index
            y = item_top + i * item_h
            if selected:
                row = pygame.Rect(32, y - 6, list_width, item_h)
                pygame.draw.rect(surface, pygame.Color(theme["panel_background"]), row, border_radius=8)
            color = pygame.Color(theme["text"] if selected else theme["disabled"])
            text = font_small.render(("> " if selected else "  ") + label, True, color)
            surface.blit(text, (48, y))
            if value:
                val = font_small.render(str(value), True, color)
                surface.blit(val, val.get_rect(right=32 + list_width - 24, top=y))

        # Footswitch legend, right side (B6/B7/B9/B10 per logic/settings.py).
        legend = ["B6  up", "B7  down", "B9  select",
                  "B10 back" if in_presets else "B10 exit"]
        for i, line in enumerate(legend):
            text = font_small.render(line, True, pygame.Color(theme["text"]))
            surface.blit(text, (surface.get_width() - 360, 110 + i * 52))
