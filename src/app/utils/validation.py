"""Input validation helpers for OreX."""

import re


def validate_username(username):
    """Validate username: 3-20 chars, alphanumeric and underscores only.
    Returns (is_valid, error_message).
    """
    if not username:
        return False, 'Username is required.'
    if len(username) < 3:
        return False, 'Username must be at least 3 characters.'
    if len(username) > 20:
        return False, 'Username must be 20 characters or fewer.'
    if not re.match(r'^[a-zA-Z0-9_]+$', username):
        return False, 'Username can only contain letters, numbers, and underscores.'
    return True, None


def validate_password(password):
    """Validate password strength.

    Rules: minimum 8 characters, at least one number, one symbol,
    one uppercase letter, and one lowercase letter.
    Returns (is_valid, error_message).
    """
    if not password:
        return False, 'Password is required.'
    length_issue = len(password) < 8
    character_issues = []

    if not re.search(r'\d', password):
        character_issues.append('at least one number')
    if not re.search(r'[^A-Za-z0-9\s]', password):
        character_issues.append('at least one symbol')
    if not re.search(r'[A-Z]', password):
        character_issues.append('at least one uppercase letter')
    if not re.search(r'[a-z]', password):
        character_issues.append('at least one lowercase letter')

    if length_issue and character_issues:
        if len(character_issues) == 1:
            return False, (
                'Password must be at least 8 characters and contain '
                f'{character_issues[0]}.'
            )
        if len(character_issues) == 2:
            return False, (
                'Password must be at least 8 characters and contain '
                f'{character_issues[0]} and {character_issues[1]}.'
            )
        return False, (
            'Password must be at least 8 characters and contain '
            f"{', '.join(character_issues[:-1])}, and {character_issues[-1]}."
        )

    if length_issue:
        return False, 'Password must be at least 8 characters.'

    if len(character_issues) == 1:
        return False, f'Password must contain {character_issues[0]}.'
    if len(character_issues) == 2:
        return False, f'Password must contain {character_issues[0]} and {character_issues[1]}.'
    if len(character_issues) > 2:
        return False, f"Password must contain {', '.join(character_issues[:-1])}, and {character_issues[-1]}."

    return True, None


def validate_quantity(quantity_str, max_quantity=None):
    """Validate trade quantity: must be a positive integer, optionally capped.
    Returns (quantity_int, error_message).
    """
    if not quantity_str:
        return None, 'Quantity is required.'
    try:
        quantity = int(quantity_str)
    except (ValueError, TypeError):
        return None, 'Quantity must be a whole number.'
    if quantity <= 0:
        return None, 'Quantity must be greater than zero.'
    if max_quantity is not None and quantity > max_quantity:
        return None, f'Maximum buy quantity is {max_quantity:,} in standard mode. Unlock Advanced Mode for unlimited trading.'
    return quantity, None
