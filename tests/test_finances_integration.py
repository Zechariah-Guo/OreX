"""Integration tests for the full finances page lifecycle.

Covers end-to-end scenarios:
- Open short position → load /finances → verify position appears with correct metrics
- Close short position → reload partial → verify position removed
- Fee burn displayed matches actual tick engine formula
- Account reset while on finances → next request returns 403
- Toggle Advanced Mode off → next request returns 403
- Multiple positions → verify aggregates match individual rows
- Zero free cash with active shorts → displays "$0.00" and "0 ticks" with red indicator

Validates: Requirements 1.1, 1.3, 4.1, 4.5, 5.1, 6.4, 6.5, 9.1, 9.2, 9.3, 9.4
"""

import sqlite3
import math

import pytest

from conftest import register_user

pytestmark = pytest.mark.finances


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _set_user_state(app, username='TestUser1', **kwargs):
    """Directly set user columns in the database for test setup."""
    if not kwargs:
        return
    conn = sqlite3.connect(app.config['DATABASE_PATH'])
    sets = ', '.join(f'{k} = ?' for k in kwargs)
    values = list(kwargs.values())
    conn.execute(
        f"UPDATE users SET {sets} WHERE username = ?",
        values + [username],
    )
    conn.commit()
    conn.close()


def _get_user_id(app, username='TestUser1'):
    """Get user ID by username."""
    conn = sqlite3.connect(app.config['DATABASE_PATH'])
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT id FROM users WHERE username = ?", (username,)
    ).fetchone()
    conn.close()
    return row['id'] if row else None


