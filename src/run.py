import os

# Debug must be known *before* create_app() runs: start_engine() uses app.debug
# to skip the Werkzeug reloader's parent process. Passing debug=True only to
# app.run() is too late, and the market engine would start in BOTH processes —
# two engines ticking the same DB, one of them frozen on the code from startup.
os.environ.setdefault('FLASK_DEBUG', '1')

from app import create_app  # noqa: E402

app = create_app()

if __name__ == '__main__':
    app.run(debug=True, port=4000)
