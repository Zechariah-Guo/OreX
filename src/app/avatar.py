"""Avatar utilities for OreX.

Provides:
- A palette of 9 ore-themed colours for default avatar backgrounds.
- Avatar upload validation (size, format).
- Avatar image processing (resize to square WebP output).
"""

import hashlib
import io
import random

from PIL import Image

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


def get_bot_icon_filename(username):
    """Return the icon filename for a bot based on its username.

    Strips the bot-type suffix (Bot, Trader, Investor, etc.) from the username
    and returns the corresponding icon filename in images/bots/.

    Examples:
        'CreeperTrader' -> 'images/bots/creeper_icon.png'
        'SteveBot' -> 'images/bots/steve_icon.png'
    """
    # Strip the bot identifier suffix to get the character name
    for identifier in BOT_IDENTIFIERS:
        if username.endswith(identifier):
            character = username[:-len(identifier)].lower()
            return f'images/bots/{character}_icon.png'
    # Fallback: use full username lowercased
    return f'images/bots/{username.lower()}_icon.png'


def get_avatar_color_hex(color_key):
    """Resolve a colour key to its hex value. Returns a default if key is unknown."""
    return AVATAR_COLORS.get(color_key, '#4a4a4a')


def get_avatar_text_color(color_key):
    """Return appropriate text colour (white or dark) for the given background."""
    if color_key in _LIGHT_COLORS:
        return '#1a1a2e'
    return '#ffffff'


# --- Avatar Upload Validation & Processing ---

ALLOWED_FORMATS = {'PNG', 'JPEG', 'WEBP'}
MAX_FILE_SIZE = 2 * 1024 * 1024  # 2 MB
OUTPUT_SIZE = (300, 300)


def validate_avatar(file_data: bytes) -> tuple[bool, str]:
    """Validate uploaded avatar data.

    Checks that the file is within the size limit and is a supported image
    format (PNG, JPEG, or WebP).

    Args:
        file_data: Raw bytes of the uploaded file.

    Returns:
        A tuple of (is_valid, error_message). If valid, error_message is "".
    """
    if len(file_data) > MAX_FILE_SIZE:
        return False, "File size exceeds 2 MB limit."

    try:
        img = Image.open(io.BytesIO(file_data))
        if img.format not in ALLOWED_FORMATS:
            return False, "Unsupported format. Accepted: PNG, JPEG, WebP."
    except Exception:
        return False, "Invalid image file."

    return True, ""


def process_avatar(file_data: bytes, output_size: int = 300) -> bytes:
    """Resize the validated image to a square WebP output.

    Converts the image to RGBA mode and resizes it to output_size × output_size
    pixels using Lanczos resampling for high quality. Outputs WebP format.

    Args:
        file_data: Raw bytes of a validated image file.
        output_size: The width and height in pixels for the output square image.
                     Defaults to 300.

    Returns:
        WebP-encoded bytes ready for storage.
    """
    img = Image.open(io.BytesIO(file_data))
    img = img.convert('RGBA')
    img = img.resize((output_size, output_size), Image.LANCZOS)

    output = io.BytesIO()
    img.save(output, format='WEBP', quality=85, method=6)
    return output.getvalue()
