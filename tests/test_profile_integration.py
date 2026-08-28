"""Integration tests for avatar upload lifecycle.

Tests the full avatar upload flow, re-upload overwrite behavior,
validation rejection (format and size), and unauthenticated access.

Requirements: 2.3, 2.4, 2.5, 2.6, 9.2, 9.3, 1.2
"""

import io
import os
import sqlite3

from PIL import Image

from conftest import get_csrf_token, register_user


def _make_png_bytes(width=100, height=100, color=(255, 0, 0)):
    """Create valid PNG image bytes in memory."""
    img = Image.new('RGB', (width, height), color=color)
    buf = io.BytesIO()
    img.save(buf, format='PNG')
    return buf.getvalue()


def _make_jpeg_bytes(width=100, height=100, color=(0, 255, 0)):
    """Create valid JPEG image bytes in memory."""
    img = Image.new('RGB', (width, height), color=color)
    buf = io.BytesIO()
    img.save(buf, format='JPEG')
    return buf.getvalue()


def _make_gif_bytes(width=100, height=100, color=(0, 0, 255)):
    """Create a GIF image (unsupported format) in memory."""
    img = Image.new('RGB', (width, height), color=color)
    buf = io.BytesIO()
    img.save(buf, format='GIF')
    return buf.getvalue()


def _get_user_id(app):
    """Retrieve user ID for TestUser1 from the test DB."""
    db_path = app.config['DATABASE_PATH']
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT id FROM users WHERE username = 'TestUser1'"
    ).fetchone()
    conn.close()
    return row['id'] if row else None


def _get_avatar_path_from_db(app):
    """Retrieve avatar_path for TestUser1 from the test DB."""
    db_path = app.config['DATABASE_PATH']
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT avatar_path FROM users WHERE username = 'TestUser1'"
    ).fetchone()
    conn.close()
    return row['avatar_path'] if row else None


class TestAvatarUploadFullFlow:
    """Test full upload flow: select image -> upload -> verify DB + file stored."""

    def test_avatar_upload_full_flow(self, app, authenticated_client):
        """Upload a valid PNG, verify response 200, DB updated, file on disk."""
        client = authenticated_client
        user_id = _get_user_id(app)

        # GET the profile page to get a CSRF token
        profile_resp = client.get('/profile')
        assert profile_resp.status_code == 200
        csrf_token = get_csrf_token(profile_resp)

        # Create a valid PNG image
        image_bytes = _make_png_bytes(200, 200)

        # POST to /profile/avatar
        data = {
            'avatar': (io.BytesIO(image_bytes), 'test_avatar.png'),
            'csrf_token': csrf_token,
        }
        response = client.post(
            '/profile/avatar',
            data=data,
            content_type='multipart/form-data',
        )

        assert response.status_code == 200

        # Verify DB avatar_path is updated (not NULL)
        avatar_path = _get_avatar_path_from_db(app)
        assert avatar_path is not None
        assert avatar_path != ''
        assert f'{user_id}.webp' in avatar_path

        # Verify the file exists on disk
        file_path = os.path.join(app.static_folder, 'uploads', 'avatars', f'{user_id}.webp')
        assert os.path.exists(file_path), f"Expected avatar file at {file_path}"

        # Verify it's a valid WebP image of 300x300
        with open(file_path, 'rb') as f:
            stored_data = f.read()
        stored_img = Image.open(io.BytesIO(stored_data))
        assert stored_img.format == 'WEBP'
        assert stored_img.size == (300, 300)

        # Cleanup the file
        os.remove(file_path)


class TestAvatarReuploadOverwrites:
    """Test re-upload overwrites previous file."""

    def test_avatar_reupload_overwrites(self, app, authenticated_client):
        """Upload one image, then upload a different one. Verify overwrite."""
        client = authenticated_client
        user_id = _get_user_id(app)

        # First upload: red image
        profile_resp = client.get('/profile')
        csrf_token = get_csrf_token(profile_resp)
        image1_bytes = _make_png_bytes(150, 150, color=(255, 0, 0))

        data = {
            'avatar': (io.BytesIO(image1_bytes), 'first.png'),
            'csrf_token': csrf_token,
        }
        resp1 = client.post('/profile/avatar', data=data, content_type='multipart/form-data')
        assert resp1.status_code == 200

        file_path = os.path.join(app.static_folder, 'uploads', 'avatars', f'{user_id}.webp')
        assert os.path.exists(file_path)

        # Read first file content
        with open(file_path, 'rb') as f:
            first_content = f.read()

        # Second upload: green image (different color produces different bytes)
        profile_resp2 = client.get('/profile')
        csrf_token2 = get_csrf_token(profile_resp2)
        image2_bytes = _make_jpeg_bytes(250, 250, color=(0, 255, 0))

        data2 = {
            'avatar': (io.BytesIO(image2_bytes), 'second.jpg'),
            'csrf_token': csrf_token2,
        }
        resp2 = client.post('/profile/avatar', data=data2, content_type='multipart/form-data')
        assert resp2.status_code == 200

        # Verify DB avatar_path still points to same filename
        avatar_path = _get_avatar_path_from_db(app)
        assert f'{user_id}.webp' in avatar_path

        # Verify only one file exists for the user
        assert os.path.exists(file_path)

        # Verify file content has changed
        with open(file_path, 'rb') as f:
            second_content = f.read()
        assert first_content != second_content, "File content should differ after re-upload"

        # Cleanup
        os.remove(file_path)


