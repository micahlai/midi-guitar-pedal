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

from hardware.constants import DISPLAY_HEIGHT, DISPLAY_WIDTH
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

        # Expression strip placeholder on the right (hidden when not detected
        # in later milestones; always drawn for bring-up).
        show_exp = True
        exp_width = int(surface.get_width() * self.exp_ratio) if show_exp else 0
        grid_width = surface.get_width() - exp_width

        if show_exp:
            exp_rect = pygame.Rect(
                grid_width + PANEL_MARGIN,
                PANEL_MARGIN,
                exp_width - 2 * PANEL_MARGIN,
                surface.get_height() - 2 * PANEL_MARGIN,
            )
            pygame.draw.rect(surface, pygame.Color(theme["panel_background"]), exp_rect, border_radius=12)
            label = font_small.render("EXP", True, pygame.Color(theme["text"]))
            surface.blit(label, label.get_rect(centerx=exp_rect.centerx, top=exp_rect.top + 16))
            # Placeholder vertical bar at current expression value.
            bar = exp_rect.inflate(-exp_rect.width // 2, -120)
            bar.bottom = exp_rect.bottom - 16
            pygame.draw.rect(surface, pygame.Color(theme["disabled"]), bar, border_radius=8)
            fill_h = int(bar.height * self.state.expression_value)
            if fill_h > 0:
                fill = pygame.Rect(bar.left, bar.bottom - fill_h, bar.width, fill_h)
                pygame.draw.rect(surface, pygame.Color("#3399FF"), fill, border_radius=8)

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
                text = font_big.render(f"B{button_num}", True, pygame.Color(theme["text"]))
                surface.blit(text, text.get_rect(center=rect.center))
                # Required bottom status rectangle (placeholder color for now).
                status = pygame.Rect(
                    rect.left + 12,
                    rect.bottom - STATUS_BAR_HEIGHT - 12,
                    rect.width - 24,
                    STATUS_BAR_HEIGHT,
                )
                pygame.draw.rect(surface, pygame.Color(theme["disabled"]), status, border_radius=6)
