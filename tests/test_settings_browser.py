"""Real-browser tests for the Settings page sections (headless Chrome/Edge via Playwright).

A #section in the URL opens that section once and then leaves the address bar
clean; the tutorial's orex:reveal event opens a collapsed section before it
spotlights something inside it.

Skipped when no Chrome/Edge is installed. Deselect with: pytest -m "not browser"
"""

import pytest

from conftest import browser_login

pytestmark = pytest.mark.browser

OPEN = '.settings-section--open'


def _open_ids(page):
    return page.eval_on_selector_all(OPEN, 'els => els.map(e => e.id)')


@pytest.fixture()
def page(browser_context, app, live_server):
    page = browser_context.new_page()
    browser_login(page, live_server, app)
    return page


def test_hash_opens_its_section_once_and_is_cleared(page, live_server):
    page.goto(live_server + '/settings#gameplay')
    page.wait_for_selector('#gameplay' + OPEN)
    assert _open_ids(page) == ['gameplay']
    assert page.evaluate('location.hash') == ''
    assert page.url == live_server + '/settings'

    # A reload starts fresh: nothing open
    page.reload()
    page.wait_for_load_state('load')
    assert _open_ids(page) == []


def test_changing_the_hash_on_the_page_opens_that_section(page, live_server):
    page.goto(live_server + '/settings')
    page.evaluate("location.hash = '#device'")
    page.wait_for_selector('#device' + OPEN)
    assert page.evaluate('location.hash') == ''


def test_reveal_event_opens_the_section_of_its_target(page, live_server):
    page.goto(live_server + '/settings')
    assert _open_ids(page) == []
    page.evaluate("document.querySelector('#appearance h3')"
                  ".dispatchEvent(new CustomEvent('orex:reveal', { bubbles: true }))")
    page.wait_for_selector('#appearance' + OPEN)
    assert _open_ids(page) == ['appearance']


def test_form_redirect_lands_on_and_opens_its_section(page, live_server):
    """A password change redirects to /settings#account, which opens Account."""
    page.goto(live_server + '/settings')
    page.fill('input[name="current_password"]', 'Password123!')
    page.fill('input[name="new_password"]', 'NewPassword456!')
    page.fill('input[name="confirm_password"]', 'NewPassword456!')
    page.click('form[action$="/settings/password"] button[type="submit"]')
    page.wait_for_load_state('load')
    page.wait_for_selector('#account' + OPEN)
    assert page.evaluate('location.hash') == ''
