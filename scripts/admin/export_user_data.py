"""Export everything stored about a player as JSON (for a data access request).

Every table that has a user_id column is found from the schema, so a table added
later is included automatically. Tables that hang off those (for example
stop_loss_take_profit, via holdings) are found through their foreign keys.

Secrets are NOT exported. Columns that hold a hash, secret or key are replaced
by "present" or "absent", session_version likewise, and a push subscription
keeps only the host of its endpoint (no keys).

Usage:
    python scripts/admin/export_user_data.py <username>
    python scripts/admin/export_user_data.py <username> --output export.json

The file holds personal data: send it only to the player who asked, then delete it.
"""

import argparse
import json
import re
import sys
from datetime import datetime
from urllib.parse import urlparse

from _admin_common import create_script_app, find_player

from app.models import get_db

# Column names that are never exported. Anything whose name matches the pattern is
# redacted too, so a secret column added later fails safe.
REDACTED_COLUMNS = {'session_version'}
REDACTED_PATTERN = re.compile(r'hash|secret|password|token|p256dh|^auth$')
# push_subscriptions.endpoint is a capability URL: keep the host only.
ENDPOINT_COLUMN = 'endpoint'


def _tables(db):
    return [r['name'] for r in db.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]


def _columns(db, table):
    return [r['name'] for r in db.execute(f'PRAGMA table_info("{table}")')]


def find_user_tables(db):
    """Return (direct, indirect).

    direct: tables with a user_id column.
    indirect: {table: (fk_column, parent_table, parent_column)} for tables that
    reference a direct table by foreign key but have no user_id of their own.
    """
    direct = [t for t in _tables(db) if t != 'users' and 'user_id' in _columns(db, t)]
    indirect = {}
    for table in _tables(db):
        if table == 'users' or table in direct:
            continue
        for fk in db.execute(f'PRAGMA foreign_key_list("{table}")'):
            if fk['table'] in direct:
                indirect[table] = (fk['from'], fk['table'], fk['to'])
                break
    return direct, indirect


def _present(value):
    return 'present' if value not in (None, '') else 'absent'


def _clean_row(table, row, ore_names):
    out = {}
    for key in row.keys():
        value = row[key]
        if key in REDACTED_COLUMNS or REDACTED_PATTERN.search(key):
            out[key] = _present(value)
        elif table == 'push_subscriptions' and key == ENDPOINT_COLUMN:
            out['endpoint_host'] = urlparse(value or '').hostname
        else:
            out[key] = value
    if 'ore_id' in out and out['ore_id'] in ore_names:
        out['ore_name'] = ore_names[out['ore_id']]
    return out


def build_export(db, user_row):
    """Return the export as a plain dict (JSON-serialisable)."""
    ore_names = {r['id']: r['name'] for r in db.execute("SELECT id, name FROM ores")}
    user_id = user_row['id']
    direct, indirect = find_user_tables(db)

    tables = {}
    for table in direct:
        rows = db.execute(f'SELECT * FROM "{table}" WHERE user_id = ?', (user_id,)).fetchall()
        tables[table] = [_clean_row(table, r, ore_names) for r in rows]
    for table, (column, parent, parent_column) in indirect.items():
        rows = db.execute(
            f'SELECT * FROM "{table}" WHERE "{column}" IN '
            f'(SELECT "{parent_column}" FROM "{parent}" WHERE user_id = ?)',
            (user_id,),
        ).fetchall()
        tables[table] = [_clean_row(table, r, ore_names) for r in rows]

    user = _clean_row('users', user_row, ore_names)
    return {
        'exported_at': datetime.now().isoformat(timespec='seconds'),
        'username': user_row['username'],
        'note': ('Secrets (password hash, 2FA secret, backup code hashes, recovery key hash, '
                 'session version, push keys) are not included; they are listed as present or absent.'),
        'user': user,
        'avatar': {
            'has_uploaded_avatar': bool(user_row['avatar_path']),
            'avatar_path': user_row['avatar_path'],
            'fallback_colour': user_row['avatar_color'],
        },
        'tables': tables,
    }


def export_user_data(username, output=None, app=None):
    app = app or create_script_app()
    with app.app_context():
        db = get_db()
        row = find_player(db, username)
        data = build_export(db, row)
    output = output or f"orex-export-{username}-{datetime.now():%Y%m%d}.json"
    with open(output, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False, default=str)
    counts = ', '.join(f"{t}={len(rows)}" for t, rows in data['tables'].items() if rows) or 'no related rows'
    print(f"Exported data for '{username}' (id={row['id']}) to {output}.")
    print(f"Rows: {counts}")
    print("This file contains personal data. Send it only to the player, then delete it.")
    return data


def main(argv=None, app=None):
    parser = argparse.ArgumentParser(description="Export everything stored about a player as JSON.")
    parser.add_argument('username')
    parser.add_argument('--output', '-o', metavar='FILE',
                        help="output file (default: orex-export-<username>-<date>.json in the current folder)")
    args = parser.parse_args(argv)
    export_user_data(args.username, args.output, app=app)


if __name__ == '__main__':
    main()
