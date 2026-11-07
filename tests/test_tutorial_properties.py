"""Property-based tests for the Tutorial System data layer and view logic.

Covers the tutorial data loader, the tutorial_progress model functions, account
lifecycle cleanup, and the Help page track list. Model tests run against an
in-memory SQLite DB built from the canonical src/schema.sql, with ``get_db``
patched to return that connection.

Properties of the browser-side logic (card position, button state, route
comparison, highlight geometry) live in test_tutorial_js_properties.py.
"""

import json
import os
import sqlite3
import string
import sys
from unittest.mock import MagicMock, patch

# Add src/ to the Python path so that `from app.tutorial import ...` works
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'src'))

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from app.tutorial import data as tutorial_data
from app.tutorial import models as tm

SCHEMA_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'src', 'schema.sql'
)

STATUSES = ['not_started', 'in_progress', 'completed', 'dismissed']
TRACK_IDS = ['beginner', 'advanced']
POSITIONS = ['top', 'bottom', 'left', 'right', 'center']


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_db(user_ids=()):
    """Create an in-memory DB from schema.sql with the given user IDs inserted."""
    conn = sqlite3.connect(':memory:')
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA foreign_keys = ON')
    with open(SCHEMA_PATH, 'r') as f:
        conn.executescript(f.read())
    for uid in user_ids:
        conn.execute(
            'INSERT INTO users (id, username, password_hash) VALUES (?, ?, ?)',
            (uid, f'user{uid}', 'hash'),
        )
    conn.commit()
    return conn


def _count(conn, user_id, track_id):
    return conn.execute(
        'SELECT COUNT(*) FROM tutorial_progress WHERE user_id = ? AND track_id = ?',
        (user_id, track_id),
    ).fetchone()[0]


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

text_field = st.text(min_size=1, max_size=60)

step_strategy = st.fixed_dictionaries({
    'selector': text_field,
    'route': st.sampled_from(['/dashboard', '/market', '/portfolio', '/leaderboard']),
    'title': text_field,
    'description': text_field,
    'position': st.sampled_from(POSITIONS),
    'action': st.one_of(st.none(), text_field),
})


@st.composite
def track_strategy(draw):
    steps = draw(st.lists(step_strategy, min_size=1, max_size=10))
    for i, step in enumerate(steps):
        step['index'] = i
    return {
        'id': draw(st.sampled_from(TRACK_IDS)),
        'name': draw(text_field),
        'trigger': draw(st.sampled_from(['first_login', 'first_advanced_activation'])),
        'steps': steps,
    }


# ---------------------------------------------------------------------------
# Data loader (task 2.1) - example-based sanity checks on the real JSON file
# ---------------------------------------------------------------------------

def test_loader_reads_both_tracks():
    ids = [t['id'] for t in tutorial_data.load_all_tracks()]
    assert ids == ['beginner', 'advanced']
    assert tutorial_data.load_track('nope') is None
    n = tutorial_data.get_track_length('beginner')
    assert n > 0
    assert tutorial_data.get_step('beginner', 0)['index'] == 0
    assert tutorial_data.get_step('beginner', n) is None
    assert tutorial_data.get_step('beginner', -1) is None
    assert tutorial_data.get_track_length('nope') == 0


def test_loader_steps_have_required_fields():
    for meta in tutorial_data.load_all_tracks():
        track = tutorial_data.load_track(meta['id'])
        for i, step in enumerate(track['steps']):
            assert step['index'] == i
            assert step['position'] in POSITIONS
            for key in ('selector', 'route', 'title', 'description', 'action'):
                assert key in step


# ---------------------------------------------------------------------------
# Property 1: Tutorial Data Serialization Round-Trip
# ---------------------------------------------------------------------------

# Feature: tutorial-system, Property 1: serializing a track to JSON and back preserves it
# Validates: Requirements 1.1, 1.2
@settings(max_examples=100)
@given(track=track_strategy())
def test_property_1_serialization_round_trip(track):
    assert json.loads(json.dumps(track)) == track
    assert json.loads(json.dumps({'tracks': [track]}))['tracks'][0] == track


# ---------------------------------------------------------------------------
# Property 2: Auto-Trigger Correctness
# ---------------------------------------------------------------------------