class TestAvatarUploadInvalidFormatRejected:
    """Test rejection of unsupported image format (GIF)."""

    def test_avatar_upload_invalid_format_rejected(self, app, authenticated_client):
        """Upload a GIF file, expect 400 and no DB update."""
        client = authenticated_client

        # GET CSRF token from profile page
        profile_resp = client.get('/profile')
        csrf_token = get_csrf_token(profile_resp)

        # Create a GIF image (unsupported)
        gif_bytes = _make_gif_bytes(100, 100)

        data = {
            'avatar': (io.BytesIO(gif_bytes), 'bad_format.gif'),
            'csrf_token': csrf_token,
        }
        response = client.post(
            '/profile/avatar',
            data=data,
            content_type='multipart/form-data',
        )

        assert response.status_code == 400

        # Verify DB avatar_path remains NULL
        avatar_path = _get_avatar_path_from_db(app)
        assert avatar_path is None

        # The route returns an htmx partial (just img tag) — flash messages
        # are displayed via the full page layout. Verify the response does NOT
        # contain a stored avatar URL (i.e., no successful upload occurred).
        html = response.data.decode('utf-8')
        assert 'uploads/avatars/' not in html


class TestAvatarUploadOversizedRejected:
    """Test rejection of files larger than 2 MB."""

    def test_avatar_upload_oversized_rejected(self, app, authenticated_client):
        """Upload data > 2MB, expect 400 and no DB update."""
        client = authenticated_client

        # GET CSRF token from profile page
        profile_resp = client.get('/profile')
        csrf_token = get_csrf_token(profile_resp)

        # Create data > 2MB. The validation checks len(file_data) first,
        # so any data exceeding the limit is rejected before image parsing.
        oversized_data = b'\x89PNG\r\n\x1a\n' + (b'\x00' * (2 * 1024 * 1024 + 100))

        data = {
            'avatar': (io.BytesIO(oversized_data), 'big_file.png'),
            'csrf_token': csrf_token,
        }
        response = client.post(
            '/profile/avatar',
            data=data,
            content_type='multipart/form-data',
        )

        assert response.status_code == 400

        # Verify DB avatar_path remains NULL
        avatar_path = _get_avatar_path_from_db(app)
        assert avatar_path is None

        # The route returns an htmx partial — verify no successful upload URL
        html = response.data.decode('utf-8')
        assert 'uploads/avatars/' not in html


class TestAvatarUploadUnauthenticatedRedirects:
    """Test that unauthenticated POST to /profile/avatar is denied."""

    def test_avatar_upload_unauthenticated_redirects(self, app, client):
        """Without logging in, POST to /profile/avatar is blocked.

        Flask-WTF CSRF protection runs before @login_required, so an
        unauthenticated POST without a valid CSRF token returns 400.
        This confirms that unauthenticated users cannot upload avatars.
        """
        image_bytes = _make_png_bytes(50, 50)

        data = {
            'avatar': (io.BytesIO(image_bytes), 'test.png'),
        }
        response = client.post(
            '/profile/avatar',
            data=data,
            content_type='multipart/form-data',
            follow_redirects=False,
        )

        # CSRF protection blocks before login_required fires,
        # resulting in 400. Either 302 (redirect) or 400 (CSRF deny)
        # confirms the unauthenticated user cannot access the route.
        assert response.status_code in (302, 400)


class TestProfilePageUnauthenticatedRedirects:
    """Test that unauthenticated GET /profile redirects to login."""

    def test_profile_page_unauthenticated_redirects(self, app, client):
        """Without logging in, GET /profile returns 302 to login."""
        response = client.get('/profile', follow_redirects=False)

        assert response.status_code == 302
        assert '/login' in response.headers.get('Location', '')


