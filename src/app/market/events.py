"""Market events — rare occurrences that cause price shocks.

Each tick has a 0.5% chance of triggering an event per ore.
When triggered, the price change is multiplied by 3x.
"""

import random

EVENT_CHANCE = 0.005  # 0.5% per ore per tick
EVENT_MULTIPLIER = 3.0


def roll_event():
    """Roll for a market event. Returns True if an event occurs."""
    return random.random() < EVENT_CHANCE


def apply_event_multiplier(price_change):
    """Apply the event multiplier to a price change."""
    return price_change * EVENT_MULTIPLIER
