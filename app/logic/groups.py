"""Selection groups — one-of-N latching for action_cc buttons (Milestone 18).

An action_cc is normally momentary: its on_color shows only while the switch is
held. Assign it to a selection group and it latches instead — pressing it lights
it and un-lights whichever member of that group was lit before, so a group of
buttons behaves like a radio button set ("Pad Key": C, D, E).

This module is pure bookkeeping: it remembers which of a group's members was
pressed last, so the renderer can keep that one's on_color up and the header can
name it. Nothing here sends MIDI.

The one place a group does reach the wire is logic/actions.py, which sends
velocity 0 for the member losing the selection as the new one is turned on —
one member on at a time on the rig, not just on the display. Pressing a member
still fires exactly the note it always did; the 0 is additional, never a
substitute.

There are always GROUP_COUNT groups; a preset only edits their names (an empty
name means the group is unused). The selection itself is runtime state, not
config — it starts empty on boot ("Pad Key — None") and is never persisted.

The selection is stored as the (menu, button, role) that was pressed, and is
resolved back through the config on every read (selected_action). That way a
button that is re-assigned, moved out of the group, or deleted under a live
selection simply stops matching, instead of leaving a phantom name in the
header or a lit button that can no longer be un-lit.
"""

GROUP_COUNT = 5

# Header item keys ("group1".."group5") and the labels the pickers show. The
# group's own name is what the header DISPLAYS; these name the slot itself, so
# an unnamed group is still findable in the list.
GROUP_KEYS = tuple(f"group{index}" for index in range(1, GROUP_COUNT + 1))
GROUP_ITEMS = tuple(
    (key, f"Selection Group {index}")
    for index, key in enumerate(GROUP_KEYS, start=1)
)


def key_to_index(key: str) -> int | None:
    """"group3" -> 3. None if it is not a group key."""
    return GROUP_KEYS.index(key) + 1 if key in GROUP_KEYS else None


def normalize_names(names) -> list[str]:
    """Exactly GROUP_COUNT names from whatever the config holds — a hand-edited
    list that is short, long or full of junk must not break the UI."""
    clean = [""] * GROUP_COUNT
    if isinstance(names, list):
        for index, name in enumerate(names[:GROUP_COUNT]):
            if isinstance(name, str):
                clean[index] = name.strip()
    return clean


def group_names(config: dict) -> list[str]:
    return normalize_names(config.get("selection_groups"))


def group_name(config: dict, index: int) -> str:
    """The user's name for group `index` (1-based), or a placeholder so an
    unnamed group still reads as something in the header."""
    names = group_names(config)
    if not 1 <= index <= GROUP_COUNT:
        return ""
    return names[index - 1] or f"Group {index}"


def action_group(action: dict | None) -> int | None:
    """The group an action_cc belongs to, or None. Only action_cc can latch:
    effect_cc already shows real feedback state, and the others are not
    on/off things at all."""
    if not action or action.get("type") != "action_cc":
        return None
    index = action.get("selection_group")
    if isinstance(index, bool) or not isinstance(index, int):
        return None
    return index if 1 <= index <= GROUP_COUNT else None


def select(state, index: int, menu: int, button: int, role: str) -> None:
    """Remember that this button is the group's current selection, replacing
    whichever member was selected before."""
    state.group_selection[index] = (menu, button, role)


def is_selected(state, index: int, menu: int, button: int, role: str) -> bool:
    return state.group_selection.get(index) == (menu, button, role)


def selected_action(config: dict, state, index: int) -> dict | None:
    """The action currently selected in group `index`, re-resolved through the
    config so an edited or deleted button drops out of the group by itself."""
    from config.model import get_secondary_action, get_slot  # circular at import

    selection = state.group_selection.get(index)
    if selection is None:
        return None
    menu, button, role = selection
    slot = get_slot(config, menu, button)
    if slot is None:
        return None
    action = slot.get("primary") if role == "primary" else get_secondary_action(slot)
    return action if action_group(action) == index else None


def selected_label(config: dict, state, index: int) -> str | None:
    """What to call the current selection: its label, or its note number when
    it has none (an unlabelled button still has to be identifiable)."""
    action = selected_action(config, state, index)
    if action is None:
        return None
    return (action.get("label") or "").strip() or f"CC {action['cc_number']}"


def header_text(config: dict, state, index: int) -> str:
    """"Pad Key - C", or "Pad Key - None" before anything in it is pressed."""
    return f"{group_name(config, index)} - {selected_label(config, state, index) or 'None'}"
