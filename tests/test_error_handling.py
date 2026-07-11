"""Tests for error handling (custom 404 and 500 pages)."""

import pytest

from conftest import register_user

pytestmark = pytest.mark.error_handling


class TestErrorHandling:
    """Tests for custom error pages and error responses."""

    def test_unauthenticated_404_contains_link(self, client):
        """TC: unauthenticated request to non-existent path returns 404 with link to root/dashboard.

        Validates: Requirements 11.1
        """
        response = client.get('/this-does-not-exist-xyz')
        assert response.status_code == 404
        html = response.data.decode('utf-8')
        assert '<a href="/"' in html or '<a href="/dashboard"' in html

    def test_authenticated_404_non_existent_ore(self, authenticated_client):
        """TC: authenticated request to /market/9999 returns 404.

        Validates: Requirements 11.2
        """
        response = authenticated_client.get('/market/9999')
        assert response.status_code == 404

    def test_500_error_user_friendly_message(self, app, client):
        """TC: forced exception in route handler returns 500 with user-friendly message.

        Validates: Requirements 11.3
        """
        # Monkey-patch the landing page view to raise an exception
        original_view = app.view_functions['pages.landing']

        def raise_error():
            raise Exception('Deliberate test exception')

        app.view_functions['pages.landing'] = raise_error

        # Temporarily disable exception propagation so the 500 handler fires
        original_testing = app.config['TESTING']
        original_propagate = app.config.get('PROPAGATE_EXCEPTIONS')
        app.config['TESTING'] = False
        app.config['PROPAGATE_EXCEPTIONS'] = False

        try:
            response = client.get('/')
            assert response.status_code == 500
            html = response.data.decode('utf-8')
            assert 'try again' in html.lower()
        finally:
            # Restore original state
            app.view_functions['pages.landing'] = original_view
            app.config['TESTING'] = original_testing
            if original_propagate is None:
                app.config.pop('PROPAGATE_EXCEPTIONS', None)
            else:
                app.config['PROPAGATE_EXCEPTIONS'] = original_propagate

    def test_authenticated_404_contains_link(self, authenticated_client):
        """TC: authenticated request to non-existent path returns 404 with link to root/dashboard.

        Validates: Requirements 11.4
        """
        response = authenticated_client.get('/this-does-not-exist-xyz')
        assert response.status_code == 404
        html = response.data.decode('utf-8')
        assert '<a href="/"' in html or '<a href="/dashboard"' in html
