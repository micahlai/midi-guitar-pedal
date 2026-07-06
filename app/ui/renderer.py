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

from config.model import get_primary, get_secondary_action, get_slot
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
SCREENSHOT_PATH = "/tmp/controller-frame.png"


class UiRenderer:
    def __init__(self, state: StateManager):
        self.state = state
        self.theme = state.config["ui"]["theme"]
        self.exp_ratio = state.config["ui"]["expression_panel_width_ratio"]
        self._thread: threading.Thread | None = None
        self._running = False
        self.screenshot_requested = False

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
        exp_width = int(surface.get_width() * self.exp_ratio) if show_exp else 0
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

            if button_num == 10:
                # Shift/Menu panel: shows menu state, never a user assignment.
                text = font_big.render(f"MENU {self.state.current_menu}", True, pygame.Color(theme["text"]))
                surface.blit(text, text.get_rect(center=rect.center))
                if self.state.shift_held:
                    pygame.draw.rect(surface, pygame.Color(theme["text"]), rect, width=4, border_radius=12)
            else:
                self._draw_assignable_panel(pygame, surface, font_big, font_small, rect, button_num)

    def _draw_assignable_panel(self, pygame, surface, font_big, font_small, rect, button_num) -> None:
        theme = self.theme
        primary = get_primary(self.state.config, self.state.current_menu, button_num)
        slot = get_slot(self.state.config, self.state.current_menu, button_num)

        label = (primary or {}).get("label") or (f"B{button_num}" if primary is None else "")
        if label:
            color = theme["disabled"] if (primary or {}).get("type") == "nothing" or primary is None else theme["text"]
            text = font_big.render(label, True, pygame.Color(color))
            surface.blit(text, text.get_rect(center=(rect.centerx, rect.centery - 12)))

        # Optional secondary-action hint.
        secondary = get_secondary_action(slot) if slot else None
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
        pygame.draw.rect(surface, pygame.Color(self._status_color(primary, button_num)), status, border_radius=6)

    def _status_color(self, primary: dict | None, button_num: int) -> str:
        """Status bar color per docs/03_UI_SPEC.md."""
        theme = self.theme
        if primary is None:
            return theme["disabled"]
        state = self.state
        kind = primary.get("type")
        if kind == "effect_cc":
            key = (primary["midi_channel"], primary["cc_number"])
            return primary["on_color"] if state.effect_states.get(key) else primary["off_color"]
        if kind == "action_cc":
            pressed = button_num in state.pressed_buttons
            return primary["pressed_color"] if pressed else primary["default_color"]
        if kind == "program_change":
            active = state.current_program == primary["program_number"]
            return primary["active_color"] if active else primary["inactive_color"]
        if kind == "expression_pedal":
            active = state.expression_mode == (state.current_menu, button_num)
            return primary["color"] if active else theme["disabled"]
        return primary.get("color") or theme["disabled"]  # nothing

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
        bar_color = action.get("color", "#3399FF") if action else theme["disabled"]
        label = font_small.render(label_text, True, pygame.Color(theme["text"]))
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
            pygame.draw.rect(surface, pygame.Color(bar_color), fill, border_radius=8)

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
