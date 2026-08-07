#!/usr/bin/env bash
# Reset the demo DB, restart the demo backend, retake all screenshots.
#
# Prerequisites: backend/.venv exists, the Vite dev server runs on :5173
# (cd frontend && npm run dev), node_modules installed here (npm install),
# and ImageMagick is on PATH.
set -e
HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
BE="$REPO/backend"

pkill -f "uvicorn demo_server" || true
sleep 1
rm -f "$HERE/demo.db"
cd "$BE"
DATABASE_URL="sqlite:///$HERE/demo.db" .venv/bin/alembic upgrade head >/dev/null 2>&1
DATABASE_URL="sqlite:///$HERE/demo.db" PYTHONPATH="$HERE" .venv/bin/python -c "import demo_seed; demo_seed.run()"

DATABASE_URL="sqlite:///$HERE/demo.db" PYTHONPATH="$HERE" \
  JWT_SECRET="handbuch-demo-secret-that-is-long-enough-32" COOKIE_SECURE=false \
  CORS_ORIGINS=http://localhost:5173 \
  nohup "$BE/.venv/bin/uvicorn" demo_server:app --port 8000 > "$HERE/backend.log" 2>&1 &
sleep 4

cd "$HERE"
node shots.mjs
mkdir -p "$HERE/shots/web"
cd "$HERE/shots"
for f in *.png; do
  b="${f%.png}"
  magick "$f" -resize 66.7% -quality 82 -define webp:method=6 "web/$b.webp"
done
echo "screenshots refreshed — now run: node build.mjs"
