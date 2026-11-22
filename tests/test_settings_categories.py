"""Settings page layout: four categories in order, a category bar, danger zone last in Account."""

import os
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

    def test_four_sections_in_order_with_h2_headings(self, html):
        ids = re.findall(r'<section class="settings-section" id="([a-z]+)"', html)
        assert ids == CATEGORIES
        titles = re.findall(r'<h2 class="settings-section__title"[^>]*>([^<]+)</h2>', html)
        assert titles == ['Account', 'This device', 'Appearance', 'Gameplay']

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

    def test_account_card_order_with_danger_zone_last(self, html):
        account = _section(html, 'account')
        order = ['Account Information', 'Change Password', 'Two-Factor Authentication',
                 'Sign out of all other devices', 'Danger Zone', 'Reset Account', 'Delete Account']
        positions = [account.index(f'>{name}<') for name in order]
        assert positions == sorted(positions)
        assert account.rindex('settings-card') > account.index('settings-divider')
        assert 'settings-divider' not in html.replace(account, '')

    def test_sign_out_others_card_posts_with_csrf(self, html):
        card = html[html.index('id="sign-out-others-card"'):html.index('Danger Zone')]
        assert 'Signs you out everywhere else, including installed apps. This device stays signed in.' in card
        assert 'action="/settings/sign-out-others"' in card
        assert 'name="csrf_token"' in card
        assert 'btn btn--secondary' in card

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

    def test_sections_render_collapsible_markup_collapsed(self, html):
        summaries = {'account': 'Password, two-factor, sign out, danger zone',
                     'device': 'Install, notifications',
                     'appearance': 'Colour theme, cosmetic themes',
                     'gameplay': 'Advanced Mode, tutorials'}
        for category in CATEGORIES:
            section = _section(html, category)
            assert (f'<button type="button" class="settings-section__toggle" aria-expanded="false" '
                    f'aria-controls="{category}-body" aria-labelledby="{category}-heading">') in section
            assert f'<div class="settings-section__body" id="{category}-body">' in section
            assert f'<p class="settings-section__summary">{summaries[category]}</p>' in section
            # The body wraps the cards: it opens after the header and holds the rest of the section
            assert section.index('settings-section__toggle') < section.index(f'id="{category}-body"')
        # Server markup never opens a section; the hash and form errors open them on load
        assert 'class="settings-section settings-section--open' not in html
        assert 'aria-expanded="true"' not in html.split('class="settings-content"')[1].split('<script>')[0]

    def test_hash_and_tutorial_hooks_open_sections(self, html):
        assert "location.hash" in html and "settings-section--open" in html
        assert "addEventListener('hashchange'" in html
        assert "addEventListener('orex:reveal'" in html
        with open(os.path.join(os.path.dirname(__file__), '..', 'src', 'static', 'js', 'tutorial.js'),
                  encoding='utf-8') as f:
            source = f.read()
        assert "new CustomEvent('orex:reveal', { bubbles: true })" in source
        assert 'revealTarget(step.selector);' in source

    def test_hash_is_cleared_after_landing_and_never_written(self, html):
        assert "history.replaceState(history.state, '', location.pathname + location.search)" in html
        assert "history.scrollRestoration = 'manual'" in html
        # nothing on the page writes a hash into the address bar
        assert not re.search(r"replaceState\([^)]*'#'", html)
        assert "'#' + target.id" not in html

    def test_no_chips_layout_and_desktop_layout_above_the_phone_breakpoint(self, html):
        css_path = os.path.join(os.path.dirname(__file__), '..', 'src', 'static', 'css', 'global.css')
        with open(css_path, encoding='utf-8') as f:
            css = f.read()
        start = css.index('/* ===== Settings Page ===== */')
        settings_css = css[start:start + 9000]
        assert 'chip' not in settings_css.lower() and 'chip' not in html.lower()
        assert 'max-width: 720px' not in settings_css and 'min-width: 721px' not in settings_css
        assert 'matchMedia(\'(max-width: 720px)\')' not in html
        assert '@media (max-width: 640px)' in settings_css
        assert re.search(r'\.settings-layout \{\s+display: grid;', settings_css)

    def test_accordion_heads_are_cards_with_an_animated_attached_panel(self, html):
        for category in CATEGORIES:
            assert 'class="settings-section__panel"' in _section(html, category)
        assert 'settings-section--instant' in html

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
