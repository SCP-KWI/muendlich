FROM python:3.12-slim

WORKDIR /app

# Unprivileged runtime user. Created early so the COPYs below can chown
# directly; the app itself must never run as root.
RUN useradd --create-home --uid 10001 --shell /usr/sbin/nologin app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

# Reproducible dependency install from the hash-pinned lockfile. Regenerate with:
#   uv pip compile pyproject.toml --generate-hashes -o requirements.lock
COPY requirements.lock ./
RUN pip install --no-cache-dir --require-hashes -r requirements.lock

# Install the package itself without re-resolving dependencies — the lockfile is
# authoritative. app/ must be present because the build reads package sources.
COPY pyproject.toml ./
COPY app ./app
RUN pip install --no-cache-dir --no-deps .

# Anonymizer: German spaCy NER model, pinned by URL so the build is repeatable
# (`python -m spacy download` resolves to "latest"). Runs before the USER switch
# because it installs into site-packages.
ARG SPACY_MODEL_URL=https://github.com/explosion/spacy-models/releases/download/de_core_news_md-3.8.0/de_core_news_md-3.8.0-py3-none-any.whl
RUN pip install --no-cache-dir "${SPACY_MODEL_URL}"

COPY --chown=app:app alembic ./alembic
COPY --chown=app:app alembic.ini ./alembic.ini

USER app

EXPOSE 8000

# Migrations are a separate, explicit deployment step — see the `migrate` service
# in deploy/docker-compose.yml. Running them here would race across replicas and
# turn a failed migration into a crash loop.
#
# --forwarded-allow-ips: nginx is the only client (private network, no published
# port in the production compose file), so its X-Forwarded-For can be trusted.
# This is what lets the per-IP login throttle see real client addresses.
CMD ["uvicorn", "app.main:app", \
     "--host", "0.0.0.0", "--port", "8000", \
     "--proxy-headers", "--forwarded-allow-ips", "*"]
