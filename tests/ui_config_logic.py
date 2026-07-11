"""
Pure Python implementations of the sort/reorder algorithms from sort-manager.js.

These functions mirror the client-side JavaScript logic and are used solely for
property-based testing with Hypothesis. They have no external dependencies beyond
the standard library.

"""


def trend_sort(ores, direction):
    """Sort ore trend values according to the priority mapping.

    Mirrors the JS compareTrend + sortCards logic for 'rising' and 'falling' modes.

    Priority mapping:
      Rising direction:  rise=0, hold=1, fall=2
      Falling direction: fall=0, hold=1, rise=2

    Args:
        ores: List of dicts with at least a 'trend' key whose value is one of
              'rise', 'hold', or 'fall'. Each dict may also have an 'id' key.
        direction: Either 'rising' or 'falling'.

    Returns:
        A new list of ore dicts sorted by trend priority. Items with equal
        priority retain their original relative order (stable sort).
    """
    if direction == 'rising':
        priority_map = {'rise': 0, 'hold': 1, 'fall': 2}
    else:
        priority_map = {'fall': 0, 'hold': 1, 'rise': 2}

    # Use a stable sort keyed by priority (unknown trends default to 1 like JS)
    return sorted(ores, key=lambda ore: priority_map.get(ore['trend'], 1))


def insertion_reorder(arr, source_idx, target_idx):
    """Perform an insertion reorder: remove item at source_idx, insert at target_idx.

    Mirrors the JS drag-and-drop logic:
      1. Remove the item at source_idx from the array.
      2. Insert it at target_idx in the resulting array.
      3. Other items maintain their relative order.

    Args:
        arr: List of items (e.g. ore IDs).
        source_idx: Index of the item to move (0-based).
        target_idx: Index where the item should be inserted (0-based, relative
                    to the array AFTER removal).

    Returns:
        A new list with the item moved from source_idx to target_idx.
    """
    result = list(arr)
    item = result.pop(source_idx)
    result.insert(target_idx, item)
    return result


def apply_custom_order(current_ids, stored_order):
    """Re-apply a stored custom order to the current set of IDs.

    Mirrors the JS custom sort re-application logic in sortCards('custom'):
      1. Build an order map from stored_order: {id: position}
      2. Separate current_ids into known (present in stored_order) and unknown
      3. Sort known IDs by their position in stored_order
      4. Append unknown IDs at the end, preserving their original relative order

    Args:
        current_ids: List of ore IDs currently present (e.g. from the DOM).
        stored_order: List of ore IDs representing the saved custom order.

    Returns:
        A new list of IDs reordered according to stored_order, with any IDs
        not in stored_order appended at the end in their original order.
    """
    # Build order map: id -> position
    order_map = {ore_id: idx for idx, ore_id in enumerate(stored_order)}

    # Separate into known and unknown
    known = []
    unknown = []
    for ore_id in current_ids:
        if ore_id in order_map:
            known.append(ore_id)
        else:
            unknown.append(ore_id)

    # Sort known IDs by their position in stored_order
    known.sort(key=lambda ore_id: order_map[ore_id])

    # Combine: known first (in custom order), unknowns at end (original order)
    return known + unknown
