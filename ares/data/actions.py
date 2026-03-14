# ares/data/actions.py
# Action ID -> human-readable name lookup table for FFXIV combat actions.

ACTION_NAMES: dict[int, str] = {
    # Common
    0x07: "Attack",

    # DRK (Dark Knight)
    0xE21: "Hard Slash",
    0xE27: "Syphon Strike",
    0xE30: "Souleater",
    0x1CE0: "Bloodspiller",
    0x4056: "Edge of Shadow",
    0x649D: "Shadowbringer",
    0xE28: "Unmend",
    0x1CE1: "Quietus",
    0xE36: "Unleash",
    0x4057: "Flood of Shadow",
    0xE34: "Abyssal Drain",

    # DRG (Dragoon)
    0x4B: "True Thrust",
    0x9058: "Drakesbane",
    0x405F: "Raiden Thrust",
    0x905A: "Lance Barrage",
    0xDE4: "Wheeling Thrust",
    0xDE2: "Fang and Claw",
    0x64AC: "Chaotic Spring",
    0x64AB: "Heavens' Thrust",
    0x905B: "Spiral Blow",
    0x64AD: "Wyrmwind Thrust",
    0x1CE7: "Mirage Dive",
    0x405E: "High Jump",
    0x1CE8: "Nastrond",
    0xDE3: "Geirskogul",
    0x60: "Dragonfire Dive",
    0x4060: "Stardiver",
    0x905C: "Starcross",
    0x9059: "Rise of the Dragon",
    0xDE5: "Battle Litany",
    0x55: "Lance Charge",
    0x53: "Life Surge",
}


def get_action_name(action_id: int) -> str:
    """Return the human-readable name for an action ID, or a hex fallback."""
    return ACTION_NAMES.get(action_id, f"Action_{action_id:X}")
