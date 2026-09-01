#!/usr/bin/env bash
set -euo pipefail

DB_USER="${DB_USER:-precut}"
DB_NAME="${DB_NAME:-precut}"

if [[ ! -f precut.dump ]]; then
  echo "precut.dump not found in the current directory."
  exit 1
fi

if [[ ! -f previews.tar.gz ]]; then
  echo "previews.tar.gz not found in the current directory."
  exit 1
fi

echo "Ensuring postgres is running..."
docker compose up -d postgres

echo "Waiting for postgres to become healthy..."
until docker compose exec postgres pg_isready -U "$DB_USER" -d "$DB_NAME" >/dev/null 2>&1; do
  sleep 1
done

echo "Recreating database ${DB_NAME}..."
docker compose exec -T postgres psql -U "$DB_USER" -d postgres <<EOF
DROP DATABASE IF EXISTS ${DB_NAME};
CREATE DATABASE ${DB_NAME};
EOF

echo "Importing database dump..."
docker compose exec -T postgres psql -U "$DB_USER" -d "$DB_NAME" < precut.dump

echo "Building bot image if needed..."
docker compose build bot

echo "Importing preview files into previews volume..."
docker compose run --rm --no-deps \
  -v "$(pwd)/previews.tar.gz:/tmp/previews.tar.gz:ro" \
  bot bash -c "mkdir -p /app/data && tar xzf /tmp/previews.tar.gz -C /app/data/"

echo "Starting full stack..."
docker compose up -d

echo "Import complete."
