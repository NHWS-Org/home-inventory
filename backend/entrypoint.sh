#!/bin/sh

set -e

if [ ! -f /app/database.py ] || [ ! -f /app/main.py ] || [ ! -f /app/alembic.ini ]; then
    echo "ERROR: backend application files are missing from /app." >&2
    echo "A volume mounted over /app hides the code included in the image." >&2
    echo "Mount persistent storage at /app/data, not /app, and recreate the container." >&2
    exit 1
fi

cd /app

echo "📁 Creating /app/data and /app/data/backups..."
mkdir -p /app/data/backups
chmod 777 /app/data /app/data/backups

echo "⏳ Waiting for the configured database..."
python -u - <<'PY'
import time
from database import DATABASE_TYPE, engine, init_db

safe_url = engine.url.set(query={}).render_as_string(hide_password=True)
print(f"Database configured: {DATABASE_TYPE} ({safe_url})")

for attempt in range(60):
    try:
        with engine.connect():
            pass
        break
    except Exception:
        if attempt == 59:
            raise
        time.sleep(2)

print("🧱 Bootstrapping base schema...")
init_db()
PY

echo "🔄 Applying database migrations..."
alembic upgrade head

echo "🚀 Starting backend..."
exec uvicorn main:app --host 0.0.0.0 --port 8000 --reload --root-path "${FASTAPI_ROOT_PATH:-}"