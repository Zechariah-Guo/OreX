"""Tests for the navbar markup: tab order, menu icons, auth class, viewport meta."""

import re


def _tab_links(html):
    return re.findall(r'<a [^>]*class="nav__tab-link[^"]*"[^>]*>.*?</a>', html, re.S)


def _tab_names(html):
    return [re.search(r'aria-label="([^"]+)"', t).group(1) for t in _tab_links(html)]


class TestNavMarkup:
    def test_tab_order(self, authenticated_client):
        html = authenticated_client.get('/dashboard').data.decode('utf-8')
        assert _tab_names(html) == ['Dashboard', 'Market', 'Portfolio']

    def test_leaderboard_is_first_menu_icon_not_a_tab(self, authenticated_client):
        html = authenticated_client.get('/dashboard').data.decode('utf-8')
        assert not any('Leaderboard' in t for t in _tab_links(html))
        icons = re.findall(r'<a [^>]*class="nav__dropdown-icon[^"]*"[^>]*>', html)
        assert 'aria-label="Leaderboard"' in icons[0]
        assert 'href="/leaderboard"' in icons[0]

    def test_inbox_icon_kept(self, authenticated_client):
        html = authenticated_client.get('/dashboard').data.decode('utf-8')
        assert 'title="Inbox"' in html

    def test_menu_sits_in_clip_wrapper_after_pill(self, authenticated_client):
        html = authenticated_client.get('/dashboard').data.decode('utf-8')
        pill = html.index('class="nav__profile-pill"')
        clip = html.index('class="nav__dropdown-clip"')
        menu = html.index('id="nav-dropdown"')
        assert pill < clip < menu
        assert html.count('class="nav__dropdown-clip"') == 1

    def test_portfolio_tab_active(self, authenticated_client):
        html = authenticated_client.get('/portfolio').data.decode('utf-8')
        active = [t for t in _tab_links(html) if 'nav__tab-link--active' in t]
        assert len(active) == 1 and 'aria-label="Portfolio"' in active[0]

    def test_leaderboard_has_no_active_tab(self, authenticated_client):
        html = authenticated_client.get('/leaderboard').data.decode('utf-8')
        assert not any('nav__tab-link--active' in t for t in _tab_links(html))

    def test_auth_class_and_viewport(self, authenticated_client):
        html = authenticated_client.get('/dashboard').data.decode('utf-8')
        assert '<nav class="main-nav main-nav--auth"' in html
        assert 'viewport-fit=cover' in html

    def test_logged_out_has_no_auth_class(self, client):
        html = client.get('/login').data.decode('utf-8')
        assert 'class="main-nav"' in html
        assert 'main-nav--auth' not in html
