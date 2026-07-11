"""Tests for transaction history.

Covers reverse chronological ordering, pagination (20 per page), archived
transaction filtering, and empty state display.
"""

import sqlite3
import time

import pytest

from conftest import get_csrf_token, register_user, login_user

pytestmark = pytest.mark.transaction_history


class TestTransactionHistory:
    """Tests for transaction history listing, pagination, and filtering."""

    def test_transactions_listed_reverse_chronological_with_all_fields(self, app, authenticated_client):
        """TC: transactions listed in reverse chronological order with all fields.

        Validates: Requirements 7.1
        """
        db_path = app.config['DATABASE_PATH']
        conn = sqlite3.connect(db_path)

        # Get the test user's ID
        user_row = conn.execute(
            "SELECT id FROM users WHERE username = 'TestUser1'"
        ).fetchone()
        user_id = user_row[0]

        # Insert 3 transactions with distinct timestamps (oldest first)
        transactions_data = [
            (user_id, 1, 'buy', 5, 10.00, 50.00, 0, '2024-01-01T10:00:00'),
            (user_id, 2, 'sell', 3, 25.00, 75.00, 0, '2024-01-02T12:00:00'),
            (user_id, 3, 'buy', 2, 15.00, 30.00, 0, '2024-01-03T14:00:00'),
        ]
        conn.executemany(
            """INSERT INTO transactions (user_id, ore_id, type, quantity,
               price_at_trade, total_value, archived, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            transactions_data,
        )
        conn.commit()
        conn.close()

        response = authenticated_client.get('/history')
        assert response.status_code == 200
        html = response.data.decode('utf-8')

        # Verify all expected fields are present
        assert 'Coal' in html       # ore_name for ore_id=1
        assert 'Iron' in html       # ore_name for ore_id=2
        assert 'Copper' in html     # ore_name for ore_id=3
        assert 'BUY' in html
        assert 'SELL' in html
        assert '10.00' in html      # price
        assert '25.00' in html      # price
        assert '50.00' in html      # total
        assert '75.00' in html      # total
        assert '2024-01-03' in html  # date

        # Verify reverse chronological order: newest (2024-01-03) before oldest (2024-01-01)
        pos_newest = html.find('Copper')    # Jan 3 transaction
        pos_middle = html.find('Iron')      # Jan 2 transaction
        pos_oldest = html.find('Coal')      # Jan 1 transaction
        assert pos_newest < pos_middle < pos_oldest, (
            "Transactions should be listed newest first"
        )

    def test_pagination_returns_20_per_page_remainder_on_page_2(self, app, authenticated_client):
        """TC: pagination returns 20 per page, remainder on page 2.

        Validates: Requirements 7.2
        """
        db_path = app.config['DATABASE_PATH']
        conn = sqlite3.connect(db_path)

        user_row = conn.execute(
            "SELECT id FROM users WHERE username = 'TestUser1'"
        ).fetchone()
        user_id = user_row[0]

        # Insert 23 transactions so page 1 has 20, page 2 has 3
        transactions_data = []
        for i in range(23):
            ts = f'2024-01-{(i + 1):02d}T10:00:00'
            transactions_data.append(
                (user_id, 1, 'buy', 1, 10.00, 10.00, 0, ts)
            )
        conn.executemany(
            """INSERT INTO transactions (user_id, ore_id, type, quantity,
               price_at_trade, total_value, archived, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            transactions_data,
        )
        conn.commit()
        conn.close()

        # Page 1 should have exactly 20 rows
        response_p1 = authenticated_client.get('/history?page=1')
        assert response_p1.status_code == 200
        html_p1 = response_p1.data.decode('utf-8')
        # Count transaction rows using the trade-badge span opening tag
        row_count_p1 = html_p1.count('<span class="trade-badge')
        assert row_count_p1 == 20, f"Page 1 should have 20 transactions, got {row_count_p1}"

        # Page 2 should have the remaining 3
        response_p2 = authenticated_client.get('/history?page=2')
        assert response_p2.status_code == 200
        html_p2 = response_p2.data.decode('utf-8')
        row_count_p2 = html_p2.count('<span class="trade-badge')
        assert row_count_p2 == 3, f"Page 2 should have 3 transactions, got {row_count_p2}"

    def test_archived_filter_includes_archived_transactions(self, app, authenticated_client):
        """TC: ?archived=1 includes archived transactions.

        Validates: Requirements 7.3
        """
        db_path = app.config['DATABASE_PATH']
        conn = sqlite3.connect(db_path)

        user_row = conn.execute(
            "SELECT id FROM users WHERE username = 'TestUser1'"
        ).fetchone()
        user_id = user_row[0]

        # Insert one active and one archived transaction
        conn.execute(
            """INSERT INTO transactions (user_id, ore_id, type, quantity,
               price_at_trade, total_value, archived, created_at)
               VALUES (?, 1, 'buy', 5, 10.00, 50.00, 0, '2024-01-01T10:00:00')""",
            (user_id,),
        )
        conn.execute(
            """INSERT INTO transactions (user_id, ore_id, type, quantity,
               price_at_trade, total_value, archived, created_at)
               VALUES (?, 2, 'sell', 3, 25.00, 75.00, 1, '2024-01-02T12:00:00')""",
            (user_id,),
        )
        conn.commit()
        conn.close()

        # Without archived filter, only the active transaction should appear
        response_no_archive = authenticated_client.get('/history')
        assert response_no_archive.status_code == 200
        html_no_archive = response_no_archive.data.decode('utf-8')
        assert 'Coal' in html_no_archive
        # The archived transaction (Iron, sell) should NOT be visible
        assert html_no_archive.count('<span class="trade-badge') == 1

        # With archived=1, both transactions should appear
        response_with_archive = authenticated_client.get('/history?archived=1')
        assert response_with_archive.status_code == 200
        html_with_archive = response_with_archive.data.decode('utf-8')
        assert 'Coal' in html_with_archive
        assert 'Iron' in html_with_archive
        assert html_with_archive.count('<span class="trade-badge') == 2

    def test_no_transactions_shows_empty_state_message(self, authenticated_client):
        """TC: no transactions shows empty state message.

        Validates: Requirements 7.4
        """
        # The authenticated_client user has no transactions in a fresh DB
        response = authenticated_client.get('/history')
        assert response.status_code == 200
        html = response.data.decode('utf-8')
        assert 'No transactions yet' in html
        assert 'Visit the market' in html
