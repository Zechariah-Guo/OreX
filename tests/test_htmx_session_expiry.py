"""Tests for unauthenticated requests to protected pages, plain and htmx."""

import pytest

PROTECTED = ['/dashboard', '/portfolio', '/leaderboard', '/market']


@pytest.fixture
def anon(app):
    """A fresh client with no session."""
    return app.test_client()


class TestUnauthenticatedRedirect:

    @pytest.mark.parametrize('path', PROTECTED)
    def test_plain_request_redirects_to_login(self, anon, path):
        resp = anon.get(path)
        assert resp.status_code == 302
        assert '/login' in resp.headers['Location']
        assert 'HX-Redirect' not in resp.headers

    @pytest.mark.parametrize('path', PROTECTED)
    def test_htmx_request_gets_hx_redirect_and_empty_body(self, anon, path):
        resp = anon.get(path, headers={'HX-Request': 'true'})
        assert resp.status_code == 200
        assert '/login' in resp.headers['HX-Redirect']
        assert 'Location' not in resp.headers
        assert resp.data == b''

    def test_htmx_redirect_matches_plain_redirect_target(self, anon):
        plain = anon.get('/dashboard').headers['Location']
        htmx = anon.get('/dashboard', headers={'HX-Request': 'true'}).headers['HX-Redirect']
        assert htmx == plain
