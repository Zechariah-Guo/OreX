from flask import Flask
from flask_login import LoginManager, current_user
from flask_wtf.csrf import CSRFProtect


def create_app():
    app = Flask(__name__,
                template_folder='../templates',
                static_folder='../static')

    app.config.from_object('app.config.Config')

    # Initialise extensions
    csrf = CSRFProtect(app)
    login_manager = LoginManager(app)
    login_manager.login_view = 'auth.login'
    login_manager.login_message = 'Please log in to access this page.'
    login_manager.login_message_category = 'error'

    # User loader for Flask-Login
    @login_manager.user_loader
    def load_user(user_id):
        from app.models import get_user_by_id
        return get_user_by_id(user_id)

    # Initialise database
    from app.database import init_db
    init_db(app)

    # Register template filters
    from app.utils.formatting import register_filters
    register_filters(app)

    # Register avatar template filters
    from app.avatar import (
        get_avatar_color_hex, get_avatar_text_color,
        get_bot_avatar_color, get_bot_icon_filename, is_bot_username
    )
    app.jinja_env.filters['avatar_color_hex'] = get_avatar_color_hex
    app.jinja_env.filters['avatar_text_color'] = get_avatar_text_color
    app.jinja_env.globals['get_bot_avatar_color'] = get_bot_avatar_color
    app.jinja_env.globals['is_bot_username'] = is_bot_username
    app.jinja_env.globals['get_avatar_color_hex'] = get_avatar_color_hex
    app.jinja_env.globals['get_avatar_text_color'] = get_avatar_text_color
    app.jinja_env.globals['get_bot_icon_filename'] = get_bot_icon_filename

    # Register blueprints
    from app.routes import register_blueprints
    register_blueprints(app)

    # The demo-short clear is fired by sendBeacon on page unload (tab close /
    # navigate away), which cannot attach the CSRF header. Exempt just this one
    # endpoint: it only ever removes the caller's OWN tutorial demo short and
    # refunds its exact margin (net-zero), so a forged call is harmless and
    # self-healing (resume re-opens the demo short).
    csrf.exempt(app.view_functions['tutorial.demo_short_clear'])

    # Context processor: inject Advanced Mode status into all templates
    @app.context_processor
    def inject_advanced_mode():
        if current_user.is_authenticated:
            from app.advanced import get_advanced_status
            from app.database import get_db
            status = get_advanced_status(current_user.id)
            # Check for active short positions (needed by settings modal)
            db = get_db()
            active_shorts_count = db.execute(
                "SELECT COUNT(*) as cnt FROM short_positions WHERE user_id = ? AND status = 'active'",
                (current_user.id,)
            ).fetchone()['cnt']
            return {
                'is_advanced_active': status['active'],
                'has_advanced_purchased': status['purchased'],
                'advanced_eligible': status['eligible'],
                'advanced_cooldown_remaining': status['cooldown_remaining'],
                'has_active_shorts': active_shorts_count > 0,
            }
        return {
            'is_advanced_active': False,
            'has_advanced_purchased': False,
            'advanced_eligible': False,
            'advanced_cooldown_remaining': 0,
            'has_active_shorts': False,
        }

    # Context processor: inject advancement theme unlock flags into all templates
    @app.context_processor
    def inject_advancement_themes():
        if current_user.is_authenticated:
            from app.database import get_db
            db = get_db()
            row = db.execute(
                "SELECT money_theme_unlocked, gold_theme_unlocked FROM users WHERE id = ?",
                (current_user.id,)
            ).fetchone()
            return {
                'money_theme_unlocked': bool(row['money_theme_unlocked']) if row else False,
                'gold_theme_unlocked': bool(row['gold_theme_unlocked']) if row else False,
            }
        return {'money_theme_unlocked': False, 'gold_theme_unlocked': False}

    # Context processor: inject current user's avatar colour into all templates
    @app.context_processor
    def inject_avatar_color():
        if current_user.is_authenticated:
            from app.database import get_db
            from app.avatar import (
                get_avatar_color_hex, get_avatar_text_color,
                get_random_avatar_color
            )
            db = get_db()
            row = db.execute(
                "SELECT avatar_color, avatar_path FROM users WHERE id = ?",
                (current_user.id,)
            ).fetchone()
            color_key = row['avatar_color'] if row and row['avatar_color'] else None
            avatar_path = row['avatar_path'] if row and row['avatar_path'] else None

            # Lazy assignment: if user has no color yet, assign one now
            if color_key is None:
                color_key = get_random_avatar_color()
                db.execute(
                    "UPDATE users SET avatar_color = ? WHERE id = ?",
                    (color_key, current_user.id)
                )
                db.commit()

            return {
                'user_avatar_color_hex': get_avatar_color_hex(color_key),
                'user_avatar_text_color': get_avatar_text_color(color_key),
                'user_avatar_path': avatar_path,
            }
        return {'user_avatar_color_hex': '#4a4a4a', 'user_avatar_text_color': '#ffffff', 'user_avatar_path': None}

    # Context processor: inject notification unread status into all templates
    @app.context_processor
    def inject_notification_status():
        if current_user.is_authenticated:
            from app.models import has_unread_notifications
            return {'has_unread': has_unread_notifications(current_user.id)}
        return {'has_unread': False}

    # Backstop for the Advanced tutorial's demo short: it must exist only while
    # the tour is live. The client clears it on Finish/Skip and on page unload
    # (sendBeacon), but a hard process crash can leave one dangling. On any normal
    # page load where the Advanced track is NOT in progress, sweep it away. This is
    # the one guarantee that does not rely on the client having run on exit.
    @app.before_request
    def _reconcile_tutorial_demo_short():
        from flask import request
        # Only GET page loads. Skip the tutorial's own API calls (they manage the
        # demo short deliberately) and static assets.
        if request.method != 'GET' or (request.endpoint or '').startswith('tutorial.'):
            return
        if not current_user.is_authenticated:
            return
        try:
            from app.tutorial.demo import has_demo_short, clear_demo_short
            from app.tutorial.models import get_tutorial_state
            if not has_demo_short(current_user.id):
                return
            state = get_tutorial_state(current_user.id, 'advanced')
            # While the Advanced tour is in progress the short is legitimate (the
            # overlay re-opens it on each page). Any other status (completed,
            # dismissed, not_started, or no record) means the tour is not live, so
            # a lingering demo short is a crash remnant: refund its margin and drop it.
            if state is None or state['status'] != 'in_progress':
                clear_demo_short(current_user.id)
        except Exception:
            # Never break a page load over tutorial bookkeeping.
            app.logger.exception('Failed to reconcile tutorial demo short')

    # Context processor: inject tutorial state into all templates
    @app.context_processor
    def inject_tutorial_state():
        empty = {
            'tutorial_active': None,
            'tutorial_auto_track': None,
            'tutorial_should_load_alpine': False,
        }
        if not current_user.is_authenticated:
            return empty
        try:
            from flask import request
            from app.tutorial.data import load_all_tracks
            from app.tutorial.models import (
                get_all_tutorial_states, pick_active_state, should_auto_trigger,
            )
            from app.advanced import get_advanced_status

            # Ignore paused tracks built for the other mode (see pick_active_state)
            active = pick_active_state(
                get_all_tutorial_states(current_user.id),
                get_advanced_status(current_user.id)['active'],
            )

            # The Advanced tour opens a demo short and walks several pages, so it
            # must begin from a clean, known starting point: the dashboard. Advanced
            # Mode is activated on the Settings page, so auto-triggering there would
            # start the tour mid-flow. Only offer it once the player is on (or has
            # returned to) the dashboard.
            on_dashboard = request.endpoint == 'dashboard.overview'

            # Only look for a new auto-trigger when nothing is already running
            auto_track = None
            if active is None:
                advanced_active = None  # looked up lazily, only if needed
                for track in load_all_tracks():
                    if track['trigger'] == 'first_advanced_activation':
                        if not on_dashboard:
                            continue
                        if advanced_active is None:
                            advanced_active = get_advanced_status(current_user.id)['active']
                        if not advanced_active:
                            continue
                    elif track['trigger'] != 'first_login':
                        continue
                    if should_auto_trigger(current_user.id, track['id']):
                        auto_track = track['id']
                        break

            return {
                'tutorial_active': active,
                'tutorial_auto_track': auto_track,
                'tutorial_should_load_alpine': active is not None or auto_track is not None,
            }
        except Exception:
            # Tutorials are non-essential: never break page rendering
            app.logger.exception('Failed to compute tutorial state')
            return empty

    # Register error handlers
    from flask import render_template

    @app.errorhandler(404)
    def page_not_found(e):
        return render_template('pages/404.html'), 404

    @app.errorhandler(500)
    def internal_error(e):
        return render_template('pages/500.html'), 500

    # Security headers (OWASP ZAP fixes)
    @app.after_request
    def set_security_headers(response):
        # Content Security Policy
        response.headers['Content-Security-Policy'] = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline' 'unsafe-eval' https://unpkg.com https://cdn.jsdelivr.net https://cdnjs.cloudflare.com; "
            "style-src 'self' 'unsafe-inline' https://cdnjs.cloudflare.com; "
            "img-src 'self' data:; "
            "font-src 'self'; "
            "connect-src 'self'; "
            "frame-ancestors 'none'"
        )
        # Anti-clickjacking
        response.headers['X-Frame-Options'] = 'DENY'
        # Prevent MIME-type sniffing
        response.headers['X-Content-Type-Options'] = 'nosniff'
        # Hide server version info
        response.headers['Server'] = 'OreX'
        # Referrer policy
        response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
        # Permissions policy
        response.headers['Permissions-Policy'] = 'geolocation=(), camera=(), microphone=()'
        return response

    # Play time heartbeat: track session activity for authenticated users
    @app.before_request
    def _track_play_time():
        if current_user.is_authenticated:
            try:
                from app.playtime import record_heartbeat
                record_heartbeat(current_user.id)
            except Exception:
                pass  # Play time tracking should not interrupt requests

    # Start market engine background thread
    if not app.config.get('TESTING'):
        from app.market.engine import start_engine
        start_engine(app)

    return app
