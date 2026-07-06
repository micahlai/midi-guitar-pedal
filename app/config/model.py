"""Typed access helpers for the config JSON (menus, slots, actions).

Slot shape (docs/12_CONFIG_SCHEMA_DRAFT.md): menus[].slots is keyed by the
physical button number as a string ("1".."9"), each value holding "primary"
(an action dict with a "type") and optional "secondary".

Action types (docs/07_ACTION_TYPES_SPEC.md): effect_cc, action_cc,
program_change, expression_pedal, nothing.
"""

ACTION_TYPES = ("effect_cc", "action_cc", "program_change", "expression_pedal", "nothing")

PALETTE_SIZE = 10


def resolve_color(config: dict, value, fallback: str = "#303030") -> str:
    """Resolve a stored color to a #RRGGBB hex. Colors are either literal hex
    or "palette:N" references into ui.color_palette (Milestone 12.5)."""
    if isinstance(value, str) and value.startswith("palette:"):
        try:
            return config["ui"]["color_palette"][int(value.split(":", 1)[1])]
        except (ValueError, IndexError, KeyError):
            return fallback
    return value or fallback


def get_menu(config: dict, menu_id: int) -> dict | None:
    for menu in config["menus"]:
        if menu["id"] == menu_id:
            return menu
    return None


def get_slot(config: dict, menu_id: int, button_num: int) -> dict | None:
    menu = get_menu(config, menu_id)
    if menu is None:
        return None
    return menu.get("slots", {}).get(str(button_num))


def get_primary(config: dict, menu_id: int, button_num: int) -> dict | None:
    slot = get_slot(config, menu_id, button_num)
    if slot is None:
        return None
    return slot.get("primary")


def get_secondary_action(slot: dict) -> dict | None:
    secondary = slot.get("secondary")
    if secondary and secondary.get("enabled"):
        return secondary.get("action")
    return None


def iter_effect_cc_actions(config: dict):
    """Yield (menu_id, button_num, action) for every effect_cc assignment —
    used to update effect state from incoming CC feedback."""
    for menu in config["menus"]:
        for button_str, slot in menu.get("slots", {}).items():
            for action in filter(None, (slot.get("primary"), get_secondary_action(slot))):
                if action.get("type") == "effect_cc":
                    yield menu["id"], int(button_str), action
