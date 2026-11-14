# OreX app image: rehearsal of the Oracle VM setup (Ubuntu 24.04 ships Python 3.12).
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Same installs as the plan: requirements.txt + gunicorn (pinned as in
# docs/planning/deployment/requirements-prod.txt).
COPY requirements.txt ./requirements.txt
RUN pip install -r requirements.txt \
    && pip install gunicorn==23.0.0 oci==2.191.0

COPY src ./src

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
