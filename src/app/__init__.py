from flask import Flask
from flask_login import LoginManager
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

    # Register blueprints
    from app.routes import register_blueprints
    register_blueprints(app)

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

    # Start market engine background thread
    if not app.config.get('TESTING'):
        from app.market.engine import start_engine
        start_engine(app)

    return app