# Feature: tutorial-system, Property 2: auto-trigger iff no record or status not_started
# Validates: Requirements 2.1, 2.2, 2.3, 2.4
@settings(max_examples=100)
@given(status=st.sampled_from([None] + STATUSES), track_id=st.sampled_from(TRACK_IDS))
def test_property_2_auto_trigger(status, track_id):
    conn = _make_db([1])
    with patch.object(tm, 'get_db', return_value=conn):
        if status is not None:
            tm.create_or_update_tutorial_state(1, track_id, status, 0)
        expected = status is None or status == 'not_started'
        assert tm.should_auto_trigger(1, track_id) is expected
    conn.close()


# ---------------------------------------------------------------------------
# Property 7: Tutorial State Persistence Round-Trip
# ---------------------------------------------------------------------------

# Feature: tutorial-system, Property 7: written state reads back identically
# Validates: Requirements 5.2, 6.1, 6.2
@settings(max_examples=100)
@given(
    user_id=st.integers(1, 1000),
    track_id=st.sampled_from(TRACK_IDS),
    status=st.sampled_from(STATUSES),
    step_index=st.integers(0, 20),
)
def test_property_7_state_round_trip(user_id, track_id, status, step_index):
    conn = _make_db([user_id])
    with patch.object(tm, 'get_db', return_value=conn):
        tm.create_or_update_tutorial_state(user_id, track_id, status, step_index)
        state = tm.get_tutorial_state(user_id, track_id)
        assert state['track_id'] == track_id
        assert state['status'] == status
        assert state['current_step_index'] == step_index
        assert [s['track_id'] for s in tm.get_all_tutorial_states(user_id)] == [track_id]
    conn.close()


# ---------------------------------------------------------------------------
# Property 12: UNIQUE Constraint on User-Track Pair
# ---------------------------------------------------------------------------

# Feature: tutorial-system, Property 12: duplicate (user_id, track_id) insert raises IntegrityError
# Validates: Requirements 11.2
@settings(max_examples=100)
@given(user_id=st.integers(1, 100), track_id=st.sampled_from(TRACK_IDS))
def test_property_12_unique_user_track(user_id, track_id):
    conn = _make_db([user_id])
    insert = 'INSERT INTO tutorial_progress (user_id, track_id) VALUES (?, ?)'
    conn.execute(insert, (user_id, track_id))
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(insert, (user_id, track_id))
    assert _count(conn, user_id, track_id) == 1
    conn.close()


# ---------------------------------------------------------------------------
# Property 14: Tutorial State Upsert Behavior
# ---------------------------------------------------------------------------

# Feature: tutorial-system, Property 14: upsert creates when absent, updates (no duplicate) when present
# Validates: Requirements 11.5
@settings(max_examples=100)
@given(
    user_id=st.integers(1, 100),
    track_id=st.sampled_from(TRACK_IDS),
    record_exists=st.booleans(),
    status=st.sampled_from(STATUSES),
    step_index=st.integers(0, 20),
)
def test_property_14_upsert(user_id, track_id, record_exists, status, step_index):
    conn = _make_db([user_id])
    with patch.object(tm, 'get_db', return_value=conn):
        first_id = None
        if record_exists:
            first_id = tm.create_or_update_tutorial_state(user_id, track_id, 'in_progress', 3)
            assert _count(conn, user_id, track_id) == 1
        else:
            assert _count(conn, user_id, track_id) == 0

        row_id = tm.create_or_update_tutorial_state(user_id, track_id, status, step_index)

        assert _count(conn, user_id, track_id) == 1
        if record_exists:
            assert row_id == first_id
        state = tm.get_tutorial_state(user_id, track_id)
        assert state['status'] == status
        assert state['current_step_index'] == step_index
    conn.close()


# ---------------------------------------------------------------------------
# Property 10: Replay Resets Tutorial State to Beginning
# ---------------------------------------------------------------------------

