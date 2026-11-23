"""Tests for the Portfolio page's link to Finances.

The link sits on the Advanced-only Longs/Shorts tab row, right-aligned. The
old standalone "View Finances" button row is gone, and the summary cards keep
their original order.
"""

import sqlite3


def _make_advanced(app):
    conn = sqlite3.connect(app.config['DATABASE_PATH'])
    conn.execute(
        """UPDATE users SET advanced_eligible = 1, advanced_purchased = 1,
               advanced_active = 1 WHERE username = 'TestUser1'"""
    )
    conn.commit()
    conn.close()


def _tab_row(html):
    """The markup of the Longs/Shorts tab row."""
    start = html.index('<div class="portfolio-tabs">')
    return html[start:html.index('</div>', start)]


class TestFinancesLink:

    def test_standard_mode_has_no_tabs_or_link(self, authenticated_client):
        html = authenticated_client.get('/portfolio').data.decode('utf-8')
        assert 'class="portfolio-tabs"' not in html
        assert 'class="portfolio-tabs__finances"' not in html

    def test_advanced_mode_link_sits_on_the_tab_row(self, authenticated_client, app):
        _make_advanced(app)
        html = authenticated_client.get('/portfolio').data.decode('utf-8')
        row = _tab_row(html)
        assert 'data-tab="longs"' in row and 'data-tab="shorts"' in row
        assert 'class="portfolio-tabs__finances"' in row
        assert 'href="/finances"' in row
        # It's a link, not another tab the tab-switching script would pick up
        assert row.count('<button class="trade-tabs__tab') == 2


    def test_longs_tab_is_active_by_default(self, authenticated_client, app):
        _make_advanced(app)
        html = authenticated_client.get('/portfolio').data.decode('utf-8')
        assert 'id="portfolio-tab-longs" class="portfolio-tab-content portfolio-tab-content--active"' in html
        assert 'id="portfolio-tab-shorts" class="portfolio-tab-content "' in html
        assert 'var _activePortfolioTab = "longs";' in html

    def test_tab_query_opens_shorts_server_side(self, authenticated_client, app):
        _make_advanced(app)
        html = authenticated_client.get('/portfolio?tab=shorts').data.decode('utf-8')
        assert 'id="portfolio-tab-shorts" class="portfolio-tab-content portfolio-tab-content--active"' in html
        assert 'id="portfolio-tab-longs" class="portfolio-tab-content "' in html
        assert 'data-tab="shorts" onclick' in html
        assert 'trade-tabs__tab trade-tabs__tab--active" data-tab="shorts"' in html
        assert 'var _activePortfolioTab = "shorts";' in html

    def test_htmx_refresh_keeps_the_requested_tab(self, authenticated_client, app):
        _make_advanced(app)
        html = authenticated_client.get(
            '/portfolio?tab=shorts', headers={'HX-Request': 'true'}
        ).data.decode('utf-8')
        assert '<!DOCTYPE' not in html  # partial only
        assert 'id="portfolio-tab-shorts" class="portfolio-tab-content portfolio-tab-content--active"' in html

    def test_unknown_tab_falls_back_to_longs(self, authenticated_client, app):
        _make_advanced(app)
        html = authenticated_client.get('/portfolio?tab=bogus').data.decode('utf-8')
        assert 'var _activePortfolioTab = "longs";' in html

    def test_standard_mode_ignores_tab_query(self, authenticated_client):
        html = authenticated_client.get('/portfolio?tab=shorts').data.decode('utf-8')
        assert 'portfolio-tab-shorts' not in html

