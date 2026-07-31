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
        get_bot_avatar_color, is_bot_username
    )
    app.jinja_env.filters['avatar_color_hex'] = get_avatar_color_hex
    app.jinja_env.filters['avatar_text_color'] = get_avatar_text_color
    app.jinja_env.globals['get_bot_avatar_color'] = get_bot_avatar_color
    app.jinja_env.globals['is_bot_username'] = is_bot_username
    app.jinja_env.globals['get_avatar_color_hex'] = get_avatar_color_hex
    app.jinja_env.globals['get_avatar_text_color'] = get_avatar_text_color

    # Register blueprints
    from app.routes import register_blueprints
    register_blueprints(app)

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
                "SELECT avatar_color FROM users WHERE id = ?",
                (current_user.id,)
            ).fetchone()
            color_key = row['avatar_color'] if row and row['avatar_color'] else None

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
            }
        return {'user_avatar_color_hex': '#4a4a4a', 'user_avatar_text_color': '#ffffff'}

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
            "script-src 'self' 'unsafe-inline' 'unsafe-eval' https://unpkg.com https://cdn.jsdelivr.net; "
            "style-src 'self' 'unsafe-inline'; "
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