# Feature: tutorial-system, Property 10: replay sets in_progress / step 0; complete & dismiss reset step to 0
# Validates: Requirements 7.3, 11.6
@settings(max_examples=100)
@given(
    track_id=st.sampled_from(TRACK_IDS),
    status=st.sampled_from(['completed', 'dismissed']),
    step_index=st.integers(0, 20),
)
def test_property_10_replay_resets_state(track_id, status, step_index):
    conn = _make_db([1])
    with patch.object(tm, 'get_db', return_value=conn):
        tm.create_or_update_tutorial_state(1, track_id, status, step_index)
        assert tm.replay_tutorial(1, track_id) is True
        state = tm.get_tutorial_state(1, track_id)
        assert state['status'] == 'in_progress'
        assert state['current_step_index'] == 0

        # Reaching completed/dismissed also resets the step index
        tm.advance_step(1, track_id, step_index)
        finish = tm.complete_tutorial if status == 'completed' else tm.dismiss_tutorial
        assert finish(1, track_id) is True
        state = tm.get_tutorial_state(1, track_id)
        assert state['status'] == status
        assert state['current_step_index'] == 0
    conn.close()


# ---------------------------------------------------------------------------
# Remaining model functions (no dedicated property): example-based checks
# ---------------------------------------------------------------------------

def test_missing_record_behaviour():
    conn = _make_db([1])
    with patch.object(tm, 'get_db', return_value=conn):
        assert tm.get_tutorial_state(1, 'beginner') is None
        assert tm.get_all_tutorial_states(1) == []
        assert tm.advance_step(1, 'beginner', 2) is False
        assert tm.complete_tutorial(1, 'beginner') is False
        assert tm.delete_tutorial_progress(1) == 0
    conn.close()


def test_advance_and_delete():
    conn = _make_db([1, 2])
    with patch.object(tm, 'get_db', return_value=conn):
        tm.create_or_update_tutorial_state(1, 'beginner', 'in_progress', 0)
        tm.create_or_update_tutorial_state(1, 'advanced', 'in_progress', 0)
        tm.create_or_update_tutorial_state(2, 'beginner', 'in_progress', 0)
        assert tm.advance_step(1, 'beginner', 4) is True
        assert tm.get_tutorial_state(1, 'beginner')['current_step_index'] == 4
        assert tm.delete_tutorial_progress(1) == 2
        assert tm.get_all_tutorial_states(1) == []
        assert len(tm.get_all_tutorial_states(2)) == 1
    conn.close()


# ---------------------------------------------------------------------------
# Property 8: Resume Prompt Triggers Only for In-Progress State
# ---------------------------------------------------------------------------

TIMESTAMPS = ['2026-01-01 10:00:00', '2026-01-01 10:00:01', '2026-06-01 09:30:00']


@st.composite
def progress_rows(draw):
    """A player's tutorial_progress rows with arbitrary statuses and timestamps."""
    statuses = draw(st.lists(st.sampled_from(STATUSES), max_size=6))
    return [
        {'id': i + 1, 'track_id': f'track{i}', 'status': status,
         'current_step_index': draw(st.integers(0, 10)),
         'last_updated': draw(st.sampled_from(TIMESTAMPS))}
        for i, status in enumerate(statuses)
    ]


# Feature: tutorial-system, Property 8: a resume prompt is offered iff some track is in_progress
# Validates: Requirements 5.4, 6.5, 6.6
@settings(max_examples=100)
@given(rows=progress_rows())
def test_property_8_resume_only_for_in_progress(rows):
    active = tm.pick_active_state(rows)
    in_progress = [r for r in rows if r['status'] == 'in_progress']
    if not in_progress:
        assert active is None
    else:
        assert active in in_progress
        # With several paused tracks the most recently updated one is offered
        assert (active['last_updated'], active['id']) == max(
            (r['last_updated'], r['id']) for r in in_progress)


# ---------------------------------------------------------------------------
# Property 13: Account Lifecycle Clears All Tutorial Records
# ---------------------------------------------------------------------------

track_ids = st.lists(st.text(alphabet=string.ascii_lowercase, min_size=1, max_size=8),
                     unique=True, max_size=5)


def _seed_progress(conn, user_id, tracks):
    for track_id in tracks:
        conn.execute(
            "INSERT INTO tutorial_progress (user_id, track_id, status) VALUES (?, ?, 'completed')",
            (user_id, track_id))
    conn.commit()


