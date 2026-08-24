"""Property-based tests for the Notification System category style mapping.

Uses Hypothesis to verify that category style mapping is deterministic and
consistent regardless of context (message, action_url, creation time).
"""

import os
import sys
import time

# Add src/ to the Python path so that `from app.models import ...` works
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'src'))

from hypothesis import given, settings, HealthCheck
from hypothesis import strategies as st

from app.models import get_notification_style


# ---------------------------------------------------------------------------
# Feature: notification-system, Property 7: Category style mapping is
# deterministic and consistent
# Validates: Requirements 9.3, 9.4, 9.5
# ---------------------------------------------------------------------------


@settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
@given(
    category=st.text(),
    message=st.text(),
    action_url=st.one_of(st.none(), st.text()),
)
def test_category_style_mapping_deterministic_and_consistent(category, message, action_url):
    """Property 7: For any category string, the style mapping returns identical
    (css_class, icon, duration) values regardless of message, action_url, or
    creation time.

    **Validates: Requirements 9.3, 9.4, 9.5**
    """
    # Call the function multiple times to verify determinism
    result1 = get_notification_style(category)
    result2 = get_notification_style(category)

    # Determinism: same input always produces same output
    assert result1 == result2, (
        f"get_notification_style('{category}') returned different results: "
        f"{result1} vs {result2}"
    )

    # Consistency: result depends ONLY on category, not on message/action_url/time
    # The function signature only takes category, so we verify the result is
    # stable across different "contexts" (different message/action_url values
    # don't affect the output since they aren't parameters, but we verify the
    # function remains pure across multiple invocations in different contexts)
    time.sleep(0)  # Ensure time has advanced (even minimally)
    result3 = get_notification_style(category)
    assert result1 == result3, (
        f"get_notification_style('{category}') returned different results at "
        f"different times: {result1} vs {result3}"
    )

    # Return type is always a 3-tuple of (str, str, int)
    assert isinstance(result1, tuple), (
        f"Expected tuple, got {type(result1).__name__}"
    )
    assert len(result1) == 3, (
        f"Expected 3-tuple, got {len(result1)}-tuple"
    )
    css_class, icon, duration = result1
    assert isinstance(css_class, str), (
        f"Expected css_class to be str, got {type(css_class).__name__}"
    )
    assert isinstance(icon, str), (
        f"Expected icon to be str, got {type(icon).__name__}"
    )
    assert isinstance(duration, int), (
        f"Expected duration to be int, got {type(duration).__name__}"
    )

    # Known categories return expected values
    if category == "achievement":
        css_class_expected = "flash--achievement"
        assert css_class == css_class_expected, (
            f"'achievement' category should map css_class to '{css_class_expected}', "
            f"got '{css_class}'"
        )
        assert duration == 5000, (
            f"'achievement' category should have duration 5000, got {duration}"
        )
        # icon is an SVG path string (long d= attribute value)
        assert "M280-120v-80h160v-124" in icon, (
            f"'achievement' icon should be the trophy SVG path, got: {icon[:50]}..."
        )
    elif category == "liquidation":
        css_class_expected = "flash--liquidation"
        assert css_class == css_class_expected, (
            f"'liquidation' category should map css_class to '{css_class_expected}', "
            f"got '{css_class}'"
        )
        assert duration == 5000, (
            f"'liquidation' category should have duration 5000, got {duration}"
        )
        assert "m40-120 440-760 440 760" in icon, (
            f"'liquidation' icon should be the warning SVG path, got: {icon[:50]}..."
        )
    else:
        # Unknown categories return default
        css_class_expected = "flash--default"
        assert css_class == css_class_expected, (
            f"Unknown category '{category}' should map css_class to '{css_class_expected}', "
            f"got '{css_class}'"
        )
        assert duration == 3000, (
            f"Unknown category '{category}' should have duration 3000, got {duration}"
        )
        assert "M160-200v-80h80v-280" in icon, (
            f"Unknown category icon should be the bell SVG path, got: {icon[:50]}..."
        )
