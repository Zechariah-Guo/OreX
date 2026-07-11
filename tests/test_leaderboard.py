"""Tests for leaderboard.

Covers ranking order by total value, current user CSS class highlighting,
and HTMX partial rendering.
"""

import re

import pytest
from hypothesis import given, settings, HealthCheck
from hypothesis import strategies as st

from conftest import register_user

pytestmark = pytest.mark.leaderboard


class TestLeaderboard:
    """Tests for leaderboard ranking display."""

    def test_leaderboard_ordering_non_increasing(self, app, authenticated_client):
        """TC: all users appear in non-increasing order of total value (balance + holdings market value)."""
        # Ensure bots exist so the leaderboard has multiple users
        with app.app_context():
            from app.database import get_db
            from app.market.bots import ensure_bots_exist

            db = get_db()
            ensure_bots_exist(db, app.config['DEFAULT_BALANCE'])

        response = authenticated_client.get('/leaderboard')
        assert response.status_code == 200
        html = response.data.decode('utf-8')

        # Extract total values from the leaderboard table cells
        # The total value column has class "leaderboard-table__total"
        total_values = re.findall(
            r'<td class="leaderboard-table__total">\$([0-9]+\.[0-9]+)</td>', html
        )
        assert len(total_values) > 1, "Expected multiple users on the leaderboard"

        # Convert to floats and verify non-increasing order
        totals = [float(v) for v in total_values]
        for i in range(len(totals) - 1):
            assert totals[i] >= totals[i + 1], (
                f"Leaderboard not in non-increasing order: "
                f"position {i} (${totals[i]}) < position {i+1} (${totals[i+1]})"
            )

    def test_current_user_row_has_css_class(self, app, authenticated_client):
        """TC: current user's row has `leaderboard-table__row--current` CSS class."""
        # Ensure bots exist so leaderboard has content
        with app.app_context():
            from app.database import get_db
            from app.market.bots import ensure_bots_exist

            db = get_db()
            ensure_bots_exist(db, app.config['DEFAULT_BALANCE'])

        response = authenticated_client.get('/leaderboard')
        assert response.status_code == 200
        html = response.data.decode('utf-8')

        # Find all rows with the current-user CSS class
        current_rows = re.findall(
            r'<tr class="leaderboard-table__row--current">', html
        )
        assert len(current_rows) == 1, (
            f"Expected exactly 1 row with 'leaderboard-table__row--current', "
            f"found {len(current_rows)}"
        )

        # Verify the current user's name appears in that highlighted row
        match = re.search(
            r'<tr class="leaderboard-table__row--current">.*?</tr>',
            html,
            re.DOTALL,
        )
        assert match is not None
        assert 'TestUser1' in match.group(0)

    def test_htmx_partial_returns_table_fragment(self, app, authenticated_client):
        """TC: HTMX partial returns table fragment without full page layout."""
        # Ensure bots exist so leaderboard has content
        with app.app_context():
            from app.database import get_db
            from app.market.bots import ensure_bots_exist

            db = get_db()
            ensure_bots_exist(db, app.config['DEFAULT_BALANCE'])

        response = authenticated_client.get(
            '/leaderboard', headers={'HX-Request': 'true'}
        )
        assert response.status_code == 200
        html = response.data.decode('utf-8')

        # Should NOT contain full page layout markers
        assert '<!DOCTYPE' not in html
        assert '<html' not in html

        # Should contain the leaderboard table
        assert 'leaderboard-table' in html
        assert '<table' in html
        assert '<thead>' in html


# Feature: orex-test-suite, Property 6: Leaderboard ordering invariant
class TestLeaderboardProperties:
    """Property-based tests for leaderboard ordering invariant."""

    @given(
        balances=st.lists(
            st.floats(min_value=100.0, max_value=50000.0),
            min_size=2,
            max_size=5,
        )
    )
    @settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
    def test_leaderboard_ordering_invariant(self, app, authenticated_client, balances):
        """Leaderboard lists users in strictly non-increasing order of total value.

        **Validates: Requirements 6.1**
        """
        import sqlite3

        with app.app_context():
            from app.database import get_db
            from app.market.bots import ensure_bots_exist

            db = get_db()
            ensure_bots_exist(db, app.config['DEFAULT_BALANCE'])

            # Insert additional users with varying balances directly into the DB
            for i, balance in enumerate(balances):
                username = f'PropUser{i}'
                # Check if user already exists (from a previous iteration in the same test)
                existing = db.execute(
                    "SELECT id FROM users WHERE username = ?", (username,)
                ).fetchone()
                if existing:
                    db.execute(
                        "UPDATE users SET balance = ? WHERE username = ?",
                        (balance, username),
                    )
                else:
                    db.execute(
                        "INSERT INTO users (username, password_hash, balance, created_at) "
                        "VALUES (?, ?, ?, datetime('now'))",
                        (username, 'PROP_TEST_NO_LOGIN', balance),
                    )
            db.commit()

        # Request the leaderboard page
        response = authenticated_client.get('/leaderboard')
        assert response.status_code == 200
        html = response.data.decode('utf-8')

        # Extract total values from the leaderboard table cells
        total_values = re.findall(
            r'<td class="leaderboard-table__total">\$([0-9]+\.[0-9]+)</td>', html
        )
        assert len(total_values) > 1, "Expected multiple users on the leaderboard"

        # Convert to floats and verify non-increasing order
        totals = [float(v) for v in total_values]
        for i in range(len(totals) - 1):
            assert totals[i] >= totals[i + 1], (
                f"Leaderboard not in non-increasing order: "
                f"position {i} (${totals[i]}) < position {i+1} (${totals[i+1]})"
            )