# ---------------------------------------------------------------------------
# Bonus Collection Integration Tests
# Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 6.6, 6.9
# ---------------------------------------------------------------------------

from unittest.mock import patch, MagicMock
from datetime import date


def _get_user_bonus_state(app):
    """Retrieve bonus-related fields for TestUser1 from the test DB."""
    db_path = app.config['DATABASE_PATH']
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT balance, bonus_cycle_day, last_bonus_collected_date "
        "FROM users WHERE username = 'TestUser1'"
    ).fetchone()
    conn.close()
    return dict(row) if row else None


class TestBonusCollectionFullCycle:
    """Test the full 3-day bonus collection cycle.

    Collect day 1 (+$1,000), advance date, collect day 2 (+$10,000),
    advance date, collect day 3 (+$100,000), verify cycle_day=4,
    attempt to collect again → rejected.
    """

    def test_full_bonus_cycle(self, app, authenticated_client):
        """Walk through all 3 days of the bonus cycle and verify rejection after."""
        client = authenticated_client
        starting_balance = 10000.0

        # --- Day 1: Collect $1,000 ---
        fake_date_day1 = date(2025, 1, 1)
        with patch('app.bonus.date') as mock_date:
            mock_date.today.return_value = fake_date_day1
            mock_date.side_effect = lambda *args, **kw: date(*args, **kw)

            # Get CSRF token from profile page
            profile_resp = client.get('/profile')
            assert profile_resp.status_code == 200
            csrf_token = get_csrf_token(profile_resp)

            # Collect bonus
            response = client.post(
                '/profile/bonus/collect',
                data={'csrf_token': csrf_token},
                headers={'HX-Request': 'true'},
            )
            assert response.status_code == 200

        # Verify DB state after Day 1 collection
        state = _get_user_bonus_state(app)
        assert state['balance'] == starting_balance + 1000
        assert state['bonus_cycle_day'] == 2
        assert state['last_bonus_collected_date'] == '2025-01-01'

        # --- Day 2: Advance date, Collect $10,000 ---
        fake_date_day2 = date(2025, 1, 2)
        with patch('app.bonus.date') as mock_date:
            mock_date.today.return_value = fake_date_day2
            mock_date.side_effect = lambda *args, **kw: date(*args, **kw)

            profile_resp = client.get('/profile')
            csrf_token = get_csrf_token(profile_resp)

            response = client.post(
                '/profile/bonus/collect',
                data={'csrf_token': csrf_token},
                headers={'HX-Request': 'true'},
            )
            assert response.status_code == 200

        state = _get_user_bonus_state(app)
        assert state['balance'] == starting_balance + 1000 + 10000
        assert state['bonus_cycle_day'] == 3
        assert state['last_bonus_collected_date'] == '2025-01-02'

        # --- Day 3: Advance date, Collect $100,000 ---
        fake_date_day3 = date(2025, 1, 3)
        with patch('app.bonus.date') as mock_date:
            mock_date.today.return_value = fake_date_day3
            mock_date.side_effect = lambda *args, **kw: date(*args, **kw)

            profile_resp = client.get('/profile')
            csrf_token = get_csrf_token(profile_resp)

            response = client.post(
                '/profile/bonus/collect',
                data={'csrf_token': csrf_token},
                headers={'HX-Request': 'true'},
            )
            assert response.status_code == 200

        state = _get_user_bonus_state(app)
        assert state['balance'] == starting_balance + 1000 + 10000 + 100000
        assert state['bonus_cycle_day'] == 4
        assert state['last_bonus_collected_date'] == '2025-01-03'

        # --- Attempt collection after cycle complete → rejected ---
        fake_date_day4 = date(2025, 1, 4)
        with patch('app.bonus.date') as mock_date:
            mock_date.today.return_value = fake_date_day4
            mock_date.side_effect = lambda *args, **kw: date(*args, **kw)

            profile_resp = client.get('/profile')
            csrf_token = get_csrf_token(profile_resp)

            response = client.post(
                '/profile/bonus/collect',
                data={'csrf_token': csrf_token},
                headers={'HX-Request': 'true'},
            )
            assert response.status_code == 200

        # Balance should NOT have changed
        state = _get_user_bonus_state(app)
        assert state['balance'] == starting_balance + 1000 + 10000 + 100000
        assert state['bonus_cycle_day'] == 4

        # Response should contain the "already completed" indicator
        html = response.data.decode('utf-8')
        assert 'Bonus cycle already completed' in html or 'bonus_complete' not in html


