"""Property-based tests for sort and reorder logic.

Tests the pure Python implementations in ui_config_logic.py which mirror
the client-side JavaScript sort-manager.js algorithms.

Uses Hypothesis for property-based testing with minimum 100 iterations per property.
"""

from hypothesis import given, settings
from hypothesis import strategies as st

from ui_config_logic import trend_sort, insertion_reorder, apply_custom_order


# ---------------------------------------------------------------------------
# Feature: ui-configuration, Property 1: Trend sort produces correct ordering
# Validates: Requirements 2.1, 3.1
# ---------------------------------------------------------------------------

@settings(max_examples=100)
@given(
    ores=st.lists(
        st.sampled_from(['rise', 'hold', 'fall']),
        min_size=0,
        max_size=20,
    ),
    direction=st.sampled_from(['rising', 'falling']),
)
def test_trend_sort_ordering(ores, direction):
    """Property 1: For any array of trends and sort direction, output is
    correctly ordered per priority mapping AND contains same items as input.
    """
    # Build ore dicts with IDs for identity tracking
    ore_dicts = [{'id': i, 'trend': trend} for i, trend in enumerate(ores)]

    result = trend_sort(ore_dicts, direction)

    # Same items (no items lost or duplicated)
    assert len(result) == len(ore_dicts)
    assert sorted([o['id'] for o in result]) == sorted([o['id'] for o in ore_dicts])

    # Correct ordering per priority mapping
    if direction == 'rising':
        priority_map = {'rise': 0, 'hold': 1, 'fall': 2}
    else:
        priority_map = {'fall': 0, 'hold': 1, 'rise': 2}

    for i in range(len(result) - 1):
        assert priority_map[result[i]['trend']] <= priority_map[result[i + 1]['trend']]


# ---------------------------------------------------------------------------
# Feature: ui-configuration, Property 2: Insertion reorder preserves items and places correctly
# Validates: Requirements 5.2
# ---------------------------------------------------------------------------

@settings(max_examples=100)
@given(
    data=st.data(),
)
def test_insertion_reorder_preserves_items(data):
    """Property 2: For any array of distinct IDs of length N>=2 and valid
    source/target indices (s!=t), insertion reorder result has same set of IDs,
    moved item at correct position, and other items in preserved relative order.
    """
    # Generate array of distinct IDs (length 2-20)
    n = data.draw(st.integers(min_value=2, max_value=20))
    arr = data.draw(
        st.lists(
            st.integers(min_value=1, max_value=1000),
            min_size=n,
            max_size=n,
            unique=True,
        )
    )

    # Generate valid source and target indices where s != t
    source_idx = data.draw(st.integers(min_value=0, max_value=n - 1))
    # target_idx is relative to the array AFTER removal, so valid range is 0..n-2
    target_idx = data.draw(
        st.integers(min_value=0, max_value=n - 2).filter(
            lambda t: t != source_idx or source_idx != t
        )
    )
    # Ensure source != target (accounting for shift)
    # Actually we need s != t in the original sense; the function removes then inserts
    # so we just need them to produce a different arrangement
    # The key constraint from the spec is s != t in terms of producing a move

    result = insertion_reorder(arr, source_idx, target_idx)

    # (1) Result contains exactly the same set of IDs
    assert sorted(result) == sorted(arr)
    assert len(result) == len(arr)

    # (2) The moved item appears at index target_idx
    moved_item = arr[source_idx]
    assert result[target_idx] == moved_item

    # (3) Relative order of other items is preserved
    other_items_before = [x for i, x in enumerate(arr) if i != source_idx]
    other_items_after = [x for i, x in enumerate(result) if i != target_idx]
    assert other_items_before == other_items_after


# ---------------------------------------------------------------------------
# Feature: ui-configuration, Property 3: Custom order re-application matches stored permutation
# Validates: Requirements 5.4
# ---------------------------------------------------------------------------

@settings(max_examples=100)
@given(
    data=st.data(),
)
def test_custom_order_reapplication(data):
    """Property 3: For any valid permutation of ore IDs stored as custom order,
    and any arrangement of the same IDs as current, applying custom order produces
    exact match with stored permutation.
    """
    # Generate a list of distinct ore IDs (simulating the 9 ores, but testing with 2-15)
    n = data.draw(st.integers(min_value=2, max_value=15))
    ore_ids = data.draw(
        st.lists(
            st.integers(min_value=1, max_value=100),
            min_size=n,
            max_size=n,
            unique=True,
        )
    )

    # stored_order is a permutation of the ore IDs
    stored_order = data.draw(st.permutations(ore_ids))

    # current_ids is another (possibly different) arrangement of the same IDs
    current_ids = data.draw(st.permutations(ore_ids))

    result = apply_custom_order(current_ids, stored_order)

    # Applying custom order produces exact match with stored permutation
    assert result == list(stored_order)
