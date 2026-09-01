FROM python:3.12-slim-bookworm

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

RUN pip install --no-cache-dir poetry

COPY pyproject.toml poetry.lock ./
RUN poetry config virtualenvs.create false \
    && poetry install --no-interaction --no-ansi --no-root

COPY main.py ./
COPY src ./src

ENV SCHEMA_PATH=/app/src/schema.sql
ENV PREVIEWS_DIR=/app/data/previews

CMD ["python", "main.py"]
