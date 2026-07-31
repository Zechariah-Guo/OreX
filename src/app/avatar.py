"""Avatar colour utilities for OreX.

Provides a palette of 9 ore-themed colours used for default avatar backgrounds.
Players get a random colour assigned at registration; bots get a deterministic
colour derived from their username.
"""

import hashlib
import random

# Ore-themed avatar background colours
AVATAR_COLORS = {
    'coal': '#4a4a4a',        # dark grey
    'iron': '#d4c5a0',        # beige
    'copper': '#b87333',      # orange-brown
    'gold': '#ffd700',        # yellow
    'lapis': '#1f4fa3',       # blue
    'redstone': '#cc2222',    # red
    'emerald': '#2ecc71',     # green
    'diamond': '#4ecdc4',     # cyan
    'netherite': '#4a3728',   # dark brown
}

AVATAR_COLOR_KEYS = list(AVATAR_COLORS.keys())

# Colours that are light enough to need dark text
_LIGHT_COLORS = {'iron', 'gold', 'diamond', 'emerald'}

# Bot username indicators
BOT_IDENTIFIERS = ('Bot', 'Trader', 'Investor', 'Miner', 'Broker', 'Dealer', 'Merchant')


def get_random_avatar_color():
    """Pick a random avatar colour key for a new player."""
    return random.choice(AVATAR_COLOR_KEYS)


def get_bot_avatar_color(username):
    """Deterministically assign a colour key based on bot username.

    Uses MD5 hash of the username to pick consistently from the palette.
    """
    digest = hashlib.md5(username.encode('utf-8')).hexdigest()
    index = int(digest, 16) % len(AVATAR_COLOR_KEYS)
    return AVATAR_COLOR_KEYS[index]


def is_bot_username(username):
    """Check if a username belongs to a bot."""
    return any(identifier in username for identifier in BOT_IDENTIFIERS)


def get_avatar_color_hex(color_key):
    """Resolve a colour key to its hex value. Returns a default if key is unknown."""
    return AVATAR_COLORS.get(color_key, '#4a4a4a')


def get_avatar_text_color(color_key):
    """Return appropriate text colour (white or dark) for the given background."""
    if color_key in _LIGHT_COLORS:
        return '#1a1a2e'
    return '#ffffff'
