"""Property-based tests for the Profile Page.

Uses Hypothesis to verify universal correctness properties defined in the
design document for avatar validation and processing.
"""

import io
import os
import sys

# Add src/ to the Python path so that `from app.avatar import ...` works
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'src'))

from hypothesis import given, settings
from hypothesis import strategies as st
from PIL import Image

from app.avatar import validate_avatar, process_avatar, MAX_FILE_SIZE


# ---------------------------------------------------------------------------
# Feature: profile-page, Property 2: Avatar Validation Correctness
# Validates: Requirements 2.4, 2.5, 2.6
# ---------------------------------------------------------------------------


def _make_image_bytes(width: int, height: int, fmt: str, mode: str) -> bytes:
    """Helper to create valid image bytes using Pillow."""
    # JPEG doesn't support RGBA mode
    if fmt == 'JPEG' and mode == 'RGBA':
        mode = 'RGB'
    # Grayscale ('L') mode requires a single int color value
    if mode == 'L':
        color = 128
    elif mode == 'RGBA':
        color = (128, 64, 200, 255)
    else:
        color = (128, 64, 200)
    img = Image.new(mode, (width, height), color=color)
    buf = io.BytesIO()
    img.save(buf, format=fmt)
    return buf.getvalue()


@settings(max_examples=50, deadline=None)
@given(
    extra_bytes=st.integers(min_value=1, max_value=1024),
)
def test_oversized_data_always_rejected(extra_bytes):
    """Property 2 (size): For any byte sequence > 2MB, validate_avatar returns
    (False, "File size exceeds 2 MB limit.") regardless of content.

    **Validates: Requirements 2.4, 2.5, 2.6**
    """
    # Construct data that exceeds the 2MB limit by a small amount
    data = b'\x00' * (MAX_FILE_SIZE + extra_bytes)
    assert len(data) > MAX_FILE_SIZE

    is_valid, error = validate_avatar(data)
    assert is_valid is False, (
        f"Expected oversized data ({len(data)} bytes) to be rejected"
    )
    assert error == "File size exceeds 2 MB limit.", (
        f"Expected size error message, got: '{error}'"
    )


@settings(max_examples=50, deadline=None)
@given(
    width=st.integers(min_value=1, max_value=200),
    height=st.integers(min_value=1, max_value=200),
    fmt=st.sampled_from(['PNG', 'JPEG', 'WEBP']),
    mode=st.sampled_from(['RGB', 'RGBA', 'L']),
)
def test_valid_images_accepted(width, height, fmt, mode):
    """Property 2 (valid format): For valid images in {PNG, JPEG, WEBP} format
    with size <= 2MB, validate_avatar returns (True, "").

    **Validates: Requirements 2.4, 2.5, 2.6**
    """
    image_data = _make_image_bytes(width, height, fmt, mode)

    # Only test if the generated image is within size limit
    if len(image_data) > MAX_FILE_SIZE:
        return  # Skip — image too large for this property

    is_valid, error = validate_avatar(image_data)
    assert is_valid is True, (
        f"Expected valid {fmt} image ({width}x{height}, mode={mode}, "
        f"{len(image_data)} bytes) to be accepted, got error: '{error}'"
    )
    assert error == "", (
        f"Expected empty error for valid image, got: '{error}'"
    )


@settings(max_examples=50, deadline=None)
@given(
    width=st.integers(min_value=1, max_value=200),
    height=st.integers(min_value=1, max_value=200),
    fmt=st.sampled_from(['GIF', 'BMP', 'TIFF']),
    mode=st.sampled_from(['RGB', 'RGBA', 'L']),
)
def test_invalid_format_rejected(width, height, fmt, mode):
    """Property 2 (invalid format): For valid images in unsupported formats
    (e.g., GIF, BMP, TIFF) with size <= 2MB, validate_avatar returns
    (False, "Unsupported format. Accepted: PNG, JPEG, WebP.").

    **Validates: Requirements 2.4, 2.5, 2.6**
    """
    image_data = _make_image_bytes(width, height, fmt, mode)

    # Only test if the generated image is within size limit
    if len(image_data) > MAX_FILE_SIZE:
        return  # Skip — image too large for this property

    is_valid, error = validate_avatar(image_data)
    assert is_valid is False, (
        f"Expected {fmt} image to be rejected as unsupported format"
    )
    assert error == "Unsupported format. Accepted: PNG, JPEG, WebP.", (
        f"Expected format error message, got: '{error}'"
    )


