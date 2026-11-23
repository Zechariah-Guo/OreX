"""Tests for short_positions.open_factor, the (1 + multiplier) fixed at open.

The margin-call phase used to derive that factor from the vault, which grows with
every top-up, so it compounded each tick. These tests cover:
  - every opener (player, bot, tutorial demo) stores the factor,
  - the engine scales the vault from the stored factor over a rising and falling price.
"""

import importlib.util
import os
import re
import sqlite3

import pytest

from conftest import get_csrf_token

pytestmark = pytest.mark.shorting_integration

SRC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'src')


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _conn(app):
    conn = sqlite3.connect(app.config['DATABASE_PATH'])
    conn.row_factory = sqlite3.Row
    return conn


def _make_advanced(app, username='TestUser1', balance=10000.0):
    conn = _conn(app)
    conn.execute(
        """UPDATE users SET balance = ?, advanced_eligible = 1, advanced_purchased = 1,
               advanced_active = 1 WHERE username = ?""",
        (balance, username),
    )
    user_id = conn.execute("SELECT id FROM users WHERE username = ?", (username,)).fetchone()['id']
    conn.commit()
    conn.close()
    return user_id


def _add_short(app, user_id, factor, shares=100, entry=10.0, vault=1500.0, ore_id=1):
    conn = _conn(app)
    cur = conn.execute(
        """INSERT INTO short_positions
           (user_id, ore_id, share_quantity, entry_price, locked_collateral,
            cumulative_fees_paid, status, open_factor)
           VALUES (?, ?, ?, ?, ?, 0, 'active', ?)""",
        (user_id, ore_id, shares, entry, vault, factor),
    )
    conn.commit()
    pos_id = cur.lastrowid
    conn.close()
    return pos_id


def _set_price(app, ore_id, price):
    conn = _conn(app)
    conn.execute("UPDATE ores SET current_price = ? WHERE id = ?", (price, ore_id))
    conn.commit()
    conn.close()


def _tick(app):
    with app.app_context():
        from app.database import get_db
        from app.market.shorting import process_short_positions
        process_short_positions(get_db())


def _position(app, pos_id):
    conn = _conn(app)
    row = conn.execute("SELECT * FROM short_positions WHERE id = ?", (pos_id,)).fetchone()
    conn.close()
    return row


# ---------------------------------------------------------------------------
# Every opener stores the factor
# ---------------------------------------------------------------------------

class TestOpenersStoreTheFactor:

    def _assert_factor_matches_vault(self, row):
        factor = row['open_factor']
        assert factor is not None
        # factor = vault / (entry x shares), up to the cent rounding of the vault
        implied = row['locked_collateral'] / (row['entry_price'] * row['share_quantity'])
        assert factor == pytest.approx(implied, abs=1e-3)
        # 1 + multiplier, with the multiplier clamped to [0.5, 2.5]
        assert 1.5 - 1e-9 <= factor <= 3.5 + 1e-9

    def test_player_short_open_route(self, authenticated_client, app):
        user_id = _make_advanced(app)
        token = get_csrf_token(authenticated_client.get('/settings'))
        resp = authenticated_client.post('/trade/short/open/1', data={
            'quantity': '10', 'confirmed': '1', 'csrf_token': token,
        })
        assert resp.status_code == 302

        conn = _conn(app)
        row = conn.execute(
            "SELECT * FROM short_positions WHERE user_id = ?", (user_id,)
        ).fetchone()
        conn.close()
        assert row is not None, 'the short should have opened'
        self._assert_factor_matches_vault(row)

    def test_bot_short_open(self, authenticated_client, app):
        conn = _conn(app)
        bot_id = conn.execute(
            "INSERT INTO users (username, password_hash, balance, created_at) "
            "VALUES ('SteveBot', 'BOT_NO_LOGIN', 1000000, '2026-01-01')"
        ).lastrowid
        conn.commit()
        conn.close()

        with app.app_context():
            from app.database import get_db
            from app.market.bots import _bot_open_short
            db = get_db()
            assert _bot_open_short(db, bot_id, 1, 10, 10.0) is True
            db.commit()

        conn = _conn(app)
        row = conn.execute("SELECT * FROM short_positions WHERE user_id = ?", (bot_id,)).fetchone()
        conn.close()
        self._assert_factor_matches_vault(row)

    def test_tutorial_demo_short(self, authenticated_client, app):
        conn = _conn(app)
        user_id = conn.execute("SELECT id FROM users WHERE username = 'TestUser1'").fetchone()['id']
        conn.close()

        with app.app_context():
            from app.tutorial.demo import open_demo_short
            assert open_demo_short(user_id)['created'] is True

        conn = _conn(app)
        row = conn.execute(
            "SELECT * FROM short_positions WHERE user_id = ? AND is_demo = 1", (user_id,)
        ).fetchone()
        conn.close()
        self._assert_factor_matches_vault(row)


# ---------------------------------------------------------------------------
# The engine reads the stored factor
# ---------------------------------------------------------------------------

class TestMarginUsesStoredFactor:

    def test_vault_is_a_high_water_mark_over_a_rising_and_falling_price(self, authenticated_client, app):
        user_id = _make_advanced(app, balance=1_000_000.0)
        pos_id = _add_short(app, user_id, factor=1.5)

        high = 10.0
        for price in [10.5, 10.5, 11, 12, 12, 12, 11, 10, 13, 13, 13, 13]:
            _set_price(app, 1, price)
            _tick(app)
            high = max(high, price)
            # price x shares x factor at the highest price so far; never compounds,
            # never releases when the price falls back
            assert _position(app, pos_id)['locked_collateral'] == pytest.approx(
                high * 100 * 1.5, abs=0.01
            ), f'at price {price}'

    def test_engine_reads_the_stored_factor_not_the_vault(self, authenticated_client, app):
        """A row whose stored factor (2.0) differs from vault/(entry x shares) (1.5)
        must be topped up to price x shares x 2.0, proving nothing is derived from the vault."""
        user_id = _make_advanced(app, balance=1_000_000.0)
        pos_id = _add_short(app, user_id, factor=2.0, vault=1500.0)
        _set_price(app, 1, 10.0)
        _tick(app)
        assert _position(app, pos_id)['locked_collateral'] == pytest.approx(2000.0, abs=0.01)


# ---------------------------------------------------------------------------
# The migration runner
# ---------------------------------------------------------------------------

