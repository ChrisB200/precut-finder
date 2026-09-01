import os
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

load_dotenv()


def load_env(key: str, fallback: Any = None) -> Any:
    value = os.getenv(key)
    if value:
        return value

    if not value and fallback:
        return fallback

    raise ValueError(f"{key} key not in env file")


ACCESS_TOKEN = load_env("ACCESS_TOKEN")
DB_NAME = load_env("DB_NAME")
SCHEMA_PATH = Path(load_env("SCHEMA_PATH"))
