"""SPI ADC potentiometer + expression detect pin — hardware only.

ADC chip: MCP3008 (10-bit, SPI mode 0), confirmed wired on SPI0 — pins in
hardware/constants.py.

A poll thread reads the pot every poll_interval_ms, normalizes to 0.0-1.0
with light exponential smoothing, and writes state.expression_value. The
detect pin (low = plugged in) drives state.expression_detected, which the UI
uses to show/hide the expression strip.
"""

import logging
import threading

from hardware.constants import (
    GPIO_EXPRESSION_DETECT,
    SPI_ADC_BUS,
    SPI_ADC_CHANNEL_POT,
    SPI_ADC_DEVICE,
)

log = logging.getLogger("controller.hw.adc")

ADC_MAX = 1023  # MCP3008
SMOOTHING_ALPHA = 0.3
SPI_HZ = 1_350_000


class ExpressionInput:
    def __init__(self, config: dict, state):
        self.config = config
        self.state = state
        self.poll_s = config["expression"]["poll_interval_ms"] / 1000.0
        self.detect_enabled = config["expression"]["detect_enabled"]
        self._spi = None
        self._detect = None
        self._thread: threading.Thread | None = None
        self._running = False
        self._smoothed: float | None = None

    def start(self) -> bool:
        try:
            import spidev
        except ImportError as e:
            log.error("spidev unavailable, expression input disabled: %s", e)
            return False
        try:
            self._spi = spidev.SpiDev()
            self._spi.open(SPI_ADC_BUS, SPI_ADC_DEVICE)
            self._spi.max_speed_hz = SPI_HZ
        except OSError as e:
            log.error("SPI open failed (is dtparam=spi=on set?): %s", e)
            self._spi = None
            return False

        if self.detect_enabled:
            try:
                from gpiozero import DigitalInputDevice
                self._detect = DigitalInputDevice(GPIO_EXPRESSION_DETECT, pull_up=True)
                # pull_up=True: is_active means pin low = plugged in.
                self._detect.when_activated = self._on_detect_change
                self._detect.when_deactivated = self._on_detect_change
                self._on_detect_change()
            except Exception as e:
                log.error("expression detect pin init failed: %s", e)
                self._detect = None
        else:
            self.state.expression_detected = True

        self._running = True
        self._thread = threading.Thread(target=self._poll, name="adc", daemon=True)
        self._thread.start()
        log.info("expression input started (detect=%s)", self.state.expression_detected)
        return True

    def stop(self) -> None:
        self._running = False
        if self._thread:
            self._thread.join(timeout=1)
        if self._spi:
            self._spi.close()
        if self._detect:
            self._detect.close()

    def _on_detect_change(self) -> None:
        detected = bool(self._detect.is_active)
        if detected != self.state.expression_detected:
            self.state.expression_detected = detected
            log.info("expression %s", "detected" if detected else "removed")

    def _read_raw(self) -> int:
        # MCP3008 single-ended read.
        r = self._spi.xfer2([1, (8 + SPI_ADC_CHANNEL_POT) << 4, 0])
        return ((r[1] & 3) << 8) | r[2]

    def _poll(self) -> None:
        import time
        while self._running:
            try:
                raw = self._read_raw()
            except OSError as e:
                log.error("ADC read failed, stopping: %s", e)
                return
            # Unplugged, the pot input floats and reads noise. With
            # retain_pedal_value the last reading stands instead — the effect
            # the pedal was driving stays where the player left it. Read live
            # so the web toggle takes effect without a restart.
            if (self.state.expression_detected
                    or not self.config["expression"].get("retain_pedal_value")):
                value = raw / ADC_MAX
                if self._smoothed is None:
                    self._smoothed = value
                else:
                    self._smoothed += SMOOTHING_ALPHA * (value - self._smoothed)
                self.state.expression_value = self._smoothed
            time.sleep(self.poll_s)
