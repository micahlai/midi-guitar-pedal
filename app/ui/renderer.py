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

from config.model import get_primary, get_secondary_action, get_slot, resolve_color
from web.images import image_path
from hardware.constants import DISPLAY_HEIGHT, DISPLAY_WIDTH
from logic.settings import SETTINGS_ITEMS
from state.manager import StateManager
from ui.gles import CanvasPresenter

log = logging.getLogger("controller.ui")

FPS = 30
GRID_COLS = 5
GRID_ROWS = 2
PANEL_MARGIN = 8
STATUS_BAR_HEIGHT = 22
FLICKER_PERIOD_S = 2.0  # primary+secondary both active -> alternate on_colors
SCREENSHOT_PATH = "/tmp/controller-frame.png"

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
            # for debugging); if none fits, keep the current mode (cropped).
            fitting = [
                m for m in (pygame.display.list_modes() or [])
                if m[0] >= DISPLAY_WIDTH and m[1] >= DISPLAY_HEIGHT
            ]
            target = min(fitting, key=lambda m: m[0] * m[1]) if fitting else (0, 0)
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
        try:
            presenter = CanvasPresenter((w, h), canvas.get_size())
        except (OSError, RuntimeError) as e:
            log.error("GLES presenter init failed: %s", e)
            pygame.quit()
            return
        log.info(
            "display up: mode %dx%d, driver %s, UI canvas %dx%d centered",
            w, h, pygame.display.get_driver(), DISPLAY_WIDTH, DISPLAY_HEIGHT,
        )

        font_big = pygame.font.Font(None, 72)
        font_small = pygame.font.Font(None, 36)
        self._font_cache = {72: font_big, 36: font_small}
        self._pygame = pygame
        clock = pygame.time.Clock()

        while self._running:
            pygame.event.pump()
            self._draw(pygame, canvas, font_big, font_small)
            presenter.present(pygame.image.tobytes(canvas, "RGBA"))
            pygame.display.flip()
            if self.screenshot_requested:
                self.screenshot_requested = False
                pygame.image.save(canvas, SCREENSHOT_PATH)
                log.info("frame saved to %s", SCREENSHOT_PATH)
            clock.tick(FPS)

        pygame.quit()

    def _draw(self, pygame, surface, font_big, font_small) -> None:
        theme = self.theme
        surface.fill(pygame.Color(theme["background"]))
        if self.state.settings_open:
            self._draw_settings(pygame, surface, font_big, font_small)
            return

        # Expression strip: only when the pedal/pot is detected; the grid
        # takes the full width otherwise (docs/08_EXPRESSION_PEDAL_SPEC.md).
        show_exp = self.state.expression_detected
        exp_ratio = self.state.config["ui"]["expression_panel_width_ratio"]
        exp_width = int(surface.get_width() * exp_ratio) if show_exp else 0
        grid_width = surface.get_width() - exp_width
        if show_exp:
            self._draw_expression(pygame, surface, font_small, grid_width, exp_width)

        # 5x2 button panel grid. Physical numbering: top row B1-B5, bottom B6-B10.
        cell_w = grid_width // GRID_COLS
        cell_h = surface.get_height() // GRID_ROWS
        for i in range(GRID_COLS * GRID_ROWS):
            col, row = i % GRID_COLS, i // GRID_COLS
            button_num = i + 1
            rect = pygame.Rect(
                col * cell_w + PANEL_MARGIN,
                row * cell_h + PANEL_MARGIN,
                cell_w - 2 * PANEL_MARGIN,
                cell_h - 2 * PANEL_MARGIN,
            )
            pygame.draw.rect(surface, pygame.Color(theme["panel_background"]), rect, border_radius=12)
            self._draw_hold_bar(pygame, surface, rect, button_num)

            if button_num == 10:
                # Shift/Menu panel: menu name with "MENU n" beneath it in the
                # small ("hold for") font, never a user assignment.
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
            else:
                self._draw_assignable_panel(pygame, surface, font_big, font_small, rect, button_num)

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

    def _draw_hold_bar(self, pygame, surface, rect, button_num) -> None:
        """Light gray progress fill growing upward from the panel bottom while
        a hold action is arming (buttons with a secondary, and Shift toward
        Menu 4). Drawn right after the panel background so text/status sit on
        top of it."""
        started = self.state.hold_started.get(button_num)
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
            return state.expression_mode == (state.current_menu, button_num, role)
        return False  # nothing

    def _draw_expression(self, pygame, surface, font_small, grid_width, exp_width) -> None:
        theme = self.theme
        action = self.state.get_expression_action()
        exp_rect = pygame.Rect(
            grid_width + PANEL_MARGIN,
            PANEL_MARGIN,
            exp_width - 2 * PANEL_MARGIN,
            surface.get_height() - 2 * PANEL_MARGIN,
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
        title = font_big.render("SETTINGS", True, pygame.Color(theme["text"]))
        surface.blit(title, (40, 24))

        # Item list with highlight on the selected row.
        item_top, item_h = 110, 52
        for i, item in enumerate(SETTINGS_ITEMS):
            selected = i == self.state.settings_index
            if selected:
                row = pygame.Rect(32, item_top + i * item_h - 6, 700, item_h)
                pygame.draw.rect(surface, pygame.Color(theme["panel_background"]), row, border_radius=8)
            color = theme["text"] if selected else theme["disabled"]
            text = font_small.render(("> " if selected else "  ") + item, True, pygame.Color(color))
            surface.blit(text, (48, item_top + i * item_h))

        # Footswitch legend, right side (B6/B7/B9/B10 per logic/settings.py).
        legend = ["B6  up", "B7  down", "B9  select", "B10 exit"]
        for i, line in enumerate(legend):
            text = font_small.render(line, True, pygame.Color(theme["text"]))
            surface.blit(text, (surface.get_width() - 360, 110 + i * 52))
