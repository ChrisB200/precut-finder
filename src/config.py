import os
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

load_dotenv()


def load_env(key: str, fallback: Any = None) -> Any:
    value = os.getenv(key)
    if value:
        return value

    if fallback is not None:
        return fallback

    raise ValueError(f"{key} key not in env file")


ACCESS_TOKEN = load_env("ACCESS_TOKEN")
DB_HOST = os.getenv("DB_HOST", "")
DB_PORT = int(os.getenv("DB_PORT", "5432"))
DB_USER = os.getenv("DB_USER", "")
DB_PASSWORD = os.getenv("DB_PASSWORD", "")
DB_NAME = load_env("DB_NAME", "precut")
SCHEMA_PATH = Path(load_env("SCHEMA_PATH", "src/schema.sql"))
PREVIEWS_DIR = Path(load_env("PREVIEWS_DIR", "./data/previews"))
