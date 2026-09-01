#!/usr/bin/env bash
set -euo pipefail

DB_HOST="${DB_HOST:-localhost}"
DB_PORT="${DB_PORT:-5432}"
DB_USER="${DB_USER:-precut}"
DB_NAME="${DB_NAME:-precut}"
PREVIEWS_DIR="${PREVIEWS_DIR:-./data/previews}"

if [[ -z "${DB_PASSWORD:-}" ]]; then
  echo "Set DB_PASSWORD in your environment or .env before exporting."
  exit 1
fi

export PGPASSWORD="${DB_PASSWORD}"

echo "Exporting database ${DB_NAME} from ${DB_HOST}:${DB_PORT}..."
pg_dump -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" "$DB_NAME" > precut.dump

if [[ ! -d "$PREVIEWS_DIR" ]]; then
  echo "Preview directory not found: $PREVIEWS_DIR"
  exit 1
fi

preview_parent="$(cd "$(dirname "$PREVIEWS_DIR")" && pwd)"
preview_name="$(basename "$PREVIEWS_DIR")"

echo "Exporting previews from ${PREVIEWS_DIR}..."
tar czf previews.tar.gz -C "$preview_parent" "$preview_name"

echo "Done. Created:"
echo "  precut.dump"
echo "  previews.tar.gz"
