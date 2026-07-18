"""Property-based tests for 2FA model functions.

Tests the 2FA-related model functions in app/models.py using Hypothesis
for property-based testing with minimum 100 iterations per property.
Requires database access via the `app` and `db_reset` fixtures from conftest.py.
"""

import string
import uuid

from hypothesis import given, settings
from hypothesis import strategies as st

from app.models import (
    create_user,
    delete_account,
    disable_2fa,
    enable_2fa,
    get_2fa_status,
    get_backup_codes,
    get_encrypted_totp_secret,
    get_remaining_backup_code_count,
    mark_backup_code_used,
    reset_account,
    store_backup_codes,
)
from app.totp import hash_backup_code, verify_backup_code


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Random alphanumeric codes (same format as backup codes: 8-char alphanumeric)
alphanumeric_code_strategy = st.text(
    alphabet=string.ascii_letters + string.digits,
    min_size=8,
    max_size=8,
)

# Random encrypted secret strings (simulating stored encrypted TOTP secrets)
encrypted_secret_strategy = st.text(
    alphabet=string.ascii_letters + string.digits + "+/=",
    min_size=20,
    max_size=100,
)

# Lists of backup codes (1 to 8 unique codes)
backup_codes_list_strategy = st.lists(
    alphanumeric_code_strategy,
    min_size=1,
    max_size=8,
    unique=True,
)


def _unique_username(prefix: str) -> str:
    """Generate a unique username using a UUID suffix to avoid collisions
    across Hypothesis iterations within the same test function."""
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


# ---------------------------------------------------------------------------
# Feature: two-factor-auth, Property 5: Backup code single-use semantics
# Validates: Requirements 5.2
# ---------------------------------------------------------------------------

@settings(max_examples=100, deadline=None)
@given(code=alphanumeric_code_strategy)
def test_backup_code_single_use_semantics(app, code):
    """Property 5: For any backup code that has been marked as used,
    subsequent verification attempts with that same code SHALL fail
    (the code is no longer counted as remaining).
    """
    with app.app_context():
        # Create a test user with a unique username
        user_id = create_user(_unique_username("p5"), "Password123!")

        # Hash the code and store it
        hashed = hash_backup_code(code)
        store_backup_codes(user_id, [hashed])

        # Verify the code is initially available
        initial_count = get_remaining_backup_code_count(user_id)
        assert initial_count == 1, f"Expected 1 remaining code, got {initial_count}"

        # Get the stored backup code row to find its ID
        codes = get_backup_codes(user_id)
        assert len(codes) == 1
        code_row = codes[0]

        # Verify the code matches before marking as used
        assert verify_backup_code(code_row["code_hash"], code) is True

        # Mark the code as used
        mark_backup_code_used(code_row["id"])

        # After marking as used, the remaining count should be 0
        remaining = get_remaining_backup_code_count(user_id)
        assert remaining == 0, (
            f"Expected 0 remaining codes after marking as used, got {remaining}"
        )

        # The code row should now show used=1
        updated_codes = get_backup_codes(user_id)
        assert updated_codes[0]["used"] == 1, "Code should be marked as used"


# ---------------------------------------------------------------------------
# Feature: two-factor-auth, Property 9: Disabling 2FA removes all 2FA data
# Validates: Requirements 8.3
# ---------------------------------------------------------------------------

@settings(max_examples=100, deadline=None)
@given(encrypted_secret=encrypted_secret_strategy)
def test_disabling_2fa_removes_all_data(app, encrypted_secret):
    """Property 9: For any user with 2FA enabled, after calling
    disable_2fa(user_id), the user's totp_enabled SHALL be 0,
    totp_secret_encrypted SHALL be NULL, and the count of rows
    in backup_codes for that user SHALL be 0.
    """
    with app.app_context():
        # Create a test user and enable 2FA
        user_id = create_user(_unique_username("p9"), "Password123!")
        enable_2fa(user_id, encrypted_secret)

        # Store some backup codes
        hashed_codes = [hash_backup_code(f"code{i:04d}") for i in range(3)]
        store_backup_codes(user_id, hashed_codes)

        # Verify 2FA is enabled with data present
        status = get_2fa_status(user_id)
        assert status["enabled"] is True
        assert get_remaining_backup_code_count(user_id) == 3

        # Disable 2FA
        disable_2fa(user_id)

        # Verify all 2FA data is removed
        status_after = get_2fa_status(user_id)
        assert status_after["enabled"] is False, "totp_enabled should be 0 after disable"
        assert status_after["encrypted_secret"] is None, (
            "totp_secret_encrypted should be NULL after disable"
        )

        secret_after = get_encrypted_totp_secret(user_id)
        assert secret_after is None, "Encrypted secret should be NULL after disable"

        backup_count = get_remaining_backup_code_count(user_id)
        assert backup_count == 0, (
            f"Expected 0 backup codes after disable, got {backup_count}"
        )

        all_codes = get_backup_codes(user_id)
        assert len(all_codes) == 0, (
            f"Expected no backup code rows after disable, got {len(all_codes)}"
        )


