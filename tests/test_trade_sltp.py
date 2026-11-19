"""Unit tests for trade route SL/TP integration.

Covers:
- Buy order with valid SL/TP creates a stop_loss_take_profit record
- Buy order with invalid SL (SL >= price) returns validation error
- Buy order with invalid TP (TP <= price) returns validation error
- SL/TP modification on existing holding
- Unauthorized modification attempt returns 403

Requirements: 6.1, 6.2, 6.5, 6.6, 6.7
"""

import sqlite3

import pytest

from conftest import get_csrf_token, register_user

pytestmark = pytest.mark.trade_sltp


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_user_id(app, username='TestUser1'):
    """Look up user ID by username."""
    conn = sqlite3.connect(app.config['DATABASE_PATH'])
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT id FROM users WHERE username = ?", (username,)).fetchone()
    conn.close()
    return row['id']


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


def _get_ore(app, ore_id=1):
    """Fetch an ore row by ID."""
    conn = sqlite3.connect(app.config['DATABASE_PATH'])
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT * FROM ores WHERE id = ?", (ore_id,)).fetchone()
    conn.close()
    return dict(row)


def _get_sltp_records(app, holding_id):
    """Fetch all SL/TP records for a holding."""
    conn = sqlite3.connect(app.config['DATABASE_PATH'])
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT * FROM stop_loss_take_profit WHERE holding_id = ?",
        (holding_id,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def _get_holding_for_user(app, user_id, ore_id):
    """Fetch a holding for a user/ore pair."""
    conn = sqlite3.connect(app.config['DATABASE_PATH'])
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT * FROM holdings WHERE user_id = ? AND ore_id = ?",
        (user_id, ore_id)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def _create_holding(app, user_id, ore_id, quantity, avg_price):
    """Insert a holding directly into the database. Returns the holding ID."""
    conn = sqlite3.connect(app.config['DATABASE_PATH'])
    cursor = conn.execute(
        "INSERT INTO holdings (user_id, ore_id, quantity, avg_purchase_price) VALUES (?, ?, ?, ?)",
        (user_id, ore_id, quantity, avg_price)
    )
    conn.commit()
    holding_id = cursor.lastrowid
    conn.close()
    return holding_id


def _create_sltp(app, holding_id, stop_loss=None, take_profit=None):
    """Insert a SL/TP record directly. Returns the record ID."""
    conn = sqlite3.connect(app.config['DATABASE_PATH'])
    cursor = conn.execute(
        "INSERT INTO stop_loss_take_profit (holding_id, stop_loss, take_profit, active) VALUES (?, ?, ?, 1)",
        (holding_id, stop_loss, take_profit)
    )
    conn.commit()
    sltp_id = cursor.lastrowid
    conn.close()
    return sltp_id


def _execute_buy(client, ore_id, quantity, stop_loss=None, take_profit=None):
    """Execute the two-step buy flow (initial POST → confirmation POST).

    Returns the final response (after confirmation).
    """
    # Step 1: Initial POST to get confirmation page (ore detail is at /market/<ore_id>)
    ore_detail_resp = client.get(f'/market/{ore_id}')
    token = get_csrf_token(ore_detail_resp)

    confirm_resp = client.post(f'/trade/buy/{ore_id}', data={
        'csrf_token': token,
        'quantity': str(quantity),
    }, follow_redirects=True)

    # Step 2: Extract CSRF from confirmation page and POST with confirmed=1
    token2 = get_csrf_token(confirm_resp)
    data = {
        'csrf_token': token2,
        'quantity': str(quantity),
        'confirmed': '1',
    }
    if stop_loss is not None:
        data['stop_loss'] = str(stop_loss)
    if take_profit is not None:
        data['take_profit'] = str(take_profit)

    return client.post(f'/trade/buy/{ore_id}', data=data, follow_redirects=True)


# ---------------------------------------------------------------------------
# Tests: Buy with valid SL/TP
# ---------------------------------------------------------------------------

class TestBuyWithValidSLTP:
    """Tests for buy orders with valid stop_loss and take_profit values."""

    def test_buy_with_valid_sl_tp_creates_record(self, authenticated_client, app):
        """Advanced-active user buying with valid SL/TP creates a sltp record.

        Requirements: 6.1, 6.2
        """
        # Set up: advanced mode active, sufficient balance
        _set_user_state(app, balance=50000.0, advanced_eligible=1,
                        advanced_purchased=1, advanced_active=1)

        # Ore 1 (Coal) has current_price = 10.00
        ore = _get_ore(app, ore_id=1)
        assert ore['current_price'] == 10.00

        # Buy 5 Coal with SL=5.00, TP=20.00
        response = _execute_buy(authenticated_client, ore_id=1, quantity=5,
                                stop_loss=5.00, take_profit=20.00)

        assert response.status_code == 200
        assert b'Successfully bought' in response.data

        # Verify the holding was created
        user_id = _get_user_id(app)
        holding = _get_holding_for_user(app, user_id, ore_id=1)
        assert holding is not None
        assert holding['quantity'] == 5

        # Verify the SL/TP record was created
        sltp_records = _get_sltp_records(app, holding['id'])
        assert len(sltp_records) == 1
        assert sltp_records[0]['stop_loss'] == 5.00
        assert sltp_records[0]['take_profit'] == 20.00
        assert sltp_records[0]['active'] == 1

    def test_buy_with_only_sl_creates_record(self, authenticated_client, app):
        """Advanced-active user buying with only stop_loss (no TP) creates a record.

        Requirements: 6.1
        """
        _set_user_state(app, balance=50000.0, advanced_eligible=1,
                        advanced_purchased=1, advanced_active=1)

        # Buy 3 Coal with SL=8.00, no TP
        response = _execute_buy(authenticated_client, ore_id=1, quantity=3,
                                stop_loss=8.00)

        assert response.status_code == 200
        assert b'Successfully bought' in response.data

        user_id = _get_user_id(app)
        holding = _get_holding_for_user(app, user_id, ore_id=1)
        sltp_records = _get_sltp_records(app, holding['id'])
        assert len(sltp_records) == 1
        assert sltp_records[0]['stop_loss'] == 8.00
        assert sltp_records[0]['take_profit'] is None

    def test_buy_with_only_tp_creates_record(self, authenticated_client, app):
        """Advanced-active user buying with only take_profit (no SL) creates a record.

        Requirements: 6.2
        """
        _set_user_state(app, balance=50000.0, advanced_eligible=1,
                        advanced_purchased=1, advanced_active=1)

        # Buy 2 Coal with TP=15.00, no SL
        response = _execute_buy(authenticated_client, ore_id=1, quantity=2,
                                take_profit=15.00)

        assert response.status_code == 200
        assert b'Successfully bought' in response.data

        user_id = _get_user_id(app)
        holding = _get_holding_for_user(app, user_id, ore_id=1)
        sltp_records = _get_sltp_records(app, holding['id'])
        assert len(sltp_records) == 1
        assert sltp_records[0]['stop_loss'] is None
        assert sltp_records[0]['take_profit'] == 15.00


# ---------------------------------------------------------------------------
# Tests: Buy with invalid SL/TP
# ---------------------------------------------------------------------------

class TestBuyWithInvalidSLTP:
    """Tests for buy orders with invalid stop_loss / take_profit values."""

    def test_buy_with_sl_equal_to_price_rejected(self, authenticated_client, app):
        """Stop loss equal to current price is rejected.

        Requirements: 6.5
        """
        _set_user_state(app, balance=50000.0, advanced_eligible=1,
                        advanced_purchased=1, advanced_active=1)

        # Coal price = 10.00, set SL = 10.00 (invalid: must be < price)
        response = _execute_buy(authenticated_client, ore_id=1, quantity=5,
                                stop_loss=10.00)

        assert response.status_code == 200
        assert b'Stop loss must be below current price' in response.data

        # Verify no holding or SL/TP record created
        user_id = _get_user_id(app)
        holding = _get_holding_for_user(app, user_id, ore_id=1)
        assert holding is None

    def test_buy_with_sl_above_price_rejected(self, authenticated_client, app):
        """Stop loss above current price is rejected.

        Requirements: 6.5
        """
        _set_user_state(app, balance=50000.0, advanced_eligible=1,
                        advanced_purchased=1, advanced_active=1)

        # Coal price = 10.00, set SL = 12.00 (invalid: above price)
        response = _execute_buy(authenticated_client, ore_id=1, quantity=5,
                                stop_loss=12.00)

        assert response.status_code == 200
        assert b'Stop loss must be below current price' in response.data

        user_id = _get_user_id(app)
        holding = _get_holding_for_user(app, user_id, ore_id=1)
        assert holding is None

    def test_buy_with_tp_equal_to_price_rejected(self, authenticated_client, app):
        """Take profit equal to current price is rejected.

        Requirements: 6.6
        """
        _set_user_state(app, balance=50000.0, advanced_eligible=1,
                        advanced_purchased=1, advanced_active=1)

        # Coal price = 10.00, set TP = 10.00 (invalid: must be > price)
        response = _execute_buy(authenticated_client, ore_id=1, quantity=5,
                                take_profit=10.00)

        assert response.status_code == 200
        assert b'Take profit must be above current price' in response.data

        user_id = _get_user_id(app)
        holding = _get_holding_for_user(app, user_id, ore_id=1)
        assert holding is None

    def test_buy_with_tp_below_price_rejected(self, authenticated_client, app):
        """Take profit below current price is rejected.

        Requirements: 6.6
        """
        _set_user_state(app, balance=50000.0, advanced_eligible=1,
                        advanced_purchased=1, advanced_active=1)

        # Coal price = 10.00, set TP = 8.00 (invalid: below price)
        response = _execute_buy(authenticated_client, ore_id=1, quantity=5,
                                take_profit=8.00)

        assert response.status_code == 200
        assert b'Take profit must be above current price' in response.data

        user_id = _get_user_id(app)
        holding = _get_holding_for_user(app, user_id, ore_id=1)
        assert holding is None


# ---------------------------------------------------------------------------
# Tests: SL/TP Modification on existing holding
# ---------------------------------------------------------------------------

class TestSLTPModification:
    """Tests for POST /trade/sltp/<holding_id> endpoint."""

    def test_modify_sltp_updates_existing_record(self, authenticated_client, app):
        """Advanced user can modify SL/TP on an existing holding.

        Requirements: 6.7
        """
        _set_user_state(app, balance=50000.0, advanced_eligible=1,
                        advanced_purchased=1, advanced_active=1)

        user_id = _get_user_id(app)

        # Create a holding and existing SL/TP record directly
        # Coal price = 10.00
        holding_id = _create_holding(app, user_id, ore_id=1, quantity=10, avg_price=10.00)
        _create_sltp(app, holding_id, stop_loss=5.00, take_profit=15.00)

        # Get CSRF from any page
        settings_resp = authenticated_client.get('/settings')
        token = get_csrf_token(settings_resp)

        # Modify SL/TP to new valid values
        response = authenticated_client.post(f'/trade/sltp/{holding_id}', data={
            'csrf_token': token,
            'stop_loss': '7.00',
            'take_profit': '18.00',
        }, follow_redirects=True)

        assert response.status_code == 200
        assert b'updated' in response.data

        # Verify the record was updated
        sltp_records = _get_sltp_records(app, holding_id)
        assert len(sltp_records) == 1
        assert sltp_records[0]['stop_loss'] == 7.00
        assert sltp_records[0]['take_profit'] == 18.00
        assert sltp_records[0]['active'] == 1

    def test_modify_sltp_creates_new_if_none_exists(self, authenticated_client, app):
        """Advanced user can set SL/TP on a holding that has no existing order.

        Requirements: 6.7
        """
        _set_user_state(app, balance=50000.0, advanced_eligible=1,
                        advanced_purchased=1, advanced_active=1)

        user_id = _get_user_id(app)

        # Create a holding without any SL/TP
        holding_id = _create_holding(app, user_id, ore_id=1, quantity=10, avg_price=10.00)

        settings_resp = authenticated_client.get('/settings')
        token = get_csrf_token(settings_resp)

        response = authenticated_client.post(f'/trade/sltp/{holding_id}', data={
            'csrf_token': token,
            'stop_loss': '6.00',
            'take_profit': '16.00',
        }, follow_redirects=True)

        assert response.status_code == 200
        assert b'updated' in response.data

        sltp_records = _get_sltp_records(app, holding_id)
        assert len(sltp_records) == 1
        assert sltp_records[0]['stop_loss'] == 6.00
        assert sltp_records[0]['take_profit'] == 16.00

    def test_remove_sltp_deactivates_record(self, authenticated_client, app):
        """Posting empty SL/TP values deactivates the existing order.

        Requirements: 6.7
        """
        _set_user_state(app, balance=50000.0, advanced_eligible=1,
                        advanced_purchased=1, advanced_active=1)

        user_id = _get_user_id(app)
        holding_id = _create_holding(app, user_id, ore_id=1, quantity=10, avg_price=10.00)
        _create_sltp(app, holding_id, stop_loss=5.00, take_profit=15.00)

        settings_resp = authenticated_client.get('/settings')
        token = get_csrf_token(settings_resp)

        # Post with empty SL/TP values
        response = authenticated_client.post(f'/trade/sltp/{holding_id}', data={
            'csrf_token': token,
            'stop_loss': '',
            'take_profit': '',
        }, follow_redirects=True)

        assert response.status_code == 200
        assert b'removed' in response.data

        # Verify the record is deactivated
        conn = sqlite3.connect(app.config['DATABASE_PATH'])
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM stop_loss_take_profit WHERE holding_id = ?",
            (holding_id,)
        ).fetchone()
        conn.close()
        assert row['active'] == 0


