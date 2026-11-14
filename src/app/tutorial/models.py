"""Database access functions for tutorial progress (tutorial_progress table)."""

from app.database import get_db

_NOW = "datetime('now', 'localtime')"


def get_tutorial_state(user_id, track_id):
    """Return the tutorial_progress row as a dict, or None if no record exists."""
    db = get_db()
    row = db.execute(
        "SELECT * FROM tutorial_progress WHERE user_id = ? AND track_id = ?",
        (user_id, track_id)
    ).fetchone()
    return dict(row) if row else None


def get_all_tutorial_states(user_id):
    """Return all tutorial_progress rows for a user as a list of dicts."""
    db = get_db()
    rows = db.execute(
        "SELECT * FROM tutorial_progress WHERE user_id = ? ORDER BY id",
        (user_id,)
    ).fetchall()
    return [dict(r) for r in rows]


def create_or_update_tutorial_state(user_id, track_id, status, step_index):
    """Upsert a tutorial_progress record. Returns the row ID."""
    db = get_db()
    db.execute(
        f"""INSERT INTO tutorial_progress (user_id, track_id, status, current_step_index, last_updated)
            VALUES (?, ?, ?, ?, {_NOW})
            ON CONFLICT(user_id, track_id) DO UPDATE SET
                status = excluded.status,
                current_step_index = excluded.current_step_index,
                last_updated = {_NOW}""",
        (user_id, track_id, status, step_index)
    )
    row = db.execute(
        "SELECT id FROM tutorial_progress WHERE user_id = ? AND track_id = ?",
        (user_id, track_id)
    ).fetchone()
    db.commit()
    return row['id']


def _update(user_id, track_id, status, step_index):
    """Update status/step of an existing record. Returns True if a row was changed."""
    db = get_db()
    cur = db.execute(
        f"""UPDATE tutorial_progress
            SET status = ?, current_step_index = ?, last_updated = {_NOW}
            WHERE user_id = ? AND track_id = ?""",
        (status, step_index, user_id, track_id)
    )
    db.commit()
    return cur.rowcount > 0


def advance_step(user_id, track_id, new_index):
    """Update current_step_index for an existing record. Returns True on success."""
    db = get_db()
    cur = db.execute(
        f"""UPDATE tutorial_progress
            SET current_step_index = ?, last_updated = {_NOW}
            WHERE user_id = ? AND track_id = ?""",
        (new_index, user_id, track_id)
    )
    db.commit()
    return cur.rowcount > 0


def complete_tutorial(user_id, track_id):
    """Mark a track completed and reset its step index. Returns True on success."""
    return _update(user_id, track_id, 'completed', 0)


def dismiss_tutorial(user_id, track_id):
    """Mark a track dismissed and reset its step index. Returns True on success."""
    return _update(user_id, track_id, 'dismissed', 0)


def replay_tutorial(user_id, track_id):
    """Restart a track: status='in_progress', step index 0. Returns True on success."""
    return _update(user_id, track_id, 'in_progress', 0)


def delete_tutorial_progress(user_id):
    """Delete all tutorial_progress records for a user. Returns the count deleted."""
    db = get_db()
    cur = db.execute("DELETE FROM tutorial_progress WHERE user_id = ?", (user_id,))
    db.commit()
    return cur.rowcount


def pick_active_state(states, advanced_active=None):
    """From a list of tutorial_progress dicts, return the in-progress one to show, or None.

    If more than one track is in progress (e.g. a paused Beginner tutorial and a
    just-replayed Advanced one), the most recently updated wins.

    When advanced_active is given (True/False), tracks built for the other mode
    are ignored: a paused Beginner tutorial must not prompt "resume?" while
    Advanced Mode is on (its steps can't render there), and vice versa. It
    stays in progress and is resumable from Help once the mode matches.
    """
    from app.tutorial.data import ADVANCED_ONLY_TRACKS
    in_progress = [s for s in states if s['status'] == 'in_progress']
    if advanced_active is not None:
        in_progress = [
            s for s in in_progress
            if (s['track_id'] in ADVANCED_ONLY_TRACKS) == bool(advanced_active)
        ]
    if not in_progress:
        return None
    return max(in_progress, key=lambda s: (s['last_updated'], s['id']))


def should_auto_trigger(user_id, track_id):
    """True if the track should auto-start: no record exists or status is 'not_started'."""
    state = get_tutorial_state(user_id, track_id)
    return state is None or state['status'] == 'not_started'