# ---------------------------------------------------------------------------
# Feature: two-factor-auth, Property 10: Account reset preserves 2FA configuration
# Validates: Requirements 10.1
# ---------------------------------------------------------------------------

@settings(max_examples=100, deadline=None)
@given(encrypted_secret=encrypted_secret_strategy)
def test_account_reset_preserves_2fa(app, encrypted_secret):
    """Property 10: For any user with 2FA enabled, after calling
    reset_account(user_id), the user's totp_enabled, totp_secret_encrypted,
    and all backup_codes rows SHALL remain unchanged from their pre-reset state.
    """
    with app.app_context():
        # Create a test user and enable 2FA
        user_id = create_user(_unique_username("p10"), "Password123!")
        enable_2fa(user_id, encrypted_secret)

        # Store backup codes
        hashed_codes = [hash_backup_code(f"bkup{i:04d}") for i in range(4)]
        store_backup_codes(user_id, hashed_codes)

        # Capture pre-reset state
        status_before = get_2fa_status(user_id)
        secret_before = get_encrypted_totp_secret(user_id)
        codes_before = get_backup_codes(user_id)
        count_before = get_remaining_backup_code_count(user_id)

        # Reset the account
        reset_account(user_id)

        # Verify 2FA state is unchanged
        status_after = get_2fa_status(user_id)
        assert status_after["enabled"] == status_before["enabled"], (
            "totp_enabled should be unchanged after reset"
        )
        assert status_after["encrypted_secret"] == status_before["encrypted_secret"], (
            "totp_secret_encrypted should be unchanged after reset"
        )

        secret_after = get_encrypted_totp_secret(user_id)
        assert secret_after == secret_before, (
            "Encrypted secret should be unchanged after reset"
        )

        codes_after = get_backup_codes(user_id)
        assert len(codes_after) == len(codes_before), (
            "Backup code count should be unchanged after reset"
        )

        count_after = get_remaining_backup_code_count(user_id)
        assert count_after == count_before, (
            f"Remaining backup code count changed: {count_before} -> {count_after}"
        )

        # Verify each backup code row is identical
        for before, after in zip(codes_before, codes_after):
            assert before["id"] == after["id"]
            assert before["code_hash"] == after["code_hash"]
            assert before["used"] == after["used"]


# ---------------------------------------------------------------------------
# Feature: two-factor-auth, Property 11: Account delete removes all 2FA data
# Validates: Requirements 10.3
# ---------------------------------------------------------------------------

@settings(max_examples=100, deadline=None)
@given(encrypted_secret=encrypted_secret_strategy)
def test_account_delete_removes_all_2fa_data(app, encrypted_secret):
    """Property 11: For any user with 2FA enabled, after calling
    delete_account(user_id), no row SHALL exist in users for that user_id,
    and no rows SHALL exist in backup_codes for that user_id.
    """
    with app.app_context():
        # Create a test user and enable 2FA
        user_id = create_user(_unique_username("p11"), "Password123!")
        enable_2fa(user_id, encrypted_secret)

        # Store backup codes
        hashed_codes = [hash_backup_code(f"del_{i:05d}") for i in range(5)]
        store_backup_codes(user_id, hashed_codes)

        # Verify data exists before deletion
        assert get_2fa_status(user_id)["enabled"] is True
        assert get_remaining_backup_code_count(user_id) == 5

        # Delete the account
        delete_account(user_id)

        # Verify user row is gone (get_2fa_status returns default for missing user)
        status_after = get_2fa_status(user_id)
        assert status_after["enabled"] is False, (
            "User should not exist after deletion"
        )
        assert status_after["encrypted_secret"] is None, (
            "No encrypted secret should remain after deletion"
        )

        # Verify no backup codes remain
        remaining_codes = get_backup_codes(user_id)
        assert len(remaining_codes) == 0, (
            f"Expected no backup code rows after delete, got {len(remaining_codes)}"
        )

        remaining_count = get_remaining_backup_code_count(user_id)
        assert remaining_count == 0, (
            f"Expected 0 remaining backup codes after delete, got {remaining_count}"
        )
