# OreX app image: rehearsal of the Oracle VM setup (Ubuntu 24.04 ships Python 3.12).
FROM python:3.12-slim

# uv binary, pinned to the version used to write uv.lock.
COPY --from=ghcr.io/astral-sh/uv:0.13.9 /uv /uvx /bin/

ENV PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_NO_CACHE=1 \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/app/.venv \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

# Install exactly what uv.lock pins: runtime deps + the prod group (gunicorn, oci),
# no dev tools. --locked fails the build if uv.lock is out of date with pyproject.toml.
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --group prod

COPY src ./src

# Admin scripts (reset_password, export_user_data, ...) so they can be run with
# `docker compose exec app python /app/scripts/admin/<script>.py`. Dev tools
# (scripts/dev, Playwright) stay out of the image.
COPY scripts/admin ./scripts/admin

# Non-root user. The data and avatar dirs are created and chowned here so the
# named volumes mounted on them inherit the ownership on first use.
RUN useradd --create-home --uid 1000 orex \
    && mkdir -p /app/src/data /app/src/static/uploads/avatars \
    && chown -R orex:orex /app/src/data /app/src/static/uploads
USER orex

WORKDIR /app/src
EXPOSE 4000

# One worker: each worker would start its own market engine thread.
CMD ["gunicorn", "app:create_app()", "--bind", "0.0.0.0:4000", "--workers", "1", "--timeout", "120"]