def _insert_short_position(app, user_id, ore_id, share_quantity, entry_price,
                           locked_collateral, status='active',
                           cumulative_fees_paid=0.0,
                           stop_loss_price=None, take_profit_price=None):
    """Insert a short position directly into the database."""
    conn = sqlite3.connect(app.config['DATABASE_PATH'])
    conn.execute(
        """INSERT INTO short_positions
           (user_id, ore_id, share_quantity, entry_price, locked_collateral,
            stop_loss_price, take_profit_price, cumulative_fees_paid, status)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (user_id, ore_id, share_quantity, entry_price, locked_collateral,
         stop_loss_price, take_profit_price, cumulative_fees_paid, status),
    )
    conn.commit()
    conn.close()


def _close_position(app, position_id):
    """Mark a short position as closed."""
    conn = sqlite3.connect(app.config['DATABASE_PATH'])
    conn.execute(
        "UPDATE short_positions SET status = 'closed', closed_at = datetime('now') WHERE id = ?",
        (position_id,),
    )
    conn.commit()
    conn.close()


def _get_ore_data(app, ore_id):
    """Get ore current_price and volatility."""
    conn = sqlite3.connect(app.config['DATABASE_PATH'])
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT current_price, volatility, name FROM ores WHERE id = ?", (ore_id,)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestFinancesIntegrationLifecycle:
    """Integration tests for the finances page full lifecycle."""

    def test_open_short_position_appears_in_finances(self, authenticated_client, app):
        """Open a short position → GET /finances → verify position appears in table.

        Validates: Requirements 1.1, 4.1
        """
        _set_user_state(app, advanced_purchased=1, advanced_active=1)
        user_id = _get_user_id(app)

        # Insert a short position on Coal (id=1, price=10.00, volatility=0.5)
        _insert_short_position(
            app, user_id, ore_id=1, share_quantity=100,
            entry_price=10.00, locked_collateral=1500.00,
        )

        response = authenticated_client.get('/finances')
        assert response.status_code == 200
        html = response.data.decode('utf-8')

        # Verify the ore name appears in the table
        assert 'Coal' in html
        # Verify share quantity
        assert '100' in html
        # Verify entry price ($10.00)
        assert '$10.00' in html
        # Verify locked collateral ($1,500.00)
        assert '$1,500.00' in html
        # Short value = 100 shares * $10.00 = $1,000.00
        assert '$1,000.00' in html

    def test_close_short_position_removed_on_partial_reload(self, authenticated_client, app):
        """Close a short position → GET /finances (HTMX) → verify position is gone.

        Validates: Requirements 6.4
        """
        _set_user_state(app, advanced_purchased=1, advanced_active=1)
        user_id = _get_user_id(app)

        # Insert an active position on Iron (id=2, price=25.00)
        _insert_short_position(
            app, user_id, ore_id=2, share_quantity=50,
            entry_price=25.00, locked_collateral=2000.00,
        )

        # Verify it appears first
        response = authenticated_client.get('/finances')
        assert response.status_code == 200
        html = response.data.decode('utf-8')
        assert 'Iron' in html

        # Now close the position
        conn = sqlite3.connect(app.config['DATABASE_PATH'])
        pos_id = conn.execute(
            "SELECT id FROM short_positions WHERE user_id = ? AND ore_id = 2",
            (user_id,)
        ).fetchone()[0]
        conn.close()
        _close_position(app, pos_id)

        # Reload via HTMX partial
        response = authenticated_client.get(
            '/finances', headers={'HX-Request': 'true'}
        )
        assert response.status_code == 200
        html = response.data.decode('utf-8')

        # Position should no longer appear
        assert 'Iron' not in html
        # Should show empty state or no positions section
        assert 'No active short positions' in html or 'Active Short Positions' not in html

    def test_fee_burn_matches_tick_engine_formula(self, authenticated_client, app):
        """Fee burn displayed matches the actual tick engine formula.

        Formula: SUM(round(short_value * ((0.005 + 0.10 * volatility^2) / 180), 2))

        Validates: Requirements 5.1
        """
        _set_user_state(app, advanced_purchased=1, advanced_active=1)
        user_id = _get_user_id(app)

        # Insert position on Gold (id=4, price=50.00, volatility=0.9)
        _insert_short_position(
            app, user_id, ore_id=4, share_quantity=200,
            entry_price=55.00, locked_collateral=15000.00,
        )

        # Insert position on Lapis Lazuli (id=5, price=30.00, volatility=1.0)
        _insert_short_position(
            app, user_id, ore_id=5, share_quantity=100,
            entry_price=35.00, locked_collateral=5000.00,
        )

        ore_gold = _get_ore_data(app, 4)
        ore_lapis = _get_ore_data(app, 5)

        ticks_per_hour = 180  # 3600 / 20

        # Gold: short_value = 200 * 50.00 = 10000.00
        sv_gold = 200 * ore_gold['current_price']
        fee_gold = round(sv_gold * ((0.005 + 0.10 * ore_gold['volatility'] ** 2) / ticks_per_hour), 2)

        # Lapis: short_value = 100 * 30.00 = 3000.00
        sv_lapis = 100 * ore_lapis['current_price']
        fee_lapis = round(sv_lapis * ((0.005 + 0.10 * ore_lapis['volatility'] ** 2) / ticks_per_hour), 2)

        expected_fee_burn_per_tick = fee_gold + fee_lapis

        response = authenticated_client.get('/finances')
        assert response.status_code == 200
        html = response.data.decode('utf-8')

        # The fee burn per tick should appear formatted in the page
        # Format: -$X.XX / tick
        expected_formatted = f"${expected_fee_burn_per_tick:,.2f}"
        assert expected_formatted in html, (
            f"Expected fee burn '{expected_formatted}' not found in HTML. "
            f"Gold fee={fee_gold}, Lapis fee={fee_lapis}, total={expected_fee_burn_per_tick}"
        )

    def test_account_reset_returns_403(self, authenticated_client, app):
        """Account reset while on finances → next GET /finances returns 403.

        Validates: Requirements 9.1
        """
        _set_user_state(app, advanced_purchased=1, advanced_active=1)
        user_id = _get_user_id(app)

        # Insert a position so finances page has content
        _insert_short_position(
            app, user_id, ore_id=1, share_quantity=10,
            entry_price=10.00, locked_collateral=200.00,
        )

        # Verify finances works initially
        response = authenticated_client.get('/finances')
        assert response.status_code == 200

        # Perform account reset (this clears advanced mode state)
        with app.app_context():
            from app.models import reset_account
            reset_account(user_id)

        # Next request to finances should return 403 (advanced mode revoked)
        response = authenticated_client.get('/finances')
        assert response.status_code == 403

    def test_toggle_advanced_off_returns_403(self, authenticated_client, app):
        """Toggle Advanced Mode off → next GET /finances returns 403.

        Validates: Requirements 9.2
        """
        _set_user_state(app, advanced_purchased=1, advanced_active=1)

        # Verify finances works initially
        response = authenticated_client.get('/finances')
        assert response.status_code == 200

        # Toggle advanced mode off
        _set_user_state(app, advanced_active=0)

        # Next request should return 403
        response = authenticated_client.get('/finances')
        assert response.status_code == 403

    def test_multiple_positions_aggregates_match(self, authenticated_client, app):
        """Multiple positions → verify aggregates match individual rows.

        Validates: Requirements 4.5
        """
        _set_user_state(app, advanced_purchased=1, advanced_active=1)
        user_id = _get_user_id(app)

        # Insert multiple positions
        # Position 1: Coal (id=1, price=10.00, volatility=0.5), 100 shares
        _insert_short_position(
            app, user_id, ore_id=1, share_quantity=100,
            entry_price=12.00, locked_collateral=1800.00,
            cumulative_fees_paid=25.50,
        )
        # Position 2: Iron (id=2, price=25.00, volatility=0.6), 50 shares
        _insert_short_position(
            app, user_id, ore_id=2, share_quantity=50,
            entry_price=28.00, locked_collateral=2100.00,
            cumulative_fees_paid=10.00,
        )
        # Position 3: Copper (id=3, price=15.00, volatility=0.8), 200 shares
        _insert_short_position(
            app, user_id, ore_id=3, share_quantity=200,
            entry_price=18.00, locked_collateral=5400.00,
            cumulative_fees_paid=55.75,
        )

        ore_coal = _get_ore_data(app, 1)
        ore_iron = _get_ore_data(app, 2)
        ore_copper = _get_ore_data(app, 3)

        # Calculate expected aggregates
        exposure_coal = 100 * ore_coal['current_price']
        exposure_iron = 50 * ore_iron['current_price']
        exposure_copper = 200 * ore_copper['current_price']
        expected_total_exposure = exposure_coal + exposure_iron + exposure_copper
        expected_total_fees = 25.50 + 10.00 + 55.75
        expected_position_count = 3

        response = authenticated_client.get('/finances')
        assert response.status_code == 200
        html = response.data.decode('utf-8')

        # Verify position count
        assert f'Positions: <strong>{expected_position_count}</strong>' in html

        # Verify total exposure
        expected_exposure_str = f"${expected_total_exposure:,.2f}"
        assert f'Total Exposure: <strong>{expected_exposure_str}</strong>' in html

        # Verify total fees paid
        expected_fees_str = f"${expected_total_fees:,.2f}"
        assert f'Total Fees Paid: <strong>{expected_fees_str}</strong>' in html

    def test_zero_free_cash_displays_correctly(self, authenticated_client, app):
        """Zero free cash with active shorts → displays "$0.00" and "0 ticks" with red indicator.

        Validates: Requirements 9.4
        """
        _set_user_state(app, advanced_purchased=1, advanced_active=1)
        user_id = _get_user_id(app)

        # Set balance to zero
        conn = sqlite3.connect(app.config['DATABASE_PATH'])
        conn.execute("UPDATE users SET balance = 0 WHERE id = ?", (user_id,))
        conn.commit()
        conn.close()

        # Insert an active short position on Diamond (id=8, price=100.00)
        _insert_short_position(
            app, user_id, ore_id=8, share_quantity=10,
            entry_price=100.00, locked_collateral=1500.00,
        )

        response = authenticated_client.get('/finances')
        assert response.status_code == 200
        html = response.data.decode('utf-8')

        # Verify "$0.00" displayed for Free Cash
        assert '$0.00' in html

        # Verify "0 ticks" in cash runway (format: ~0 ticks / ~0m)
        assert '~0 ticks' in html

        # Verify red indicator class
        assert 'runway-bar--red' in html

        # Verify "Liquidation imminent" warning
        assert 'Liquidation imminent' in html
