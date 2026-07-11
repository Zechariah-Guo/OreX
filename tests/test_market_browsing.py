"""Tests for market browsing.

Covers market overview, ore detail pages, price history API, HTMX partials,
and unauthenticated access control.
"""

import pytest

pytestmark = pytest.mark.market_browsing

# All 9 ore names from seed data
ORE_NAMES = [
    'Coal', 'Iron', 'Copper', 'Gold', 'Lapis Lazuli',
    'Redstone', 'Emerald', 'Diamond', 'Netherite',
]


class TestMarketBrowsing:
    """Tests for market overview and detail pages."""

    def test_market_overview_lists_all_ores(self, authenticated_client):
        """TC: /market lists all 9 ore names."""
        response = authenticated_client.get('/market')
        assert response.status_code == 200
        html = response.data.decode('utf-8')
        for ore_name in ORE_NAMES:
            assert ore_name in html, f"Expected '{ore_name}' in market overview"

    def test_ore_detail_shows_name_price_base(self, authenticated_client):
        """TC: /market/<ore_id> shows ore name, current price, base price."""
        # Use ore_id=1 (Coal: current_price=10.00, base_price=10.00)
        response = authenticated_client.get('/market/1')
        assert response.status_code == 200
        html = response.data.decode('utf-8')
        assert 'Coal' in html
        assert '10.00' in html  # current_price and base_price are both 10.00

    def test_ore_price_history_json(self, authenticated_client):
        """TC: /market/<ore_id>/history returns JSON with price and time fields for multiple range values."""
        for range_val in ('5m', '1h'):
            response = authenticated_client.get(f'/market/1/history?range={range_val}')
            assert response.status_code == 200
            data = response.get_json()
            assert isinstance(data, list)
            # If there are entries, verify they have the expected fields
            for entry in data:
                assert 'price' in entry, f"Missing 'price' field in history entry for range={range_val}"
                assert 'time' in entry, f"Missing 'time' field in history entry for range={range_val}"

    def test_htmx_market_overview_partial(self, authenticated_client):
        """TC: HTMX partial for /market returns partial HTML without full layout."""
        response = authenticated_client.get('/market', headers={'HX-Request': 'true'})
        assert response.status_code == 200
        html = response.data.decode('utf-8')
        # Should NOT contain full page layout markers
        assert '<!DOCTYPE' not in html
        assert '<html' not in html
        # Should contain ore price data (at least one ore name)
        assert 'Coal' in html
        assert 'ore-card' in html

    def test_htmx_ore_detail_partial(self, authenticated_client):
        """TC: HTMX partial for /market/<ore_id> returns current price and movement."""
        response = authenticated_client.get('/market/1', headers={'HX-Request': 'true'})
        assert response.status_code == 200
        html = response.data.decode('utf-8')
        # Should NOT contain full page layout
        assert '<!DOCTYPE' not in html
        assert '<html' not in html
        # Should contain current price (Coal = $10.00)
        assert '10.00' in html
        # Should contain movement indicator (trend direction class)
        assert 'stat-card__value--' in html

    def test_unauthenticated_access_redirects_to_login(self, client):
        """TC: unauthenticated access redirects to /login."""
        response = client.get('/market', follow_redirects=False)
        assert response.status_code == 302
        location = response.headers.get('Location', '')
        assert '/login' in location

        # Follow redirect to verify the flash message
        response = client.get('/market', follow_redirects=True)
        html = response.data.decode('utf-8')
        assert 'Please log in to access this page.' in html