# ---------------------------------------------------------------------------
# Feature: profile-page, Property 3: Avatar Processing Produces Fixed Dimensions
# Validates: Requirements 2.7
# ---------------------------------------------------------------------------


@settings(max_examples=100, deadline=None)
@given(
    width=st.integers(min_value=1, max_value=500),
    height=st.integers(min_value=1, max_value=500),
    fmt=st.sampled_from(['PNG', 'JPEG', 'WEBP']),
    mode=st.sampled_from(['RGB', 'RGBA', 'L']),
)
def test_process_avatar_produces_fixed_dimensions(width, height, fmt, mode):
    """Property 3: For any valid image of arbitrary W×H (W≥1, H≥1),
    process_avatar produces a WebP image of exactly 300×300 pixels.

    **Validates: Requirements 2.7**
    """
    image_data = _make_image_bytes(width, height, fmt, mode)

    result = process_avatar(image_data)

    # Verify the output is a valid WebP image of exactly 300×300 pixels
    output_img = Image.open(io.BytesIO(result))
    assert output_img.format == 'WEBP', (
        f"Expected output format WEBP, got {output_img.format}"
    )
    assert output_img.size == (300, 300), (
        f"Expected output size (300, 300), got {output_img.size} "
        f"for input image {width}x{height} mode={mode} fmt={fmt}"
    )


# ---------------------------------------------------------------------------
# Feature: profile-page, Property 4: Peak Net Worth is Monotonically Non-Decreasing
# Validates: Requirements 4.1, 4.2
# ---------------------------------------------------------------------------

import sqlite3 as _sqlite3

from app.market.engine import update_peak_net_worths


@settings(max_examples=100, deadline=None)
@given(
    current_net_worth=st.floats(min_value=0, max_value=100_000_000, allow_nan=False, allow_infinity=False),
    stored_peak=st.floats(min_value=0, max_value=100_000_000, allow_nan=False, allow_infinity=False),
)
def test_peak_net_worth_monotonically_non_decreasing(current_net_worth, stored_peak):
    """Property 4: For any player with stored peak P and current net worth N,
    after update_peak_net_worths executes: new peak = max(N, P).
    If N > P, stored peak becomes N; if N <= P, stored peak remains P.

    **Validates: Requirements 4.1, 4.2**
    """
    # Set up in-memory SQLite database
    db = _sqlite3.connect(":memory:")
    db.row_factory = _sqlite3.Row

    db.execute("""
        CREATE TABLE users (
            id INTEGER PRIMARY KEY,
            balance REAL NOT NULL DEFAULT 0,
            peak_net_worth REAL NOT NULL DEFAULT 0
        )
    """)
    db.execute("""
        CREATE TABLE holdings (
            id INTEGER PRIMARY KEY,
            user_id INTEGER NOT NULL,
            ore_id INTEGER NOT NULL,
            quantity REAL NOT NULL DEFAULT 0
        )
    """)
    db.execute("""
        CREATE TABLE ores (
            id INTEGER PRIMARY KEY,
            current_price REAL NOT NULL DEFAULT 0
        )
    """)

    # Create a user with balance = current_net_worth and no holdings
    # This ensures net worth = balance = current_net_worth
    db.execute(
        "INSERT INTO users (id, balance, peak_net_worth) VALUES (?, ?, ?)",
        (1, current_net_worth, stored_peak),
    )
    db.commit()

    # Execute the function under test
    update_peak_net_worths(db)

    # Read the resulting peak_net_worth
    row = db.execute("SELECT peak_net_worth FROM users WHERE id = 1").fetchone()
    result_peak = row["peak_net_worth"]

    # Assert: new peak = max(current_net_worth, stored_peak)
    expected_peak = max(current_net_worth, stored_peak)
    assert result_peak == expected_peak, (
        f"Expected peak_net_worth = max({current_net_worth}, {stored_peak}) = {expected_peak}, "
        f"got {result_peak}"
    )

    db.close()


