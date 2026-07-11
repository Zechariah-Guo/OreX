"""Tests for portfolio.

Covers holdings display, P/L calculations, empty state, HTMX partials,
and unauthenticated access control.
"""

import sqlite3

import pytest
from hypothesis import given, settings, HealthCheck
from hypothesis import strategies as st

from conftest import get_csrf_token, register_user, login_user

pytestmark = pytest.mark.portfolio


class TestPortfolio:
    """Tests for portfolio display and profit/loss calculations."""

    def test_authenticated_user_with_holdings(self, authenticated_client, app):
        """TC: authenticated user with holdings sees ore names, quantities, prices, P/L.

        Validates: Requirements 5.1
        """
        # Buy some Coal (ore_id=1, current_price=10.00) to create a holding
        # First get CSRF token from the buy page
        buy_page = authenticated_client.get('/trade/buy/1')
        # The buy route redirects to ore detail page on GET, so get CSRF from market page
        market_page = authenticated_client.get('/market/1')
        token = get_csrf_token(market_page)

        # Submit buy order (two-step: first POST without confirmed, then with confirmed)
        # Step 1: Submit quantity to get confirmation page
        confirm_resp = authenticated_client.post('/trade/buy/1', data={
            'quantity': '5',
            'csrf_token': token,
        }, follow_redirects=True)
        # Get CSRF from confirmation page
        confirm_token = get_csrf_token(confirm_resp)

        # Step 2: Confirm the trade
        authenticated_client.post('/trade/buy/1', data={
            'quantity': '5',
            'confirmed': '1',
            'csrf_token': confirm_token,
        }, follow_redirects=True)

        # Now update Coal's current_price to 15.00 to create a known P/L
        conn = sqlite3.connect(app.config['DATABASE_PATH'])
        conn.execute("UPDATE ores SET current_price = 15.00 WHERE id = 1")
        conn.commit()
        conn.close()

        # Request portfolio page
        response = authenticated_client.get('/portfolio')
        assert response.status_code == 200
        html = response.data.decode('utf-8')

        # Verify holdings data is displayed
        assert 'Coal' in html                   # ore name
        assert '5' in html                      # quantity
        assert '10.00' in html                  # avg purchase price
        assert '15.00' in html                  # current price
        # P/L = (15 - 10) * 5 = 25.00
        assert '25.00' in html                  # profit/loss amount
        # P/L% = ((15/10) - 1) * 100 = 50.0%
        assert '50.0' in html                   # profit/loss percentage

    def test_authenticated_user_no_holdings(self, authenticated_client):
        """TC: authenticated user with no holdings sees $0 total and full cash balance.

        Validates: Requirements 5.2
        """
        response = authenticated_client.get('/portfolio')
        assert response.status_code == 200
        html = response.data.decode('utf-8')

        # Should show $0.00 for holdings value
        assert '0.00' in html
        # Should show full cash balance of $10,000.00
        assert '10000.00' in html
        # Should show empty state message
        assert "You don't own any ores yet" in html or 'Browse the Market' in html

    def test_profit_loss_calculation(self, authenticated_client, app):
        """TC: P/L equals (current_price - avg_purchase_price) * quantity and
        percentage ((current_price / avg_purchase_price) - 1) * 100.

        Validates: Requirements 5.3
        """
        # Buy Coal at current_price=10.00
        market_page = authenticated_client.get('/market/1')
        token = get_csrf_token(market_page)

        # Step 1: Submit quantity
        confirm_resp = authenticated_client.post('/trade/buy/1', data={
            'quantity': '10',
            'csrf_token': token,
        }, follow_redirects=True)
        confirm_token = get_csrf_token(confirm_resp)

        # Step 2: Confirm
        authenticated_client.post('/trade/buy/1', data={
            'quantity': '10',
            'confirmed': '1',
            'csrf_token': confirm_token,
        }, follow_redirects=True)

        # Manipulate current_price to 12.50 to create a precise P/L
        conn = sqlite3.connect(app.config['DATABASE_PATH'])
        conn.execute("UPDATE ores SET current_price = 12.50 WHERE id = 1")
        conn.commit()
        conn.close()

        # Request portfolio
        response = authenticated_client.get('/portfolio')
        assert response.status_code == 200
        html = response.data.decode('utf-8')

        # Expected P/L: (12.50 - 10.00) * 10 = 25.00
        assert '25.00' in html
        # Expected P/L%: ((12.50 / 10.00) - 1) * 100 = 25.0%
        assert '25.0' in html

    def test_htmx_partial_returns_portfolio_totals(self, authenticated_client, app):
        """TC: HTMX partial returns portfolio totals with latest prices.

        Validates: Requirements 5.4
        """
        # Buy Coal to have holdings
        market_page = authenticated_client.get('/market/1')
        token = get_csrf_token(market_page)

        confirm_resp = authenticated_client.post('/trade/buy/1', data={
            'quantity': '3',
            'csrf_token': token,
        }, follow_redirects=True)
        confirm_token = get_csrf_token(confirm_resp)

        authenticated_client.post('/trade/buy/1', data={
            'quantity': '3',
            'confirmed': '1',
            'csrf_token': confirm_token,
        }, follow_redirects=True)

        # Request with HX-Request header for HTMX partial
        response = authenticated_client.get('/portfolio', headers={'HX-Request': 'true'})
        assert response.status_code == 200
        html = response.data.decode('utf-8')

        # Should NOT contain full page layout
        assert '<!DOCTYPE' not in html
        assert '<html' not in html

        # Should contain portfolio summary data
        assert 'Cash Balance' in html
        assert 'Holdings Value' in html
        assert 'Total Portfolio' in html
        # Should contain the current price of Coal ($10.00)
        assert '10.00' in html

    def test_unauthenticated_access_redirects_to_login(self, client):
        """TC: unauthenticated access redirects to /login.

        Validates: Requirements 5.5
        """
        response = client.get('/portfolio', follow_redirects=False)
        assert response.status_code == 302
        location = response.headers.get('Location', '')
        assert '/login' in location