# ---------------------------------------------------------------------------
# Tests: Unauthorized modification
# ---------------------------------------------------------------------------

class TestUnauthorizedSLTPModification:
    """Tests for unauthorized access to /trade/sltp/<holding_id>."""

    def test_modify_other_users_holding_is_refused_without_revealing(self, authenticated_client, app):
        """Another user's holding is not modified and gets the same response as a
        closed/nonexistent holding (no 403, so existence is not revealed).

        Requirements: 6.7
        """
        _set_user_state(app, balance=50000.0, advanced_eligible=1,
                        advanced_purchased=1, advanced_active=1)

        # Create another user directly in the DB
        conn = sqlite3.connect(app.config['DATABASE_PATH'])
        conn.execute(
            "INSERT INTO users (username, password_hash, balance) VALUES (?, ?, ?)",
            ('OtherUser', 'fakehash', 50000.0)
        )
        conn.commit()
        other_user = conn.execute(
            "SELECT id FROM users WHERE username = 'OtherUser'"
        ).fetchone()
        other_user_id = other_user[0]

        # Create a holding for the other user
        cursor = conn.execute(
            "INSERT INTO holdings (user_id, ore_id, quantity, avg_purchase_price) VALUES (?, ?, ?, ?)",
            (other_user_id, 1, 10, 10.00)
        )
        conn.commit()
        other_holding_id = cursor.lastrowid
        conn.close()

        # Authenticated as TestUser1, try to modify OtherUser's holding
        settings_resp = authenticated_client.get('/settings')
        token = get_csrf_token(settings_resp)

        response = authenticated_client.post(f'/trade/sltp/{other_holding_id}', data={
            'csrf_token': token,
            'stop_loss': '5.00',
            'take_profit': '20.00',
        }, follow_redirects=False)

        assert response.status_code == 302
        assert '/portfolio' in response.headers['Location']
        assert _get_sltp_records(app, other_holding_id) == []

        # Same outcome as an id that does not exist at all
        missing = authenticated_client.post('/trade/sltp/999999', data={
            'csrf_token': token,
            'stop_loss': '5.00',
            'take_profit': '20.00',
        }, follow_redirects=False)
        assert missing.status_code == response.status_code
        assert missing.headers['Location'] == response.headers['Location']