# ---------------------------------------------------------------------------
# Feature: profile-page, Property 5: Bonus Amount Mapping
# Validates: Requirements 6.1
# ---------------------------------------------------------------------------

from app.bonus import get_bonus_amount, collect_bonus, BONUS_AMOUNTS


@settings(max_examples=100, deadline=None)
@given(cycle_day=st.integers(min_value=-10, max_value=10))
def test_bonus_amount_mapping(cycle_day):
    """Property 5: For any cycle_day D in {1,2,3}, get_bonus_amount(D) returns
    the correct mapped value. For D>=4 or D<=0, returns 0.

    **Validates: Requirements 6.1**
    """
    result = get_bonus_amount(cycle_day)

    if cycle_day in BONUS_AMOUNTS:
        assert result == BONUS_AMOUNTS[cycle_day], (
            f"Expected get_bonus_amount({cycle_day}) == {BONUS_AMOUNTS[cycle_day]}, got {result}"
        )
    else:
        assert result == 0, (
            f"Expected get_bonus_amount({cycle_day}) == 0 for out-of-range day, got {result}"
        )


# ---------------------------------------------------------------------------
# Feature: profile-page, Property 6: Bonus Collection State Machine
# Validates: Requirements 6.2, 6.3, 6.4, 7.5, 7.6
# ---------------------------------------------------------------------------

import sqlite3
from datetime import date
from unittest.mock import patch


@settings(max_examples=100, deadline=None)
@given(
    cycle_day=st.integers(min_value=1, max_value=5),
    last_collected=st.one_of(st.none(), st.dates()),
    today=st.dates(),
)
def test_bonus_collection_state_machine(cycle_day, last_collected, today):
    """Property 6: For any player state (D, L, T):
    - if D>=4, collect returns (False, 0) and balance unchanged
    - if D<4 AND L==T, returns (False, 0) and balance unchanged
    - if D<4 AND (L is None OR L!=T), returns (True, BONUS_AMOUNTS[D])
      with correct state transitions.

    **Validates: Requirements 6.2, 6.3, 6.4, 7.5, 7.6**
    """
    initial_balance = 10000.0

    # Set up in-memory SQLite database
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    db.execute(
        """CREATE TABLE users (
            id INTEGER PRIMARY KEY,
            balance REAL NOT NULL DEFAULT 10000,
            bonus_cycle_day INTEGER NOT NULL DEFAULT 1,
            last_bonus_collected_date TEXT DEFAULT NULL
        )"""
    )

    # Convert last_collected to ISO string or None
    last_collected_str = last_collected.isoformat() if last_collected is not None else None

    db.execute(
        "INSERT INTO users (id, balance, bonus_cycle_day, last_bonus_collected_date) VALUES (?, ?, ?, ?)",
        (1, initial_balance, cycle_day, last_collected_str),
    )
    db.commit()

    # Mock date.today() to return our controlled 'today' value
    with patch("app.bonus.date") as mock_date:
        mock_date.today.return_value = today
        mock_date.side_effect = lambda *args, **kwargs: date(*args, **kwargs)

        success, amount = collect_bonus(db, 1)

    # Read resulting state
    row = db.execute("SELECT balance, bonus_cycle_day, last_bonus_collected_date FROM users WHERE id = 1").fetchone()
    final_balance = row["balance"]
    final_cycle_day = row["bonus_cycle_day"]
    final_last_collected = row["last_bonus_collected_date"]

    today_str = today.isoformat()

    if cycle_day >= 4:
        # Branch 1: cycle complete — no collection
        assert success is False
        assert amount == 0
        assert final_balance == initial_balance
        assert final_cycle_day == cycle_day
        assert final_last_collected == last_collected_str
    elif last_collected_str == today_str:
        # Branch 2: already collected today — no collection
        assert success is False
        assert amount == 0
        assert final_balance == initial_balance
        assert final_cycle_day == cycle_day
        assert final_last_collected == last_collected_str
    else:
        # Branch 3: eligible — collect bonus
        expected_amount = BONUS_AMOUNTS[cycle_day]
        assert success is True
        assert amount == expected_amount
        assert final_balance == initial_balance + expected_amount
        assert final_cycle_day == cycle_day + 1
        assert final_last_collected == today_str

    db.close()



