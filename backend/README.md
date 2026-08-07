# muendlich — backend

FastAPI backend. Runs with **no cloud and no API key** (uses a stub structurer).
See `../TECHNICAL_DESIGN.md` for the full design.

## Run locally (sqlite, zero infra)

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

# create the sqlite schema from the migrations
alembic upgrade head

# seed a dev admin + demo class/students (refuses to run if ENVIRONMENT=production)
python -m app.seed
#   admin@example.com / changeme-dev-only   (dev only)

# start the API. COOKIE_SECURE=false is required for local http dev, otherwise
# the browser won't store the refresh cookie over http://localhost.
COOKIE_SECURE=false uvicorn app.main:app --reload
# docs at http://localhost:8000/docs  (disabled when ENVIRONMENT=production)
```

`JWT_SECRET` is optional in dev — an ephemeral one is generated per process, so
sessions don't survive a restart. In production it is **required** and must be at
least 32 characters; the app refuses to start otherwise.

## Tests

```bash
pytest -q          # 144 tests
ruff check .
```

The suite is deliberately weighted toward the things that are expensive to get
wrong:

| File | Covers |
|---|---|
| `test_authz.py` | cross-tenant isolation on every id-taking endpoint (404, never 403) |
| `test_config_guards.py` | startup refusal on weak secrets / un-anonymized cloud use |
| `test_auth_lifecycle.py` | throttling, timing equalisation, refresh rotation + reuse detection |
| `test_validation.py` | every input that used to reach the DB and 500 |
| `test_capture_commit.py` | commit replay protection, raw-text minimization |
| `test_exports.py` | CSV formula injection, ReportLab markup injection, filename headers |
| `test_anonymize.py` | roster/fuzzy/phonetic/gazetteer coverage, placeholder round trip |

CI also runs the migrations against Postgres and asserts an **empty
`alembic revision --autogenerate` diff** — models and migration history must not
drift.

## Smoke test (end to end, no key)

```bash
alembic upgrade head && python -m app.seed && python -m scripts.smoke
```

Exercises login → class → students → capture → commit → list, and prints the
proposed observations (including an off-roster name that resolves to
`create_student`).

## Run on the server (Postgres, Docker)

See `../deploy/README.md`. Migrations run in a dedicated one-shot `migrate`
service, not from the backend's `CMD` — a failed migration aborts the deploy
instead of crash-looping the API.

The container runs as an unprivileged user and installs from the hash-pinned
`requirements.lock`. Regenerate that after changing `pyproject.toml`:

```bash
uv pip compile pyproject.toml --generate-hashes -o requirements.lock
```

## Using the real cloud structurer (Anthropic)

The stub is the default so the app runs with no key. To use the real Stage 2
cloud model instead:

```bash
export AI_PROVIDER=anthropic
export ANTHROPIC_API_KEY=sk-ant-...
# optional: export STRUCTURER_MODEL=claude-sonnet-4-6   (default)
# optional: export STRUCTURER_TIMEOUT_S=30               (per-attempt timeout)

# live check (no DB), prints parsed observations for a sample German dictation:
python -m scripts.smoke_anthropic
```

The structurer uses forced tool-calling for schema-safe JSON and only splits +
sentiment-tags the text — name→student matching stays deterministic in the
backend (`resolve.py`), identical in stub and cloud modes. The client carries an
explicit timeout: the SDK default is 10 minutes, which on a threadpool worker is
enough for a handful of slow calls to freeze the whole API.

**Anonymization is on by default and enforced.** With `AI_PROVIDER=anthropic` and
`ANONYMIZE_ENABLED=false`, startup fails unless `ALLOW_CLOUD_PII=true` is also
set. See `../deploy/README.md` for what the anonymizer does and does not protect.

## Maintenance commands

```bash
python -m app.create_admin you@example.com        # prompts; resets revoke sessions
python -m app.purge --dry-run                     # retention preview
python -m app.purge                               # apply retention
python -m app.purge --student <uuid>              # erasure request
```

## Configuration

Every setting is an environment variable; see `app/config.py` for the full list
with defaults. The ones that change behaviour most:

| Variable | Default | Notes |
|---|---|---|
| `ENVIRONMENT` | `dev` | `production` enables the startup guards and disables `/docs` |
| `JWT_SECRET` | — | Required in production, ≥32 chars |
| `ANONYMIZE_ENABLED` | `true` | Refuses to be false alongside a cloud provider |
| `ALLOW_CLOUD_PII` | `false` | Deliberate override for the above |
| `STRUCTURER_TIMEOUT_S` | `30` | Per-attempt; worst case ≈ this × (retries + 1) |
| `RAW_CAPTURE_RETENTION_DAYS` | `30` | Enforced by `app.purge` |
| `ACCESS_TOKEN_MINUTES` | `15` | Refresh cookie carries the 30-day session |
| `LOGIN_MAX_ATTEMPTS_PER_EMAIL` | `5` | In-process; single-replica assumption |
