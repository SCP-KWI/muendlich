# muendlich — Technical Design

**Author:** Philip Schaffner
**Date:** 2026-07-01
**Status:** Draft v1 — companion to REQUIREMENTS.md v3
**Scope:** Phase 1 build, with Phase 2 hooks (anonymization) designed in but disabled.

---

## 1. Stack & Conventions

| Concern | Choice |
|---------|--------|
| Backend | Python 3.12 + **FastAPI** (Pydantic v2, Uvicorn) |
| DB | **PostgreSQL 16**, accessed via SQLAlchemy 2.0 + Alembic migrations |
| Frontend | **React (Vite) PWA**, served as static files; German UI, `de-DE` dictation |
| Auth | JWT access token + refresh token (httpOnly cookie); passwords hashed with **argon2** |
| Stage 1 (anonymize) | In-process: **rapidfuzz** + **Kölner Phonetik** roster matching + **spaCy `de_core_news_md`** NER. *Disabled in Phase 1.* |
| Stage 2 (structure) | Cloud LLM via official SDK (Anthropic **or** OpenAI) behind a `Structurer` interface, using tool/function-calling for schema-safe JSON |
| Deploy | **Docker Compose**: `db` + `backend` (+ optional `caddy` for HTTPS/static) |

**Cross-cutting rules**
- All IDs are UUID v4.
- All timestamps are UTC ISO-8601; `lesson_date` is a **date** (defaults to today in the user's timezone at capture).
- Every data query is **scoped to the authenticated user** (see §5). This is the multi-user isolation boundary.
- API base path: `/api`. JSON everywhere. Errors use RFC-7807-style `{ "detail": ... }`.

---

## 2. Repository Layout

```
muendlich/
├── REQUIREMENTS.md
├── TECHNICAL_DESIGN.md
├── docker-compose.yml
├── .env.example
├── backend/
│   ├── Dockerfile
│   ├── pyproject.toml
│   ├── alembic/                # migrations
│   └── app/
│       ├── main.py             # FastAPI app + routers
│       ├── config.py           # env-driven settings
│       ├── db.py               # engine/session
│       ├── models.py           # SQLAlchemy models
│       ├── schemas.py          # Pydantic request/response
│       ├── auth.py             # login, JWT, deps (current_user, require_admin)
│       ├── deps.py             # scoping helpers
│       ├── routers/            # auth, admin, classes, students, captures, observations, export
│       └── ai/
│           ├── pipeline.py     # orchestrates Stage 1 → Stage 2 → resolution
│           ├── anonymize.py    # Stage 1 (roster + phonetic + spaCy); pass-through if disabled
│           ├── structurer.py   # Structurer interface
│           ├── structurer_anthropic.py
│           ├── structurer_openai.py
│           └── resolve.py      # name → student resolution (fuzzy/phonetic)
└── frontend/
    ├── Dockerfile
    ├── package.json
    └── src/                    # React PWA (capture + review views)
```

---

## 3. Database Schema (Migrations)

Presented as SQL for clarity; in practice each block is one Alembic revision.

### 3.1 Enums & extensions

```sql
CREATE EXTENSION IF NOT EXISTS "pgcrypto";        -- gen_random_uuid()
CREATE TYPE user_role   AS ENUM ('admin', 'teacher');
CREATE TYPE sentiment   AS ENUM ('positive', 'neutral', 'negative');
CREATE TYPE capture_status AS ENUM ('pending', 'processed', 'committed', 'failed');
```

### 3.2 Core tables

```sql
CREATE TABLE users (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email         CITEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    role          user_role NOT NULL DEFAULT 'teacher',
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE classes (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id      UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name         TEXT NOT NULL,
    subject      TEXT,
    semester     TEXT,          -- e.g. 'HS2026'
    school_year  TEXT,          -- e.g. '2026/27'
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX ix_classes_user ON classes(user_id);

CREATE TABLE students (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    class_id    UUID NOT NULL REFERENCES classes(id) ON DELETE CASCADE,
    full_name   TEXT NOT NULL,
    short_name  TEXT,
    active      BOOLEAN NOT NULL DEFAULT true,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX ix_students_class ON students(class_id);

-- Aliases/nicknames/spelling variants improve name matching (Phase 2 UI; table exists in Phase 1)
CREATE TABLE student_aliases (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    student_id  UUID NOT NULL REFERENCES students(id) ON DELETE CASCADE,
    alias       TEXT NOT NULL
);
CREATE INDEX ix_aliases_student ON student_aliases(student_id);

-- Raw dictation, kept for audit / re-processing so nothing is ever lost
CREATE TABLE raw_captures (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id          UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    class_id         UUID NOT NULL REFERENCES classes(id) ON DELETE CASCADE,
    raw_text         TEXT NOT NULL,
    anonymized_text  TEXT,                 -- NULL in Phase 1 (anonymizer disabled)
    status           capture_status NOT NULL DEFAULT 'pending',
    lesson_date      DATE NOT NULL,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    processed_at     TIMESTAMPTZ
);
CREATE INDEX ix_captures_class ON raw_captures(class_id);

CREATE TABLE observations (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    class_id        UUID NOT NULL REFERENCES classes(id) ON DELETE CASCADE,
    student_id      UUID REFERENCES students(id) ON DELETE SET NULL,  -- NULL = unassigned
    raw_capture_id  UUID REFERENCES raw_captures(id) ON DELETE SET NULL,
    text            TEXT NOT NULL,
    sentiment       sentiment NOT NULL,
    manual_score    SMALLINT,              -- optional; app does not compute the official mark
    lesson_date     DATE NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX ix_obs_class    ON observations(class_id);
CREATE INDEX ix_obs_student  ON observations(student_id);
CREATE INDEX ix_obs_date     ON observations(lesson_date);
```

**Notes**
- `CITEXT` makes emails case-insensitive-unique. `manual_score` range is enforced in the API, not the DB, so the scale can change without a migration.
- Retention is indefinite (per requirements); deletion is user-initiated. `ON DELETE SET NULL` on `observations.student_id` means removing a student doesn't erase the history — the note survives as unassigned.

---

## 4. Authentication

Accounts are **admin-created** (no self-registration).

- `POST /api/auth/login` → verifies argon2 hash, returns `{ "access_token": "...", "token_type": "bearer" }` (15 min) **and** sets a refresh token in an httpOnly, Secure, SameSite=Strict cookie (30 days). This keeps the PWA logged in between lessons (FR-M1) without re-auth.
- `POST /api/auth/refresh` → rotates the refresh cookie, returns a new access token.
- `POST /api/auth/logout` → clears the refresh cookie.
- Access token carries `sub` (user id) and `role`. FastAPI dependencies:
  - `current_user` — decodes token, loads user.
  - `require_admin` — 403 unless `role == 'admin'`.

---

## 5. Data-Isolation Pattern

A single dependency resolves an owned resource and 404s if it isn't the caller's:

```python
def get_owned_class(class_id: UUID, user = Depends(current_user), db = Depends(get_db)) -> Class:
    cls = db.get(Class, class_id)
    if cls is None or cls.user_id != user.id:
        raise HTTPException(404)   # 404 not 403: don't reveal existence
    return cls
```

Student/observation/capture routes resolve their parent class through this dependency, so **no query returns another teacher's data**. Admin endpoints are the only cross-user surface and expose account metadata only — never observation content.

---

## 6. REST API

All routes require a valid access token unless noted. `{id}` are UUIDs.

### 6.1 Auth & profile
| Method | Path | Body / Notes | Returns |
|--------|------|--------------|---------|
| POST | `/api/auth/login` | `{email, password}` | `{access_token}` + refresh cookie |
| POST | `/api/auth/refresh` | (cookie) | `{access_token}` |
| POST | `/api/auth/logout` | — | 204 |
| GET  | `/api/me` | — | `{id, email, role}` |

### 6.2 Admin (require_admin)
| Method | Path | Body | Returns |
|--------|------|------|---------|
| GET | `/api/admin/users` | — | `[{id,email,role,created_at}]` |
| POST | `/api/admin/users` | `{email, role?, temp_password}` | created user |
| POST | `/api/admin/users/{id}/reset-password` | `{temp_password}` | 204 |
| DELETE | `/api/admin/users/{id}` | — | 204 (cascades that user's data) |

### 6.3 Classes
| Method | Path | Body | Returns |
|--------|------|------|---------|
| GET | `/api/classes` | — | list of caller's classes |
| POST | `/api/classes` | `{name, subject?, semester?, school_year?}` | class |
| GET | `/api/classes/{id}` | — | class + student count |
| PATCH | `/api/classes/{id}` | partial | class |
| DELETE | `/api/classes/{id}` | — | 204 |

### 6.4 Students
| Method | Path | Body | Returns |
|--------|------|------|---------|
| GET | `/api/classes/{classId}/students` | — | students in class |
| POST | `/api/classes/{classId}/students` | `{full_name, short_name?, aliases?[]}` | student |
| PATCH | `/api/students/{id}` | partial (incl. `active`) | student |
| DELETE | `/api/students/{id}` | — | 204 (observations become unassigned) |
| POST | `/api/students/{id}/aliases` | `{alias}` | alias |
| DELETE | `/api/aliases/{id}` | — | 204 |

### 6.5 Capture & processing (the core flow)
| Method | Path | Body | Returns |
|--------|------|------|---------|
| POST | `/api/classes/{classId}/captures` | `{raw_text, lesson_date?}` | **draft** (see §7) — runs Stage 1→2→resolve, persists a `raw_captures` row (`status=processed`), returns proposed observations. Does **not** yet create `observations`. |
| POST | `/api/captures/{id}/commit` | commit body (§7.4) | `{saved:[obs...], created_students:[...]}` — persists observations, sets capture `status=committed`. |
| GET | `/api/captures/{id}` | — | the stored draft (for retry/resume) |

### 6.6 Observations & review
| Method | Path | Query / Body | Returns |
|--------|------|--------------|---------|
| GET | `/api/classes/{classId}/observations` | `?student_id&from&to&sentiment` | filtered list |
| POST | `/api/classes/{classId}/observations` | `{student_id?, text, sentiment, manual_score?, lesson_date?}` | manual (typed) entry |
| GET | `/api/students/{id}/observations` | — | chronological list |
| GET | `/api/students/{id}/summary` | — | `{counts:{positive,neutral,negative}, avg_score, timeline:[...]}` (marking view) |
| PATCH | `/api/observations/{id}` | partial (`text, sentiment, manual_score, student_id`) | observation (reassign allowed) |
| DELETE | `/api/observations/{id}` | — | 204 |

### 6.7 Export
| Method | Path | Query | Returns |
|--------|------|-------|---------|
| GET | `/api/classes/{classId}/export` | `?format=csv\|pdf` | file download |
| GET | `/api/students/{id}/export` | `?format=csv\|pdf` | file download (per-student marking sheet) |

---

## 7. AI Pipeline & Contracts

The pipeline is `pipeline.process(raw_text, class, lesson_date)` → **draft**. Three steps:

```
raw_text ──▶ Stage 1: anonymize ──▶ Stage 2: structure (cloud) ──▶ resolve names ──▶ draft
             (Phase 2; no-op P1)      splits + sentiment            (deterministic)
```

### 7.1 Stage 1 — Anonymizer (internal)
Interface: `anonymize(text, roster) -> AnonymizeResult`.

```jsonc
// INPUT
{
  "text": "Anna was great today, helped Beatrice. Colin got on my nerves.",
  "roster": [
    {"student_id": "uuid-anna", "names": ["Anna", "Anni"]},
    {"student_id": "uuid-colin", "names": ["Colin"]}
    // Beatrice intentionally NOT on roster in this example
  ]
}

// OUTPUT (Phase 2, enabled)
{
  "anonymized_text": "Student1 was great today, helped Person1. Student2 got on my nerves.",
  "mapping": {
    "Student1": {"student_id": "uuid-anna",  "surface": "Anna",     "source": "roster"},
    "Student2": {"student_id": "uuid-colin", "surface": "Colin",    "source": "roster"},
    "Person1":  {"student_id": null,          "surface": "Beatrice", "source": "ner"}
  }
}
```

- **Layer (a)** roster/alias matching: rapidfuzz token match + Kölner Phonetik key, threshold-guarded, replaces hits with `Student{n}`.
- **Layer (b)** spaCy `de_core_news_md` `PER` entities not already replaced → `Person{n}` (off-roster; `student_id: null`).
- **Phase 1 (disabled):** returns `anonymized_text == text`, `mapping == {}`. `ANONYMIZE_ENABLED=false`.

### 7.2 Stage 2 — Structurer (cloud, tool-calling)
The model is given the (anonymized or raw) text and asked to call one tool. **Name→student matching is NOT done by the model** — it only extracts mentions, splits observations, and tags sentiment.

```jsonc
// Tool schema: record_observations
{
  "name": "record_observations",
  "input_schema": {
    "type": "object",
    "properties": {
      "observations": {
        "type": "array",
        "items": {
          "type": "object",
          "properties": {
            "mention":  {"type": "string", "description": "person referred to, verbatim as in the text (may be a placeholder like Student1)"},
            "text":     {"type": "string", "description": "the observation about that person, rewritten as a standalone note"},
            "sentiment":{"type": "string", "enum": ["positive", "neutral", "negative"]}
          },
          "required": ["mention", "text", "sentiment"]
        }
      }
    },
    "required": ["observations"]
  }
}
```

```jsonc
// Example model output (Phase 1, raw names)
{ "observations": [
  {"mention": "Anna",  "text": "War heute super, hat Beatrice geholfen.", "sentiment": "positive"},
  {"mention": "Colin", "text": "Ging mir auf die Nerven.",                "sentiment": "negative"}
]}
```

The system prompt is German-parameterized (per i18n requirement) and instructs: keep every person, never merge two people, output nothing but the tool call.

### 7.3 Resolution (deterministic backend step)
`resolve(observations, class, mapping) -> proposed[]`. For each `mention`:
- **Phase 2:** look up `mention` in `mapping` → exact `student_id` (or `null` for `Person*`).
- **Phase 1:** fuzzy/phonetic match `mention` against the roster (same matcher as Stage 1 Layer a) → best student + confidence.
- Assign a `status`:

| status | meaning | UI action |
|--------|---------|-----------|
| `matched` | confident single match | none |
| `low_confidence` | ambiguous / below threshold | confirm/correct |
| `off_roster` | no roster match (or NER `Person*`) | **add new student** or **map to existing** (FR-M7) |
| `unassigned` | user chose to keep without a student | — |

```jsonc
// DRAFT returned by POST /captures
{
  "capture_id": "uuid-cap",
  "lesson_date": "2026-07-01",
  "proposed": [
    {"temp_id": "o1", "mention": "Anna",  "text": "War heute super, hat Beatrice geholfen.",
     "sentiment": "positive", "match": {"student_id": "uuid-anna", "student_name": "Anna", "confidence": 0.98, "status": "matched"}},
    {"temp_id": "o2", "mention": "Colin", "text": "Ging mir auf die Nerven.",
     "sentiment": "negative", "match": {"student_id": "uuid-colin", "student_name": "Colin", "confidence": 0.91, "status": "matched"}},
    {"temp_id": "o3", "mention": "Beatrice", "text": "Wurde von Anna unterstützt.",
     "sentiment": "neutral",  "match": {"student_id": null, "student_name": null, "confidence": 0.0, "status": "off_roster"}}
  ]
}
```

### 7.4 Commit
Client resolves each proposed item and posts back:

```jsonc
// POST /api/captures/{id}/commit
{
  "lesson_date": "2026-07-01",
  "items": [
    {"temp_id": "o1", "action": "save",          "student_id": "uuid-anna", "text": "...", "sentiment": "positive", "manual_score": null},
    {"temp_id": "o2", "action": "save",          "student_id": "uuid-colin","text": "...", "sentiment": "negative"},
    {"temp_id": "o3", "action": "create_student","new_student_name": "Beatrice", "text": "...", "sentiment": "neutral"}
    // other actions: "map_existing" (+student_id), "unassigned", "discard"
  ]
}
```

Server creates any new students, inserts `observations`, marks the capture `committed`, and returns saved rows. All edits the user made on the phone (corrected text, sentiment, score) are respected — the model output is only a proposal.

---

## 8. Capture Sequence (end to end)

```
Phone (PWA)                Backend                     Cloud LLM
 │ pick class               │                            │
 │ dictate → on-device STT  │                            │
 │ (edit text)              │                            │
 │ POST /captures ─────────▶│ persist raw_capture        │
 │                          │ Stage1 anonymize (P1 no-op)│
 │                          │ Stage2 ───────────────────▶│ tool call
 │                          │ ◀─────────────────────────  observations JSON
 │                          │ resolve names (fuzzy)      │
 │ ◀──────────── draft ─────│                            │
 │ review / fix / resolve   │                            │
 │  off-roster (add/map)    │                            │
 │ POST /commit ───────────▶│ insert observations        │
 │ ◀──────────── saved ─────│ status=committed           │
```

If the network drops before commit, the draft is already persisted server-side (`status=processed`) and re-fetchable via `GET /captures/{id}`; the PWA also queues unsent `raw_text` locally (Phase 2 offline support).

---

## 9. Docker Compose Skeleton

```yaml
# docker-compose.yml
services:
  db:
    image: postgres:16
    environment:
      POSTGRES_DB: muendlich
      POSTGRES_USER: muendlich
      POSTGRES_PASSWORD: ${DB_PASSWORD}
    volumes:
      - db_data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U muendlich"]
      interval: 5s
      retries: 5

  backend:
    build: ./backend
    depends_on:
      db:
        condition: service_healthy
    environment:
      DATABASE_URL: postgresql+psycopg://muendlich:${DB_PASSWORD}@db:5432/muendlich
      JWT_SECRET: ${JWT_SECRET}
      AI_PROVIDER: ${AI_PROVIDER}            # "anthropic" | "openai"
      ANTHROPIC_API_KEY: ${ANTHROPIC_API_KEY}
      OPENAI_API_KEY: ${OPENAI_API_KEY}
      ANONYMIZE_ENABLED: "false"             # Phase 1 off; flip to "true" in Phase 2
      DEFAULT_TZ: "Europe/Zurich"            # for lesson_date "now"
    ports: ["8000:8000"]

  # Optional: TLS + serves the built PWA static files
  caddy:
    image: caddy:2
    depends_on: [backend]
    ports: ["80:80", "443:443"]
    volumes:
      - ./Caddyfile:/etc/caddy/Caddyfile
      - caddy_data:/data

volumes:
  db_data:
  caddy_data:
```

```dockerfile
# backend/Dockerfile (key steps)
FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml .
RUN pip install --no-cache-dir . \
 && python -m spacy download de_core_news_md   # Stage-1 model, baked into the image
COPY app ./app
COPY alembic ./alembic
CMD alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000
```

`.env.example`: `DB_PASSWORD`, `JWT_SECRET`, `AI_PROVIDER`, `ANTHROPIC_API_KEY`/`OPENAI_API_KEY`, `ANONYMIZE_ENABLED`.

> The spaCy model is installed at build time (§ requirements: no LLM container). If Phase 1 ships without anonymization, the download can be deferred to the Phase-2 image to keep the image smaller.

---

## 10. Security & Privacy Notes

- HTTPS only (Caddy auto-TLS); refresh token in httpOnly/Secure/SameSite=Strict cookie; access token in memory on the client (not localStorage).
- argon2id password hashing; admin sets a temp password, user changes on first login (Phase 1 minimum: admin-set password).
- Per-user scoping on every query (§5); 404 (not 403) on foreign resources.
- Phase 1 sends real names to the cloud (documented, personal use). Phase 2 flips `ANONYMIZE_ENABLED=true` so only placeholders leave the server; the placeholder→name map never persists beyond the request. Content-level identifiers in the note text remain a known limitation (pseudonymization, not anonymization).
- CORS restricted to the PWA origin. Rate-limit `/auth/login`.

---

## 11. Phase 1 vs Phase 2 Toggle Summary

| Capability | Phase 1 | Phase 2 |
|------------|---------|---------|
| Stage 1 anonymizer | pass-through no-op (`ANONYMIZE_ENABLED=false`) | roster+phonetic+spaCy on (`=true`) |
| Names sent to cloud | real names | placeholders only |
| Name→student resolution | fuzzy match on real names | exact via placeholder map |
| Offline queue-and-sync (PWA) | — | ✔ |
| Student trend view + PDF export | CSV export | + trend view + PDF marking sheet |
| Alias management UI | table exists, no UI | UI |

No schema or API changes are required to move from Phase 1 to Phase 2 — only configuration and the anonymizer implementation. This is the payoff of building the two-stage pipeline from the start.

---

*Open build-time choices (unchanged from REQUIREMENTS §13): cloud vendor for Stage 2; spaCy model size + matcher thresholds (tune on real dictation); PDF marking-sheet layout. Next step could be scaffolding the backend (`models.py`, first Alembic migration, and the `/captures` + `/commit` routes) so you have a runnable skeleton.*
