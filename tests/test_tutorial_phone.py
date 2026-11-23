"""Phone support for the tutorial: step data and the phone layout helpers.

Data checks need nothing but the JSON. The layout helpers in tutorial.js are
evaluated through the shared Node runner (skipped when Node.js is missing).
"""

import json
import os

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

TUTORIALS = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'src', 'static', 'data', 'tutorials.json')
ALLOWED_PHONE_KEYS = {'selector', 'title', 'description', 'position', 'reveal'}


def load_tracks():
    with open(TUTORIALS, encoding='utf-8') as f:
        return json.load(f)['tracks']


def test_phone_overrides_are_well_formed():
    """Overrides may only restyle a step; route/action/step count stay shared with desktop."""
    for track in load_tracks():
        for step in track['steps']:
            phone = step.get('phone')
            if phone is None:
                continue
            assert set(phone) <= ALLOWED_PHONE_KEYS, (track['id'], step['title'], set(phone))
            selector = phone.get('selector')
            if isinstance(selector, list):
                assert len(selector) >= 2 and all(isinstance(s, str) and s for s in selector)


def test_nav_steps_have_phone_targets():
    """Steps aimed at desktop-only nav wrappers (display: contents on phones) need a phone selector."""
    wrappers = ('.nav__profile-pill', '.nav__dropdown-icons', '.nav__dropdown-items')
    for track in load_tracks():
        for step in track['steps']:
            if step['selector'] in wrappers:
                assert 'selector' in step.get('phone', {}), (track['id'], step['title'])



# ---------------------------------------------------------------------------
# Layout helpers (Node)
# ---------------------------------------------------------------------------

node = pytest.importorskip('test_tutorial_js_properties')
call_js = node.call_js
pytestmark_node = node.pytestmark

finite = node.finite


@st.composite
def phone_case(draw):
    vw = draw(st.sampled_from([360, 375, 390, 414, 640]))
    vh = draw(st.sampled_from([667, 740, 844, 932]))
    top = draw(st.sampled_from([64, 64, 124]))          # bar, or bar + open avatar menu
    bottom = draw(st.sampled_from([64, 72, 98]))        # bar with and without a safe-area inset
    card = {'width': min(380, vw - 24), 'height': draw(finite(150, vh - top - bottom - 24))}
    hl = {'top': draw(finite(-200, vh + 200)), 'left': 12, 'width': draw(finite(20, vw)),
          'height': draw(finite(20, 1500))}
    position = draw(st.sampled_from(['top', 'bottom', 'left', 'right']))
    return position, hl, card, {'width': vw, 'height': vh}, top, bottom


@pytestmark_node
@settings(max_examples=100, deadline=None)
@given(phone_case())
def test_phone_card_stays_between_the_bars(case):
    position, hl, card, vp, top, bottom = case
    pos = call_js('computePhoneCardPosition', position, hl, card, vp, top, bottom, False)
    assert pos['top'] >= top - 1e-6
    assert pos['top'] + card['height'] <= vp['height'] - bottom + 1e-6
    assert 0 <= pos['left'] and pos['left'] + card['width'] <= vp['width'] + 1e-6


@pytestmark_node
@settings(max_examples=100, deadline=None)
@given(phone_case())
def test_phone_scroll_plan_clears_the_bars_when_it_fits(case):
    position, hl, card, vp, top, bottom = case
    rect = {'top': hl['top'], 'bottom': hl['top'] + hl['height'], 'height': hl['height']}
    plan = call_js('planPhoneLayout', rect, {
        'vh': vp['height'], 'topInset': top, 'bottomInset': bottom,
        'cardHeight': card['height'], 'pref': position, 'fixedTarget': False})
    after_top = rect['top'] - plan['delta']
    after_bottom = rect['bottom'] - plan['delta']
    assert after_top >= top - 1e-6                      # never left under the top bar
    free = vp['height'] - top - bottom - 24 - card['height'] - 12
    if hl['height'] <= free:                            # fits: must also clear the bottom bar
        assert after_bottom <= vp['height'] - bottom + 1e-6


@pytestmark_node
def test_fixed_nav_target_is_never_scrolled():
    rect = {'top': 760, 'bottom': 820, 'height': 60}     # the balance pill in the bottom bar
    plan = call_js('planPhoneLayout', rect, {
        'vh': 844, 'topInset': 64, 'bottomInset': 72, 'cardHeight': 250,
        'pref': 'bottom', 'fixedTarget': True})
    assert plan['delta'] == 0 and plan['zone'] == 'bottom'
