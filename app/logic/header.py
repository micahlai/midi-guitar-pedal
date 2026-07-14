"""What the header strip shows, and where — config["ui"]["header"].

Five positions across the top of the screen, left to right, each holding at
most one item; each item appears at most once. The pedal has five switches in
a row, so B1..B5 map straight onto the five positions: highlight an item in
the popup, press the switch under the spot you want it.

    slots = [far left, left, middle, right, far right]

`assign()` keeps both halves of that invariant: putting an item somewhere
vacates wherever it used to be, and evicts whatever used to be there. Pure
logic — the settings popup and the renderer both read the same list.
"""

# (key, menu label) in the popup's display order.
HEADER_ITEMS = (
    ("patch", "Patch"),
    ("bpm", "BPM"),
    ("network", "Network status"),
    ("midi", "MIDI status"),
    ("preset", "Preset name"),
)
ITEM_KEYS = tuple(key for key, _ in HEADER_ITEMS)

# Position index -> the name shown in the menu, and the switch that picks it.
POSITION_NAMES = ("far left", "left", "middle", "right", "far right")
SLOT_COUNT = len(POSITION_NAMES)


def normalize(slots) -> list:
    """A well-formed 5-slot list from whatever is in the config: wrong length,
    unknown keys and duplicates all get cleaned up rather than crashing the
    renderer on a hand-edited config.json."""
    clean: list = [None] * SLOT_COUNT
    seen: set = set()
    if isinstance(slots, list):
        for index, item in enumerate(slots[:SLOT_COUNT]):
            if item in ITEM_KEYS and item not in seen:
                clean[index] = item
                seen.add(item)
    return clean


def assign(slots, item: str, position: int) -> list:
    """Put `item` at `position`. Whatever was there is dropped, and the item's
    previous position is vacated — one item, one place, both directions."""
    clean = normalize(slots)
    if item not in ITEM_KEYS or not 0 <= position < SLOT_COUNT:
        return clean
    for index, existing in enumerate(clean):
        if existing == item:
            clean[index] = None  # vacate where it used to live
    clean[position] = item  # evicts whatever occupied this spot
    return clean


def clear(slots, item: str) -> list:
    """Remove an item from the header entirely."""
    clean = normalize(slots)
    return [None if existing == item else existing for existing in clean]


def position_of(slots, item: str) -> int | None:
    clean = normalize(slots)
    return clean.index(item) if item in clean else None