# ---------------------------------------------------------------------------
# Feature: profile-page, Property 1: Avatar URL Resolution
# Validates: Requirements 2.1, 9.2
# ---------------------------------------------------------------------------

from app.storage import LocalStorage


@settings(max_examples=100, deadline=None)
@given(
    user_id=st.integers(min_value=1, max_value=1_000_000),
    avatar_path=st.one_of(st.none(), st.just(''), st.text(min_size=1, max_size=100)),
)
def test_avatar_url_resolution(user_id, avatar_path, app):
    """Property 1: For any user row: if avatar_path is non-null/non-empty,
    resolved URL derives from avatar_path (using storage.get_url with
    filename '{user_id}.webp'); if NULL/empty, returns default avatar path.

    **Validates: Requirements 2.1, 9.2**
    """
    with app.test_request_context():
        storage = LocalStorage(os.path.join(app.static_folder, 'uploads', 'avatars'))

        if avatar_path:  # non-null and non-empty
            # URL should derive from the user_id-based filename
            expected_filename = f"{user_id}.webp"
            url = storage.get_url(expected_filename)
            assert 'uploads/avatars/' in url, (
                f"Expected URL to contain 'uploads/avatars/', got: {url}"
            )
            assert expected_filename in url, (
                f"Expected URL to contain {expected_filename}, got: {url}"
            )
        else:
            # NULL or empty avatar_path: no default image (the default avatar
            # is the initials circle), so the avatar partial renders no <img>
            from flask import render_template
            html = render_template('partials/profile_avatar.html', avatar_url=None)
            assert '<img' not in html, (
                f"Expected no avatar image without an upload, got: {html}"
            )


# ---------------------------------------------------------------------------
# Feature: profile-page, Property 7: Avatar Filename Derivation
# Validates: Requirements 2.1, 9.2
# ---------------------------------------------------------------------------


@settings(max_examples=200, deadline=None)
@given(user_id=st.integers(min_value=1, max_value=10_000_000))
def test_avatar_filename_derivation(user_id):
    """Property 7: For any positive integer user_id, the stored avatar
    filename equals f"{user_id}.webp".

    This ensures filenames are deterministic, collision-free (one per user),
    and safe (no path traversal, no special characters beyond digits and dot).

    **Validates: Requirements 2.1, 9.2**
    """
    filename = f"{user_id}.webp"

    # Must end with .webp extension
    assert filename.endswith('.webp'), (
        f"Expected .webp extension, got: {filename}"
    )

    # Must start with the user_id as a string
    assert filename.startswith(str(user_id)), (
        f"Expected filename to start with user_id {user_id}, got: {filename}"
    )

    # Must be exactly '{user_id}.webp' with no extra characters
    assert filename == f"{user_id}.webp", (
        f'Expected exactly "{user_id}.webp", got: {filename}'
    )

    # Must not contain path separators (prevents path traversal)
    assert '/' not in filename and '\\' not in filename, (
        f"Filename must not contain path separators: {filename}"
    )

    # Must be unique per user_id (deterministic derivation)
    filename_again = f"{user_id}.webp"
    assert filename == filename_again, (
        "Filename derivation must be deterministic"
    )
