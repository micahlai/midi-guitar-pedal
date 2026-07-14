"""Phone-style multi-tap text entry on the ten footswitches.

Wi-Fi passwords have to be typeable with nothing but the pedal: the USB port
is a device port whenever the MIDI gadget owns it, so a keyboard may not be
attachable at all. Tapping a key repeatedly cycles through its characters,
exactly like a feature-phone keypad.

    B1  0-9              B6   symbols
    B2  a b c d e f g    B7   SHIFT (sticky: abc -> ABC)
    B3  h i j k l m n    B8   DELETE (left of cursor)
    B4  o p q r s t u    B9   cursor left
    B5  v w x y z        B10  cursor right
                         POWER  confirm (handled by the caller)

A tap on the SAME key within MULTITAP_SECONDS rewrites the character just
typed; anything else (a different key, a cursor move, or the timeout) commits
it and the next tap starts a new character. Pure logic — no pygame, no
hardware, no clock of its own: the caller passes `now`.
"""

MULTITAP_SECONDS = 1.0

DIGITS = "0123456789"
SYMBOLS = ".,-_@#!?$%&*+=/:;'\"()[]{}<>~^`|\\ "

# Button -> the characters it cycles through, in tap order.
CHAR_KEYS = {
    1: DIGITS,
    2: "abcdefg",
    3: "hijklmn",
    4: "opqrstu",
    5: "vwxyz",
    6: SYMBOLS,
}
KEY_SHIFT = 7
KEY_DELETE = 8
KEY_LEFT = 9
KEY_RIGHT = 10

# On-screen legend, laid out as the pedal physically is: B1-B5 across the top
# row, B6-B10 across the bottom. Drawn as a 2x5 grid so a glance at the screen
# maps straight onto the switch under your foot.
LEGEND_ROWS = (
    ((1, "0-9"), (2, "abcdefg"), (3, "hijklmn"), (4, "opqrstu"), (5, "vwxyz")),
    ((6, ". , - _ @ #"), (KEY_SHIFT, "SHIFT"), (KEY_DELETE, "DELETE"),
     (KEY_LEFT, "◀"), (KEY_RIGHT, "▶")),
)


class MultiTapKeypad:
    """Editable text buffer driven by footswitch presses."""

    def __init__(self, max_chars: int = 63):
        self.max_chars = max_chars
        self.reset()

    def reset(self) -> None:
        self.text = ""
        self.cursor = 0
        self.shift = False
        # The character still open to rewriting by another tap on the same key.
        self._pending_key: int | None = None
        self._pending_at = 0.0
        self._pending_index = 0
        self._pending_position = -1

    def _clear_pending(self) -> None:
        self._pending_key = None
        self._pending_position = -1

    def press(self, button: int, now: float) -> None:
        if button == KEY_SHIFT:
            self.shift = not self.shift
            self._clear_pending()
        elif button == KEY_DELETE:
            self._clear_pending()
            if self.cursor > 0:
                self.text = self.text[:self.cursor - 1] + self.text[self.cursor:]
                self.cursor -= 1
        elif button == KEY_LEFT:
            self._clear_pending()
            self.cursor = max(0, self.cursor - 1)
        elif button == KEY_RIGHT:
            self._clear_pending()
            self.cursor = min(len(self.text), self.cursor + 1)
        elif button in CHAR_KEYS:
            self._type(button, now)

    def insert(self, character: str) -> None:
        """Type one character outright (USB keyboard path) — no multi-tap."""
        if len(self.text) >= self.max_chars:
            return
        self.text = (self.text[:self.cursor] + character
                     + self.text[self.cursor:])
        self.cursor += 1
        self._clear_pending()

    def _type(self, button: int, now: float) -> None:
        characters = CHAR_KEYS[button]
        cycling = (button == self._pending_key
                   and now - self._pending_at < MULTITAP_SECONDS
                   and self._pending_position == self.cursor - 1)
        if cycling:
            self._pending_index = (self._pending_index + 1) % len(characters)
            character = self._shifted(characters[self._pending_index])
            position = self._pending_position
            self.text = self.text[:position] + character + self.text[position + 1:]
        else:
            if len(self.text) >= self.max_chars:
                return
            self._pending_index = 0
            character = self._shifted(characters[0])
            self.text = self.text[:self.cursor] + character + self.text[self.cursor:]
            self.cursor += 1
            self._pending_position = self.cursor - 1
        self._pending_key = button
        self._pending_at = now

    def _shifted(self, character: str) -> str:
        return character.upper() if self.shift else character