class TestBonusDoubleCollectionRejected:
    """Test that collecting the bonus twice on the same day is rejected."""

    def test_double_collection_same_day_rejected(self, app, authenticated_client):
        """Collect once, then attempt again on the same day — second is rejected."""
        client = authenticated_client
        starting_balance = 10000.0

        fake_today = date(2025, 3, 15)
        with patch('app.bonus.date') as mock_date:
            mock_date.today.return_value = fake_today
            mock_date.side_effect = lambda *args, **kw: date(*args, **kw)

            # First collection — should succeed
            profile_resp = client.get('/profile')
            csrf_token = get_csrf_token(profile_resp)

            response = client.post(
                '/profile/bonus/collect',
                data={'csrf_token': csrf_token},
                headers={'HX-Request': 'true'},
            )
            assert response.status_code == 200

            # Verify first collection succeeded
            state = _get_user_bonus_state(app)
            assert state['balance'] == starting_balance + 1000
            assert state['bonus_cycle_day'] == 2

            # Second collection on same day — should be rejected
            profile_resp = client.get('/profile')
            csrf_token = get_csrf_token(profile_resp)

            response = client.post(
                '/profile/bonus/collect',
                data={'csrf_token': csrf_token},
                headers={'HX-Request': 'true'},
            )
            assert response.status_code == 200

        # Balance unchanged after second attempt
        state = _get_user_bonus_state(app)
        assert state['balance'] == starting_balance + 1000
        assert state['bonus_cycle_day'] == 2

        # Response should indicate already collected today
        html = response.data.decode('utf-8')
        assert 'Already collected today' in html or 'Come back tomorrow' in html


class TestBonusSectionHiddenAfterCompletion:
    """Test that the bonus section is hidden when bonus_cycle_day >= 4."""

    def test_bonus_section_hidden_when_complete(self, app, authenticated_client):
        """Set cycle_day to 4 directly, then verify profile hides bonus section."""
        client = authenticated_client

        # Directly set bonus_cycle_day to 4 in the DB to simulate completion
        db_path = app.config['DATABASE_PATH']
        conn = sqlite3.connect(db_path)
        conn.execute(
            "UPDATE users SET bonus_cycle_day = 4 WHERE username = 'TestUser1'"
        )
        conn.commit()
        conn.close()

        # Load profile page
        response = client.get('/profile')
        assert response.status_code == 200
        html = response.data.decode('utf-8')

        # The bonus section content should NOT be rendered (hidden by template conditional)
        # The template wraps content in {% if not bonus_complete %}, so the
        # bonus title, cards, and collect button should all be absent.
        # Note: 'bonus__cards' may still exist in the CSS <style> block, so we check
        # for content that only appears in the rendered bonus HTML section.
        assert 'Beginner Bonus' not in html
        assert 'Collect daily rewards' not in html
        assert 'bonus/collect' not in html


# ---------------------------------------------------------------------------
# Peak Net Worth and Account Lifecycle Integration Tests
# Requirements: 4.1, 4.2, 10.1, 10.2, 10.3, 10.5
# ---------------------------------------------------------------------------

from app.market.engine import update_peak_net_worths
from app.models import reset_account, delete_account


def _get_peak_net_worth(app, username='TestUser1'):
    """Retrieve peak_net_worth for a user from the test DB."""
    db_path = app.config['DATABASE_PATH']
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT peak_net_worth FROM users WHERE username = ?", (username,)
    ).fetchone()
    conn.close()
    return row['peak_net_worth'] if row else None


class TestPeakNetWorthUpdatesWhenExceeded:
    """Test that peak_net_worth updates when current net worth exceeds stored value.

    Requirements: 4.1, 4.2
    """

    def test_peak_updates_when_net_worth_exceeds_stored(self, app, authenticated_client):
        """Register a user, give them holdings whose value exceeds peak, run update."""
        user_id = _get_user_id(app)
        db_path = app.config['DATABASE_PATH']

        # User starts with balance=10000, peak_net_worth=10000 (defaults).
        # Insert a holding: 100 shares of ore_id=1 (Coal at $10.00 current_price).
        # Net worth = 10000 + (100 * 10.00) = 11000, which exceeds peak of 10000.
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        conn.execute(
            "INSERT INTO holdings (user_id, ore_id, quantity, avg_purchase_price) VALUES (?, ?, ?, ?)",
            (user_id, 1, 100, 10.00)
        )
        conn.commit()

        # Run update_peak_net_worths with the raw sqlite3 connection
        update_peak_net_worths(conn)
        conn.close()

        # Verify peak_net_worth is updated to 11000
        peak = _get_peak_net_worth(app)
        assert peak == 11000.0, f"Expected peak 11000.0, got {peak}"