# Feature: orex-test-suite, Property 5: Portfolio profit/loss calculation
class TestPortfolioProperties:
    """Property-based tests for portfolio profit/loss calculations.

    **Validates: Requirements 5.3**
    """

    @given(
        quantity=st.integers(min_value=1, max_value=100),
        avg_purchase_price=st.floats(min_value=1.0, max_value=100.0),
        current_price=st.floats(min_value=1.0, max_value=200.0),
    )
    @settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
    def test_profit_loss_calculation_property(self, quantity, avg_purchase_price, current_price, authenticated_client, app):
        """Property: P/L amount == (current_price - avg_purchase_price) * quantity
        and P/L percentage == ((current_price / avg_purchase_price) - 1) * 100.

        **Validates: Requirements 5.3**
        """
        db_path = app.config['DATABASE_PATH']
        conn = sqlite3.connect(db_path)

        # Get the user_id for TestUser1 (created by authenticated_client fixture)
        user_row = conn.execute(
            "SELECT id FROM users WHERE username = 'TestUser1'"
        ).fetchone()
        user_id = user_row[0]

        # Clear any existing holdings and reset ore price for a clean state
        conn.execute("DELETE FROM holdings WHERE user_id = ?", (user_id,))
        conn.execute(
            "UPDATE ores SET current_price = ? WHERE id = 1",
            (current_price,)
        )
        conn.execute(
            "INSERT INTO holdings (user_id, ore_id, quantity, avg_purchase_price) VALUES (?, 1, ?, ?)",
            (user_id, quantity, avg_purchase_price)
        )
        conn.commit()
        conn.close()

        # Request portfolio page
        response = authenticated_client.get('/portfolio')
        assert response.status_code == 200
        html = response.data.decode('utf-8')

        # Calculate expected P/L values
        expected_pl = (current_price - avg_purchase_price) * quantity
        expected_pl_pct = ((current_price / avg_purchase_price) - 1) * 100

        # Verify P/L amount (rendered as "%.2f")
        expected_pl_str = f"{expected_pl:.2f}"
        assert expected_pl_str in html, (
            f"Expected P/L amount '{expected_pl_str}' not found in HTML "
            f"(qty={quantity}, avg={avg_purchase_price}, cur={current_price})"
        )

        # Verify P/L percentage (rendered as "%.1f")
        expected_pct_str = f"{expected_pl_pct:.1f}"
        assert expected_pct_str in html, (
            f"Expected P/L percentage '{expected_pct_str}%' not found in HTML "
            f"(qty={quantity}, avg={avg_purchase_price}, cur={current_price})"
        )