def _progress_count(conn, user_id):
    return conn.execute(
        'SELECT COUNT(*) FROM tutorial_progress WHERE user_id = ?', (user_id,)).fetchone()[0]


# Feature: tutorial-system, Property 13: after account reset, zero tutorial records remain for that player
# Validates: Requirements 11.3
@settings(max_examples=100)
@given(mine=track_ids, theirs=track_ids)
def test_property_13_reset_clears_tutorial_records(mine, theirs):
    from app.models import reset_account
    conn = _make_db([1, 2])
    _seed_progress(conn, 1, mine)
    _seed_progress(conn, 2, theirs)
    mock_app = MagicMock()
    mock_app.config = {'DEFAULT_BALANCE': 10000}
    with patch('app.models.get_db', return_value=conn), patch('app.models.current_app', mock_app):
        reset_account(1)
    assert _progress_count(conn, 1) == 0
    assert _progress_count(conn, 2) == len(theirs)   # other players are untouched
    conn.close()


# Feature: tutorial-system, Property 13: after account deletion, zero tutorial records remain for that player
# Validates: Requirements 11.4
@settings(max_examples=100)
@given(mine=track_ids, theirs=track_ids)
def test_property_13_delete_clears_tutorial_records(mine, theirs):
    from app.models import delete_account
    conn = _make_db([1, 2])
    _seed_progress(conn, 1, mine)
    _seed_progress(conn, 2, theirs)
    with patch('app.models.get_db', return_value=conn), patch('app.models.current_app', MagicMock()):
        delete_account(1)
    assert _progress_count(conn, 1) == 0             # removed by ON DELETE CASCADE
    assert _progress_count(conn, 2) == len(theirs)
    conn.close()


# ---------------------------------------------------------------------------
# Property 9: Help Page Track Visibility Rules
# ---------------------------------------------------------------------------

# Feature: tutorial-system, Property 9: Beginner always listed; Advanced iff purchased;
#   Replay iff completed/dismissed, Resume iff in_progress (so an in-progress track is
#   always reachable even after the resume toast is gone), no button iff not_started
# Validates: Requirements 7.1, 7.2, 7.4, 7.5, 7.6
@settings(max_examples=150)
@given(
    advanced_purchased=st.booleans(),
    advanced_active=st.booleans(),
    beginner_status=st.sampled_from([None] + STATUSES),
    advanced_status=st.sampled_from([None] + STATUSES),
)
def test_property_9_help_page_track_list(advanced_purchased, advanced_active,
                                         beginner_status, advanced_status):
    from app.tutorial.view import build_tutorial_list
    tracks = tutorial_data.load_all_tracks()
    states = [
        {'track_id': track_id, 'status': status}
        for track_id, status in (('beginner', beginner_status), ('advanced', advanced_status))
        if status is not None
    ]
    rows = {row['id']: row
            for row in build_tutorial_list(tracks, states, advanced_purchased, advanced_active)}

    assert 'beginner' in rows
    assert ('advanced' in rows) is advanced_purchased
    for track_id, status in (('beginner', beginner_status), ('advanced', advanced_status)):
        if track_id in rows:
            row = rows[track_id]
            shown = status or 'not_started'
            assert row['status'] == shown
            # In progress -> Resume + Replay; finished -> Replay; not started -> none.
            labels = [a['label'] for a in row['actions']]
            if shown == 'in_progress':
                assert labels == ['Resume', 'Replay']
                by_label = {a['label']: a for a in row['actions']}
                assert by_label['Resume']['restart'] is False
                assert by_label['Replay']['restart'] is True
            elif shown in ('completed', 'dismissed'):
                assert labels == ['Replay']
                assert row['actions'][0]['restart'] is True
            else:  # not_started
                assert labels == []
            assert row['can_replay'] is bool(labels)

            # Each track is gated to the mode its steps are built for: the
            # Advanced track needs Advanced Mode ON, the Beginner track needs it OFF.
            if track_id == 'advanced':
                assert row['disabled'] is (not advanced_active)
            else:
                assert row['disabled'] is advanced_active
            assert (row['disabled_reason'] is not None) is row['disabled']