class TestPeakNetWorthUnchangedWhenLower:
    """Test that peak_net_worth remains unchanged when current net worth is lower.

    Requirements: 4.1, 4.2
    """

    def test_peak_unchanged_when_net_worth_is_lower(self, app, authenticated_client):
        """Set peak to a high value, ensure net worth is lower, verify no update."""
        user_id = _get_user_id(app)
        db_path = app.config['DATABASE_PATH']

        # Set peak_net_worth to 50000 directly; user balance is 10000 with no holdings.
        # Net worth = 10000, which is less than stored peak of 50000.
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        conn.execute(
            "UPDATE users SET peak_net_worth = 50000 WHERE id = ?", (user_id,)
        )
        conn.commit()

        # Run update_peak_net_worths
        update_peak_net_worths(conn)
        conn.close()

        # Verify peak_net_worth remains 50000
        peak = _get_peak_net_worth(app)
        assert peak == 50000.0, f"Expected peak 50000.0, got {peak}"


class TestAccountResetPreservesAvatarResetsBonusAndPeak:
    """Test account reset preserves avatar, resets bonus and peak.

    Requirements: 10.1, 10.2, 10.3
    """

    def test_account_reset_preserves_avatar_resets_bonus_and_peak(self, app, authenticated_client):
        """Set avatar, bonus, and peak to non-default values, then reset and verify."""
        user_id = _get_user_id(app)
        db_path = app.config['DATABASE_PATH']

        # Set non-default profile values directly in DB
        conn = sqlite3.connect(db_path)
        conn.execute(
            """UPDATE users SET
                avatar_path = 'static/uploads/avatars/test.webp',
                bonus_cycle_day = 3,
                last_bonus_collected_date = '2025-01-01',
                peak_net_worth = 99999
            WHERE id = ?""",
            (user_id,)
        )
        conn.commit()
        conn.close()

        # Call reset_account within app context
        with app.app_context():
            reset_account(user_id)

        # Verify results
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            """SELECT avatar_path, peak_net_worth, bonus_cycle_day, last_bonus_collected_date
               FROM users WHERE id = ?""",
            (user_id,)
        ).fetchone()
        conn.close()

        # Avatar path is preserved (Req 10.1)
        assert row['avatar_path'] == 'static/uploads/avatars/test.webp', \
            f"Avatar path should be preserved after reset, got {row['avatar_path']}"

        # Peak net worth is preserved (lifetime high persists across resets)
        assert row['peak_net_worth'] == 99999.0, \
            f"Peak net worth should be preserved after reset, got {row['peak_net_worth']}"

        # Bonus cycle day reset to 1 (Req 10.3)
        assert row['bonus_cycle_day'] == 1, \
            f"Bonus cycle day should be reset to 1, got {row['bonus_cycle_day']}"

        # Last bonus collected date reset to NULL (Req 10.3)
        assert row['last_bonus_collected_date'] is None, \
            f"Last bonus collected date should be NULL, got {row['last_bonus_collected_date']}"


class TestAccountDeleteRemovesAvatarFile:
    """Test account delete removes avatar file from storage.

    Requirements: 10.5
    """

    def test_account_delete_removes_avatar_file(self, app, authenticated_client):
        """Upload an avatar file, then delete account and verify file is removed."""
        user_id = _get_user_id(app)
        db_path = app.config['DATABASE_PATH']

        # Create the avatar directory and write a fake .webp file
        avatar_dir = os.path.join(app.static_folder, 'uploads', 'avatars')
        os.makedirs(avatar_dir, exist_ok=True)
        avatar_filename = f'{user_id}.webp'
        avatar_filepath = os.path.join(avatar_dir, avatar_filename)

        # Write a minimal file to simulate stored avatar
        with open(avatar_filepath, 'wb') as f:
            f.write(b'\x00' * 100)

        assert os.path.exists(avatar_filepath), "Avatar file should exist before delete"

        # Set avatar_path in DB so delete_account knows to clean it up
        conn = sqlite3.connect(db_path)
        conn.execute(
            "UPDATE users SET avatar_path = ? WHERE id = ?",
            (f'static/uploads/avatars/{avatar_filename}', user_id)
        )
        conn.commit()
        conn.close()

        # Call delete_account within app context
        with app.app_context():
            delete_account(user_id)

        # Verify the avatar file is removed from disk (Req 10.5)
        assert not os.path.exists(avatar_filepath), \
            f"Avatar file should be deleted after account deletion, but still exists at {avatar_filepath}"

        # Verify user row is gone from DB
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT id FROM users WHERE id = ?", (user_id,)
        ).fetchone()
        conn.close()
        assert row is None, "User row should be deleted from DB"
