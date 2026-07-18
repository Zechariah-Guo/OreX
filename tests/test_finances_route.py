"""Unit tests for finances route access control.

Covers:
- GET /finances returns 200 for authenticated user with advanced mode active
- GET /finances redirects unauthenticated users to /login (302)
- GET /finances returns 403 for authenticated user without advanced mode
- HTMX request returns partial HTML only (no full page wrapper)
"""

import sqlite3

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


class TestFinancesRouteAccessControl:
    """Tests for finances route authentication and authorization."""

    def test_authenticated_advanced_user_gets_200(self, authenticated_client, app):
        """TC: authenticated user with advanced mode active sees finances page (200).

        Validates: Requirements 1.1, 1.2
        """
        _set_user_state(app, advanced_purchased=1, advanced_active=1)

        response = authenticated_client.get('/finances')
        assert response.status_code == 200

    def test_unauthenticated_user_redirects_to_login(self, client):
        """TC: unauthenticated user is redirected to /login (302).

        Validates: Requirements 1.3
        """
        response = client.get('/finances', follow_redirects=False)
        assert response.status_code == 302
        location = response.headers.get('Location', '')
        assert '/login' in location

    def test_authenticated_user_without_advanced_gets_403(self, authenticated_client, app):
        """TC: authenticated user without advanced mode gets 403 Forbidden.

        Validates: Requirements 1.2
        """
        # User is authenticated but advanced mode is NOT active
        # (default state: advanced_purchased=0, advanced_active=0)
        response = authenticated_client.get('/finances')
        assert response.status_code == 403

    def test_htmx_request_returns_partial_html(self, authenticated_client, app):
        """TC: HTMX request returns partial HTML without full page wrapper.

        Validates: Requirements 6.2
        """
        _set_user_state(app, advanced_purchased=1, advanced_active=1)

        response = authenticated_client.get(
            '/finances', headers={'HX-Request': 'true'}
        )
        assert response.status_code == 200
        html = response.data.decode('utf-8')

        # Partial should NOT contain full document wrapper
        assert '<!DOCTYPE' not in html
        assert '<html' not in html
