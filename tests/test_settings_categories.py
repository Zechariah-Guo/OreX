"""Settings page: the category bar, which cards sit in which section, and redirects to a section.

How the sections open (hash, tutorial reveal) is checked in a browser in test_settings_browser.py.
"""

import re

import pytest

pytestmark = pytest.mark.account_settings

CATEGORIES = ['account', 'device', 'appearance', 'gameplay']


@pytest.fixture()
def html(authenticated_client):
    return authenticated_client.get('/settings').data.decode('utf-8')


def _section(html, category):
    start = html.index(f'<section class="settings-section" id="{category}"')
    return html[start:html.index('</section>', start)]


class TestSettingsCategories:

    def test_category_bar_links_to_every_section(self, html):
        bar = re.search(r'<nav class="settings-nav" id="settings-nav" aria-label="Settings sections">(.*?)</nav>',
                        html, re.S)
        assert bar
        assert re.findall(r'<a class="settings-nav__link" href="#([a-z]+)"', bar.group(1)) == CATEGORIES
        assert bar.start() < html.index('id="account"')

    def test_cards_live_in_their_category(self, html):
        account = _section(html, 'account')
        for heading in ('Account Information', 'Change Password', 'Two-Factor Authentication',
                        'Sign out of all other devices', 'Danger Zone'):
            assert heading in account
        device = _section(html, 'device')
        assert 'id="install-card"' in device and 'id="push-card"' in device
        appearance = _section(html, 'appearance')
        assert '<h3>Colour theme</h3>' in appearance and '<h3>Cosmetic Themes</h3>' in appearance
        gameplay = _section(html, 'gameplay')
        assert 'id="advanced-mode-card"' in gameplay and 'id="tutorials-card"' in gameplay

    def test_sign_out_others_card_posts_with_csrf(self, html):
        card = html[html.index('id="sign-out-others-card"'):html.index('Danger Zone')]
        assert 'Signs you out everywhere else, including installed apps. This device stays signed in.' in card
        assert 'action="/settings/sign-out-others"' in card
        assert 'name="csrf_token"' in card

    def test_tutorials_card_links_to_the_help_tutorials_anchor(self, html, client):
        assert re.search(r'<a href="/help#tutorials">', _section(html, 'gameplay'))
        assert 'id="tutorials"' in client.get('/help').data.decode('utf-8')

    def test_notifications_card_scopes_device_and_categories(self, html):
        card = html[html.index('id="push-card"'):html.index('id="appearance"')]
        assert 'for this device only' in card and 'all of your devices' in card

    def test_notifications_card_is_always_present_and_the_section_never_hides(self, html):
        device = _section(html, 'device')
        assert re.search(r'<div class="settings-card push-card" id="push-card"\s+data-configured', device)
        assert 'Notifications are not configured on this server.' in device
        assert 'id="push-controls"' in device and 'id="push-device-switch" disabled' in device
        assert 'settings-nav__item--device' not in html

    def test_redirects_land_on_the_matching_section(self, authenticated_client):
        from conftest import get_csrf_token
        token = get_csrf_token(authenticated_client.get('/settings'))
        resp = authenticated_client.post('/settings/password', data={
            'current_password': 'Password123!', 'new_password': 'NewPassword456!',
            'confirm_password': 'NewPassword456!', 'csrf_token': token})
        assert resp.headers['Location'].endswith('/settings#account')
        token = get_csrf_token(authenticated_client.get('/settings'))
        resp = authenticated_client.post('/settings/advanced/toggle', data={'csrf_token': token})
        assert resp.headers['Location'].endswith('/settings#gameplay')
