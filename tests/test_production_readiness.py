"""Tests for production-readiness behaviour of create_app().

Covers: dev /advancements page gating, SECRET_KEY refusal in production,
SESSION_COOKIE_SECURE env control and the OREX_TRUST_PROXY (ProxyFix) toggle.
Each test builds its own app on a temporary DB; the market engine is stubbed.
"""

import pytest
from flask import request

from app import create_app
from app.config import DEFAULT_SECRET_KEY

PRIVATE_KEY = 'a-private-test-secret'


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    """Start every test from a known env (not debug, no overrides) with no engine thread."""
    for name in ('FLASK_DEBUG', 'SECRET_KEY', 'SESSION_COOKIE_SECURE',
                 'OREX_TRUST_PROXY', 'OREX_ALLOW_DEFAULT_SECRET'):
        monkeypatch.delenv(name, raising=False)
    import app.market.engine as engine
    monkeypatch.setattr(engine, 'start_engine', lambda app: None)


def make_app(tmp_path, **config):
    cfg = {'DATABASE_PATH': str(tmp_path / 'orex.db'), 'SECRET_KEY': PRIVATE_KEY}
    cfg.update(config)
    return create_app(cfg)


# --- dev page gating ---------------------------------------------------------

def _dev_rules(app):
    return [r for r in app.url_map.iter_rules() if r.endpoint.startswith('advancements.')]


def _concrete_url(rule):
    return rule.rule.replace('<key>', 'millionaire')


def test_dev_routes_404_outside_debug(tmp_path):
    app = make_app(tmp_path, TESTING=True, WTF_CSRF_ENABLED=False)
    assert not app.debug
    rules = _dev_rules(app)
    assert len(rules) >= 14   # page plus 13 POST tools; guards against the loop being vacuous
    client = app.test_client()
    for rule in rules:
        for method in rule.methods - {'HEAD', 'OPTIONS'}:
            resp = client.open(_concrete_url(rule), method=method)
            assert resp.status_code == 404, f'{method} {rule.rule} -> {resp.status_code}'


def test_dev_routes_available_in_debug(tmp_path):
    app = make_app(tmp_path, TESTING=True, DEBUG=True)
    assert app.debug
    resp = app.test_client().get('/advancements')
    assert resp.status_code == 302   # reaches login_required instead of 404
    assert '/login' in resp.headers['Location']


def test_real_advancements_module_unaffected():
    from app.advancements import ADVANCEMENT_KEYS, award_advancement
    assert ADVANCEMENT_KEYS and callable(award_advancement)


# --- SECRET_KEY --------------------------------------------------------------

def test_production_refuses_default_secret(tmp_path):
    with pytest.raises(RuntimeError, match='SECRET_KEY'):
        create_app({'DATABASE_PATH': str(tmp_path / 'orex.db'), 'SECRET_KEY': DEFAULT_SECRET_KEY})


def test_production_refuses_missing_secret(tmp_path):
    with pytest.raises(RuntimeError, match='SECRET_KEY'):
        create_app({'DATABASE_PATH': str(tmp_path / 'orex.db'), 'SECRET_KEY': ''})


def test_production_accepts_private_secret(tmp_path):
    app = make_app(tmp_path)
    assert app.config['SECRET_KEY'] == PRIVATE_KEY


def test_debug_and_testing_allow_default_secret(tmp_path):
    make_app(tmp_path, SECRET_KEY=DEFAULT_SECRET_KEY, DEBUG=True)
    make_app(tmp_path, SECRET_KEY=DEFAULT_SECRET_KEY, TESTING=True)


def test_flask_debug_env_allows_default_secret(tmp_path, monkeypatch):
    monkeypatch.setenv('FLASK_DEBUG', '1')
    app = make_app(tmp_path, SECRET_KEY=DEFAULT_SECRET_KEY)
    assert app.debug


def test_explicit_opt_out_allows_default_secret(tmp_path, monkeypatch):
    monkeypatch.setenv('OREX_ALLOW_DEFAULT_SECRET', '1')
    make_app(tmp_path, SECRET_KEY=DEFAULT_SECRET_KEY)


# --- SESSION_COOKIE_SECURE ---------------------------------------------------

def test_cookie_secure_defaults_on_in_production(tmp_path):
    assert make_app(tmp_path).config['SESSION_COOKIE_SECURE'] is True


@pytest.mark.parametrize('config', [{'TESTING': True}, {'DEBUG': True}])
def test_cookie_secure_defaults_off_for_dev_and_tests(tmp_path, config):
    assert make_app(tmp_path, **config).config['SESSION_COOKIE_SECURE'] is False


@pytest.mark.parametrize('value, expected', [('0', False), ('false', False), ('1', True), ('true', True)])
def test_cookie_secure_env_overrides(tmp_path, monkeypatch, value, expected):
    monkeypatch.setenv('SESSION_COOKIE_SECURE', value)
    assert make_app(tmp_path).config['SESSION_COOKIE_SECURE'] is expected
    assert make_app(tmp_path, TESTING=True).config['SESSION_COOKIE_SECURE'] is expected


# --- ProxyFix ----------------------------------------------------------------

def _probe_app(tmp_path):
    app = make_app(tmp_path, TESTING=True)
    app.add_url_rule('/_probe', 'probe', lambda: f'{request.remote_addr}|{request.scheme}')
    return app


FORWARDED = {'X-Forwarded-For': '203.0.113.9', 'X-Forwarded-Proto': 'https'}


def test_proxyfix_off_by_default(tmp_path):
    body = _probe_app(tmp_path).test_client().get('/_probe', headers=FORWARDED).get_data(as_text=True)
    assert body == '127.0.0.1|http'


def test_proxyfix_on_with_env(tmp_path, monkeypatch):
    monkeypatch.setenv('OREX_TRUST_PROXY', '1')
    body = _probe_app(tmp_path).test_client().get('/_probe', headers=FORWARDED).get_data(as_text=True)
    assert body == '203.0.113.9|https'


def test_proxyfix_trusts_only_one_hop(tmp_path, monkeypatch):
    monkeypatch.setenv('OREX_TRUST_PROXY', '1')
    headers = {'X-Forwarded-For': '198.51.100.7, 203.0.113.9'}   # client-supplied entry, then proxy-added
    body = _probe_app(tmp_path).test_client().get('/_probe', headers=headers).get_data(as_text=True)
    assert body.split('|')[0] == '203.0.113.9'
