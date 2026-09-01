# Deployment Guide

One-time bulk indexing on your PC, then migrate to a Docker stack on your Debian server.

## Phase 1: Index on your PC

### 1. Start local Postgres

Option A — Docker (recommended):

```bash
cp .env.example .env
# Edit .env: set ACCESS_TOKEN and DB_PASSWORD

docker compose -f docker-compose.dev.yml up -d
```

Option B — system Postgres with pgvector installed locally.

For Docker dev Postgres, set in `.env`:

```
DB_HOST=localhost
DB_PORT=5432
DB_USER=precut
DB_PASSWORD=your_password
DB_NAME=precut
```

### 2. Install Python dependencies

```bash
poetry install
```

Install `ffmpeg` on your system if not already present.

### 3. Run the bot and index all precuts

```bash
poetry run python main.py
```

In Discord:

1. Use `/register` for each precut channel
2. Wait for indexing to finish (`0 remaining` in the progress bar)
3. Indexing is resumable — safe to stop and restart

### 4. Export data

```bash
set -a && source .env && set +a
chmod +x scripts/export-data.sh
./scripts/export-data.sh
```

This creates:

- `precut.dump` — Postgres database
- `previews.tar.gz` — scene preview images

### 5. Copy to server

```bash
scp precut.dump previews.tar.gz user@your-server:/opt/precut-finder/
```

## Phase 2: Run on Debian server

### 1. Install Docker

Install Docker Engine and Docker Compose plugin on Debian.

### 2. Configure environment

```bash
git clone <your-repo> /opt/precut-finder
cd /opt/precut-finder
cp .env.example .env
```

Edit `.env`:

```
ACCESS_TOKEN=your_discord_bot_token
DB_PASSWORD=strong_server_password
DB_USER=precut
DB_NAME=precut
```

Leave `DB_HOST` empty in `.env` — `docker-compose.yml` sets `DB_HOST=postgres` for the bot container.

### 3. Import migrated data

Place `precut.dump` and `previews.tar.gz` in the project directory, then:

```bash
chmod +x scripts/import-data.sh
./scripts/import-data.sh
```

This starts Postgres, restores the dump into a fresh database, loads preview files into the Docker volume, then starts the bot.

Alternatively, to start with an empty database and import manually:

```bash
docker compose up -d postgres
./scripts/import-data.sh
```

### 4. Verify

- Bot shows online in Discord
- @mention the bot with a test image — search returns results with preview thumbnails
- Post a new precut in a registered channel — it indexes on the server automatically

## Ongoing operation

The server handles everything after migration:

- Image search
- Indexing new precuts (one at a time)
- Removing deleted precuts

No PC involvement needed unless you want to re-index a large batch.

## Environment variables

| Variable | Description |
|----------|-------------|
| `ACCESS_TOKEN` | Discord bot token |
| `DB_HOST` | Postgres host (`postgres` in Docker, `localhost` for local dev) |
| `DB_PORT` | Postgres port (default `5432`) |
| `DB_USER` | Postgres user (default `precut`) |
| `DB_PASSWORD` | Postgres password |
| `DB_NAME` | Database name (default `precut`) |
| `SCHEMA_PATH` | Path to `schema.sql` |
| `PREVIEWS_DIR` | Directory for scene preview JPEGs |

## Preview paths

Preview paths in the database are stored **relative** to `PREVIEWS_DIR` (e.g. `{content_hash}/0.jpg`) so the database can be moved between machines without broken embed images.
