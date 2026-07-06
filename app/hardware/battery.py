"""Battery/charging status readout.

Placeholder until the battery/BMS milestone: there is no fuel gauge wired
yet, so read() reports no battery and the UI shows mains power. When the BMS
lands, return {"percent": int, "charging": bool} here and the header picks
it up unchanged.
"""


def read() -> dict | None:
    """{"percent": 0-100, "charging": bool} or None when no battery
    hardware is present."""
    return None