# ---------------------------------------------------------------------------
# Tests: Position closed while the SL/TP modal was open
# ---------------------------------------------------------------------------

CLOSED_MSG = b'already closed, so the stop loss / take profit was not changed'


def _create_short(app, user_id, ore_id=1, status='active'):
    """Insert a short position directly. Returns the position ID."""
    conn = sqlite3.connect(app.config['DATABASE_PATH'])
    cursor = conn.execute(
        """INSERT INTO short_positions
           (user_id, ore_id, share_quantity, entry_price, locked_collateral,
            stop_loss_price, take_profit_price, status)
           VALUES (?, ?, 10, 10.00, 100.0, 15.00, 5.00, ?)""",
        (user_id, ore_id, status),
    )
    conn.commit()
    pos_id = cursor.lastrowid
    conn.close()
    return pos_id


class TestSLTPOnClosedPosition:
    """Submitting SL/TP after the engine closed the position is not a 403."""

    def test_long_closed_by_engine_gets_friendly_redirect(self, authenticated_client, app):
        _set_user_state(app, balance=50000.0, advanced_eligible=1,
                        advanced_purchased=1, advanced_active=1)
        user_id = _get_user_id(app)
        holding_id = _create_holding(app, user_id, ore_id=1, quantity=10, avg_price=10.00)
        _create_sltp(app, holding_id, stop_loss=5.00, take_profit=15.00)
        token = get_csrf_token(authenticated_client.get('/settings'))

        # Engine triggers SL/TP: the holding row is deleted
        conn = sqlite3.connect(app.config['DATABASE_PATH'])
        conn.execute("DELETE FROM holdings WHERE id = ?", (holding_id,))
        conn.commit()
        conn.close()

        response = authenticated_client.post(f'/trade/sltp/{holding_id}', data={
            'csrf_token': token, 'stop_loss': '7.00', 'take_profit': '18.00',
        }, follow_redirects=True)

        assert response.status_code == 200
        assert CLOSED_MSG in response.data

    def test_short_closed_gets_friendly_redirect(self, authenticated_client, app):
        _set_user_state(app, balance=50000.0, advanced_eligible=1,
                        advanced_purchased=1, advanced_active=1)
        user_id = _get_user_id(app)
        position_id = _create_short(app, user_id, status='closed')
        token = get_csrf_token(authenticated_client.get('/settings'))

        response = authenticated_client.post(f'/trade/short/edit/{position_id}', data={
            'csrf_token': token, 'stop_loss': '16.00', 'take_profit': '4.00',
        }, follow_redirects=True)

        assert response.status_code == 200
        assert CLOSED_MSG in response.data

    def test_other_users_short_is_refused_without_revealing(self, authenticated_client, app):
        _set_user_state(app, balance=50000.0, advanced_eligible=1,
                        advanced_purchased=1, advanced_active=1)
        conn = sqlite3.connect(app.config['DATABASE_PATH'])
        cursor = conn.execute(
            "INSERT INTO users (username, password_hash, balance) VALUES (?, ?, ?)",
            ('OtherUser', 'fakehash', 50000.0))
        other_id = cursor.lastrowid
        conn.commit()
        conn.close()
        position_id = _create_short(app, other_id)
        token = get_csrf_token(authenticated_client.get('/settings'))

        response = authenticated_client.post(f'/trade/short/edit/{position_id}', data={
            'csrf_token': token, 'stop_loss': '16.00', 'take_profit': '4.00',
        }, follow_redirects=False)
        missing = authenticated_client.post('/trade/short/edit/999999', data={
            'csrf_token': token, 'stop_loss': '16.00', 'take_profit': '4.00',
        }, follow_redirects=False)

        assert response.status_code == 302
        assert missing.status_code == 302
        assert missing.headers['Location'] == response.headers['Location']

        conn = sqlite3.connect(app.config['DATABASE_PATH'])
        row = conn.execute(
            "SELECT stop_loss_price, take_profit_price FROM short_positions WHERE id = ?",
            (position_id,)).fetchone()
        conn.close()
        assert row == (15.00, 5.00)
