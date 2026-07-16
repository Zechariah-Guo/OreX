import os


class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY', 'orex-local-dev-secret-change-in-production')
    DATABASE_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data', 'orex.db')
    DEFAULT_BALANCE = 10000
    TICK_INTERVAL = 20          # seconds
    MAX_BUY_QUANTITY = 500      # hard cap on single buy order in simple mode (no Advanced Mode)
    RATE_LIMIT_WINDOW = 900     # 15 minutes in seconds
    RATE_LIMIT_MAX = 5          # attempts per window
    SESSION_COOKIE_SAMESITE = 'Lax'
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SECURE = False   # Set True in production with HTTPS
