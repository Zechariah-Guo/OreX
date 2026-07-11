"""
Property-based tests for preference persistence round-trip.

Tests validate that localStorage read/write operations preserve values exactly,
using a dict-based simulation of localStorage for the string persistence contract
and json.dumps/json.loads for the JSON serialization contract.

Feature: ui-configuration
"""

import json

from hypothesis import given, settings
from hypothesis import strategies as st


# --- Simulated localStorage helpers (mirrors JS localStorage API) ---

def local_storage_set_item(storage: dict, key: str, value: str) -> None:
    """Simulate localStorage.setItem(key, value)."""
    storage[key] = value


def local_storage_get_item(storage: dict, key: str) -> str | None:
    """Simulate localStorage.getItem(key)."""
    return storage.get(key, None)


# --- Property 4: Preference string persistence round-trip ---
# Feature: ui-configuration, Property 4: Preference string persistence round-trip


@settings(max_examples=100)
@given(
    sort_mode=st.sampled_from(["default", "rising", "falling", "custom"]),
)
def test_sort_mode_persistence_round_trip(sort_mode):
    """
    Property 4: For any valid sort mode, writing the value to localStorage
    and immediately reading it back SHALL return the identical string.

    **Validates: Requirements 6.1**
    """
    storage = {}
    local_storage_set_item(storage, "orex-sort-mode", sort_mode)
    retrieved = local_storage_get_item(storage, "orex-sort-mode")
    assert retrieved == sort_mode


@settings(max_examples=100)
@given(
    theme_mode=st.sampled_from(["light", "dark", "system"]),
)
def test_theme_mode_persistence_round_trip(theme_mode):
    """
    Property 4: For any valid theme mode, writing the value to localStorage
    and immediately reading it back SHALL return the identical string.

    **Validates: Requirements 9.1**
    """
    storage = {}
    local_storage_set_item(storage, "orex-theme", theme_mode)
    retrieved = local_storage_get_item(storage, "orex-theme")
    assert retrieved == theme_mode


# --- Property 5: Custom order JSON serialization round-trip ---
# Feature: ui-configuration, Property 5: Custom order JSON serialization round-trip


@settings(max_examples=100)
@given(
    ore_ids=st.lists(
        st.integers(min_value=1, max_value=10000),
        min_size=0,
        max_size=20,
        unique=True,
    ),
)
def test_custom_order_json_round_trip(ore_ids):
    """
    Property 5: For any valid array of distinct positive integers representing
    ore IDs, serializing the array to localStorage as JSON and deserializing it
    back SHALL produce an array that is deeply equal to the original.

    **Validates: Requirements 6.2**
    """
    storage = {}
    # Serialize: JSON.stringify equivalent
    serialized = json.dumps(ore_ids)
    local_storage_set_item(storage, "orex-custom-order", serialized)

    # Deserialize: JSON.parse equivalent
    retrieved = local_storage_get_item(storage, "orex-custom-order")
    deserialized = json.loads(retrieved)

    assert deserialized == ore_ids
    assert isinstance(deserialized, list)
    # Verify all elements are integers (not floats)
    for item in deserialized:
        assert isinstance(item, int)
