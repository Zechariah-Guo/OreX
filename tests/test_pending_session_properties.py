"""Property-based tests for pending 2FA session expiry boundary.

Tests the _get_pending_user_id() function in app/routes/two_factor.py using
Hypothesis. Verifies that the pending session is valid for offsets < 300s
and expired (returns None) for offsets >= 300s.

# Feature: two-factor-auth, Property 7: Pending session expiry boundary
# Validates: Requirements 7.1, 7.2
"""

from unittest.mock import patch

from hypothesis import given, settings
from hypothesis import strategies as st


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Offsets where the session should still be valid: [0, 299.99]
valid_offset_strategy = st.floats(min_value=0.0, max_value=299.99, allow_nan=False, allow_infinity=False)

# Offsets where the session should be expired: [300, 600]
expired_offset_strategy = st.floats(min_value=300.0, max_value=600.0, allow_nan=False, allow_infinity=False)

# Random user IDs (positive integers)
user_id_strategy = st.integers(min_value=1, max_value=100_000)

# Base timestamp for session creation (any reasonable epoch time)
base_time_strategy = st.floats(min_value=1_000_000_000.0, max_value=2_000_000_000.0, allow_nan=False, allow_infinity=False)


# ---------------------------------------------------------------------------
# Feature: two-factor-auth, Property 7: Pending session expiry boundary
# Validates: Requirements 7.1, 7.2
# ---------------------------------------------------------------------------

@settings(max_examples=100)
@given(
    user_id=user_id_strategy,
    base_time=base_time_strategy,
    offset=valid_offset_strategy,
)
def test_pending_session_valid_before_expiry(app, user_id, base_time, offset):
    """Property 7 (valid case): For any pending 2FA session created at time T,
    verification at T + offset WHERE offset < 300 seconds SHALL return the
    user_id (session is still valid).

    **Validates: Requirements 7.1, 7.2**
    """
    with app.test_request_context():
        from flask import session
        from app.routes.two_factor import _get_pending_user_id, PENDING_USER_KEY, PENDING_TIME_KEY

        session[PENDING_USER_KEY] = user_id
        session[PENDING_TIME_KEY] = base_time

        # Simulate current time as base_time + offset (offset < 300)
        with patch('app.routes.two_factor.time.time', return_value=base_time + offset):
            result = _get_pending_user_id()

        assert result == user_id, (
            f"Session should be valid at offset {offset}s but got None. "
            f"Expected user_id={user_id}"
        )


@settings(max_examples=100)
@given(
    user_id=user_id_strategy,
    base_time=base_time_strategy,
    offset=expired_offset_strategy,
)
def test_pending_session_expired_at_or_after_boundary(app, user_id, base_time, offset):
    """Property 7 (expired case): For any pending 2FA session created at time T,
    verification at T + offset WHERE offset >= 300 seconds SHALL return None
    (session is expired).

    **Validates: Requirements 7.1, 7.2**
    """
    with app.test_request_context():
        from flask import session
        from app.routes.two_factor import _get_pending_user_id, PENDING_USER_KEY, PENDING_TIME_KEY

        session[PENDING_USER_KEY] = user_id
        session[PENDING_TIME_KEY] = base_time

        # Simulate current time as base_time + offset (offset >= 300)
        with patch('app.routes.two_factor.time.time', return_value=base_time + offset):
            result = _get_pending_user_id()

        assert result is None, (
            f"Session should be expired at offset {offset}s but got user_id={result}. "
            f"Expected None."
        )
