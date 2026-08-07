# Deploying muendlich (Docker + a TLS reverse proxy)

This is a multi-container app: **Postgres + FastAPI backend + an internal
nginx** that serves the PWA and proxies `/api` to the backend. Your reverse
proxy only ever talks to the `muendlich-web` container — it handles TLS and the
public hostname.

```
Internet ─► reverse proxy (TLS, app.example.com) ─► muendlich-web (nginx :8080)
                                                     ├── /        → PWA files
                                                     └── /api/*   → muendlich-backend:8000 ─► muendlich-db
```

Containers: `muendlich-web`, `muendlich-backend`, `muendlich-db`, plus a one-shot
`muendlich-migrate`. Only `muendlich-web` joins the external proxy network
(`PROXY_NETWORK` in `.env`); backend and db stay on a private `internal` network.

The walkthrough below uses [NGINX Proxy Manager](https://nginxproxymanager.com/)
as the TLS terminator because it is a common self-hosted choice, but any proxy
(Traefik, Caddy, plain nginx) works — it just has to reach `muendlich-web:8080`
and terminate HTTPS.

> **Upgrading an existing deployment? Two breaking changes:**
> 1. **`muendlich-web` now listens on 8080, not 80** (the container runs as an
>    unprivileged user). Edit the proxy host's forward port to `8080`.
> 2. **`JWT_SECRET` is now mandatory and must be ≥32 characters.** The backend
>    refuses to start without it — there is no longer a default. Changing it
>    logs everyone out once, which is expected.

## One-time deploy

1. **Get the code onto the server.** Pick any directory you own; the rest of this
   guide calls it `$APP_DIR`.
   ```bash
   export APP_DIR=/opt/muendlich          # adjust to taste
   sudo mkdir -p "$APP_DIR" && sudo chown "$USER:$USER" "$APP_DIR"
   git clone <your-repo-url> "$APP_DIR"
   cd "$APP_DIR/deploy"
   ```

2. **Create `.env`** from the template and fill in secrets:
   ```bash
   cp .env.example .env
   openssl rand -hex 32   # use for DB_PASSWORD
   openssl rand -hex 32   # use for JWT_SECRET
   nano .env
   ```
   - `DB_PASSWORD` — long random string
   - `JWT_SECRET` — **required**, ≥32 chars. The backend validates this at
     startup and refuses placeholder values.
   - `ANTHROPIC_API_KEY` — your key (keep `AI_PROVIDER=anthropic`)
   - `ANONYMIZE_ENABLED` — leave `true`. With a cloud provider the backend
     **refuses to start** if this is false (see *Anonymization* below).
   - `APP_ORIGIN` — the public HTTPS origin, e.g. `https://app.example.com`.
     Required; it is what CORS allows.
   - `PROXY_NETWORK` — the name of the existing Docker network your reverse
     proxy is on (`docker network ls`).

3. **DNS:** point the hostname you chose at your server — an `A`/`AAAA` record
   for a static address, or a `CNAME` to your dynamic-DNS name. Wait for it to
   propagate; confirm with `nslookup app.example.com`.

4. **Start the stack** (builds both images on the server):
   ```bash
   docker compose up -d --build
   ```
   The `migrate` service applies database migrations and exits before the
   backend starts. If it fails, the deploy stops there — check
   `docker compose logs migrate`.

5. **Create your admin account** (do NOT use the demo seed in production — it
   refuses to run when `ENVIRONMENT=production` anyway):
   ```bash
   # Omit the password to be prompted, keeping it out of shell history and `ps`:
   docker compose exec backend python -m app.create_admin you@example.com
   ```

6. **Reverse proxy host.** Route your hostname to `muendlich-web` on port
   **8080** over plain HTTP inside the Docker network, and terminate TLS at the
   proxy. In NGINX Proxy Manager (mind the known SSL-save bug — create the host
   first, add SSL second):
   - New Proxy Host → your domain, Forward Hostname `muendlich-web`,
     **Forward Port `8080`**, enable **Websockets Support** and
     **Block Common Exploits**. Save **without SSL**.
   - Edit the host → SSL tab → request a new Let's Encrypt cert, Force SSL. Save.
   - Also enable **HSTS** on the SSL tab. The app sets every other security
     header itself (CSP, nosniff, frame-deny); HSTS belongs at the TLS terminator.

7. **Schedule the retention job** (see *Data retention* below):
   ```bash
   ( crontab -l 2>/dev/null; \
     echo "17 3 * * * cd $APP_DIR/deploy && /usr/bin/docker compose exec -T backend python -m app.purge >> /var/log/muendlich-purge.log 2>&1" \
   ) | crontab -
   ```
   `$APP_DIR` is expanded when you run this, so the crontab ends up with an
   absolute path — verify with `crontab -l`.

8. **Test in an incognito window:** open your `APP_ORIGIN`, log in, and try a
   dictation. (HTTPS is required for the microphone — this is why it must go
   through the proxy, not a bare IP.)

## Updating after code changes

```bash
cd "$APP_DIR" && git pull
cd deploy && docker compose up -d --build
```

Migrations run in the dedicated `migrate` service before the backend starts, so a
failed migration aborts the deploy rather than crash-looping the API. The
Postgres volume (`deploy_db_data`) persists across rebuilds — your data is safe.

## Adding teacher accounts

Only an admin can create accounts (no self-signup). From the server:

```bash
docker compose exec backend python -m app.create_admin teacher@example.com
```

This creates the login (or resets its password if it already exists) and marks it
admin. Resetting a password **revokes every active session** for that account.
The teacher then logs in at your `APP_ORIGIN` and manages their
own classes/students under the **Verwalten** tab. Each teacher only ever sees
their own data.

> Note: `create_admin` makes every account an **admin**. For a single-teacher or
> trusted-colleague setup that's fine — no endpoint currently distinguishes admin
> from teacher, so the role is informational. A teacher-only role and an in-app
> "manage users" screen are a small future addition if you open it up more widely.

## Anonymization (on by default)

Student names are replaced with placeholders (`Student1`, `Person1`, `Ort1`)
**before** the cloud call and restored locally afterwards — names never leave your
server. It's deterministic: roster/alias matching (fuzzy + Kölner Phonetik), a
first-name gazetteer, and German spaCy NER for people and places.

This is now the **default**, and the backend enforces it: with
`AI_PROVIDER=anthropic` and `ANONYMIZE_ENABLED=false` it refuses to start unless
you also set `ALLOW_CLOUD_PII=true`. In production it additionally refuses to
start if the spaCy model is missing from the image, rather than silently
degrading to gazetteer-only coverage.

Verify after a capture:
```bash
docker compose exec db psql -U muendlich -c \
  "select anonymized_text from raw_captures order by created_at desc limit 1;"
```
It should contain only `Student…`/`Person…`/`Ort…` placeholders. The draft screen
in the app also shows you the exact text that was sent.

> **Honest caveat:** this is *pseudonymization*, not anonymization. It removes
> *names*, but the note *content* ("the boy who broke his arm") can still
> identify someone — no name-substitution scheme fixes that. Under GDPR/DSG
> pseudonymized data is still personal data, so **you still need a data
> processing agreement** with Anthropic and an entry in your processing register
> before using this with real pupils.
>
> The gazetteer ships a curated starter list of common German/Swiss first names;
> extend `backend/app/ai/data/first_names.txt` if you hit off-roster names it
> misses.

## Data retention

Verbatim dictations are cleared from `raw_captures` the moment a capture is
committed — the curated observations are the record of value. The purge job
handles what's left (abandoned and failed captures, expired refresh tokens):

```bash
docker compose exec -T backend python -m app.purge --dry-run   # preview
docker compose exec -T backend python -m app.purge             # apply
```

`RAW_CAPTURE_RETENTION_DAYS` (default 30) sets the window. Step 7 above schedules
this nightly.

**Erasure requests** are separate from the in-app delete. `DELETE` on a pupil in
the UI keeps their observations (deliberately — grading continuity). To erase a
pupil *and* every observation about them:

```bash
docker compose exec backend python -m app.purge --student <uuid> --dry-run
docker compose exec backend python -m app.purge --student <uuid>
```

## Audit log

Security-relevant events are emitted as JSON lines on the backend's stdout:
logins (success, failure, throttled), captures created/committed, exports, and
deletions. Observation text and dictations are never logged.

```bash
docker compose logs -f backend | grep '"action"'
docker compose logs backend | grep '"action":"export'      # who exported what
docker compose logs backend | grep '"action":"login.failure"'
```

Set a retention/rotation policy on the Docker log driver if you need these kept
for a defined period.

## Notes

- **Login persists ~30 days** via an httpOnly refresh cookie; the access token
  itself is short-lived (15 min) and renews silently. Refresh tokens are recorded
  server-side, rotated on every use, and revoked on logout — a stolen token
  cannot outlive a logout, and replaying an old one revokes the whole session
  family.
- **Login throttling** is in-process (per IP and per account). It is sized for
  the single `backend` replica here; if you ever scale out, move that state to
  Redis or each replica will allow its own quota.
- **Backups:** `docker exec muendlich-db pg_dump -U muendlich muendlich > backup.sql`.
