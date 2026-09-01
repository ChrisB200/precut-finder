import logging
from datetime import datetime

import numpy as np
import psycopg2 as pg
from numpy._typing import NDArray
from pgvector.psycopg2 import register_vector
from psycopg2.extras import RealDictCursor

from src.config import DB_NAME, SCHEMA_PATH
from src.models import Channel, Scene

logger = logging.getLogger(__name__)

connection = pg.connect(dbname=DB_NAME, cursor_factory=RealDictCursor)
cursor = connection.cursor(cursor_factory=RealDictCursor)


def _table_exists(table_name: str) -> bool:
    cursor.execute(
        """
        SELECT EXISTS (
            SELECT 1
            FROM information_schema.tables
            WHERE table_schema = 'public'
              AND table_name = %s
        )
        """,
        (table_name,),
    )
    return cursor.fetchone()["exists"]


def _column_exists(table_name: str, column_name: str) -> bool:
    cursor.execute(
        """
        SELECT EXISTS (
            SELECT 1
            FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name = %s
              AND column_name = %s
        )
        """,
        (table_name, column_name),
    )
    return cursor.fetchone()["exists"]


def migrate_legacy_schema() -> None:
    if not _table_exists("precuts"):
        return

    logger.info("Migrating legacy precuts schema")

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS indexed_precuts (
            id BIGSERIAL PRIMARY KEY,
            content_hash TEXT UNIQUE NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS precut_posts (
            attachment_id BIGINT PRIMARY KEY,
            indexed_precut_id BIGINT NOT NULL,
            message_id BIGINT NOT NULL,
            channel_id BIGINT NOT NULL,
            user_id BIGINT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL,
            FOREIGN KEY (indexed_precut_id) REFERENCES indexed_precuts(id) ON DELETE CASCADE,
            FOREIGN KEY (channel_id) REFERENCES channels(id)
        )
        """
    )

    cursor.execute(
        """
        INSERT INTO indexed_precuts (content_hash, created_at)
        SELECT 'legacy:' || id::TEXT, created_at
        FROM precuts
        ON CONFLICT (content_hash) DO NOTHING
        """
    )
    cursor.execute(
        """
        INSERT INTO precut_posts (
            attachment_id,
            indexed_precut_id,
            message_id,
            channel_id,
            user_id,
            created_at
        )
        SELECT
            p.id,
            ip.id,
            p.message_id,
            p.channel_id,
            p.user_id,
            p.created_at
        FROM precuts p
        JOIN indexed_precuts ip
            ON ip.content_hash = 'legacy:' || p.id::TEXT
        ON CONFLICT (attachment_id) DO NOTHING
        """
    )

    if _column_exists("scenes", "precut_id"):
        if not _column_exists("scenes", "indexed_precut_id"):
            cursor.execute(
                """
                ALTER TABLE scenes
                ADD COLUMN indexed_precut_id BIGINT
                """
            )

        cursor.execute(
            """
            UPDATE scenes s
            SET indexed_precut_id = ip.id
            FROM indexed_precuts ip
            WHERE ip.content_hash = 'legacy:' || s.precut_id::TEXT
            """
        )

        cursor.execute(
            """
            ALTER TABLE scenes
            DROP CONSTRAINT IF EXISTS scenes_precut_id_fkey
            """
        )
        cursor.execute(
            """
            ALTER TABLE scenes
            DROP CONSTRAINT IF EXISTS scenes_precut_id_scene_index_key
            """
        )
        cursor.execute(
            """
            ALTER TABLE scenes
            DROP COLUMN precut_id
            """
        )
        cursor.execute(
            """
            ALTER TABLE scenes
            ALTER COLUMN indexed_precut_id SET NOT NULL
            """
        )
        cursor.execute(
            """
            ALTER TABLE scenes
            ADD CONSTRAINT scenes_indexed_precut_id_fkey
            FOREIGN KEY (indexed_precut_id)
            REFERENCES indexed_precuts(id)
            ON DELETE CASCADE
            """
        )
        cursor.execute(
            """
            ALTER TABLE scenes
            ADD CONSTRAINT scenes_indexed_precut_id_scene_index_key
            UNIQUE (indexed_precut_id, scene_index)
            """
        )

    cursor.execute("DROP TABLE precuts")
    logger.info("Legacy precuts migration complete")


def init_database():
    schema = SCHEMA_PATH.read_text()
    cursor.execute(schema)
    cursor.execute(
        """
        ALTER TABLE scenes
        ADD COLUMN IF NOT EXISTS preview_path TEXT
        """
    )
    migrate_legacy_schema()
    register_vector(connection)
    connection.commit()


def get_last_message_id(channel_id: int) -> int | None:
    cursor.execute(
        """
        SELECT MAX(message_id) AS message_id
        FROM precut_posts
        WHERE channel_id = %s
        """,
        (channel_id,),
    )
    row = cursor.fetchone()
    if row is None or row["message_id"] is None:
        logger.warning("Could not find message id in channel %d", channel_id)
        return None

    message_id = row["message_id"]
    return message_id


def get_channels() -> list[Channel]:
    cursor.execute("SELECT * FROM channels")
    channels = cursor.fetchall()

    logger.debug("loaded %d channels from db", len(channels))
    return [Channel.from_row(c) for c in channels]


def is_channel_registered(channel_id: int) -> bool:
    cursor.execute(
        """
        SELECT 1
        FROM channels
        WHERE id = %s
        """,
        (channel_id,),
    )
    return cursor.fetchone() is not None


def add_channel(id: int):
    cursor.execute(
        """
        INSERT INTO channels (id)
        VALUES (%s)
        ON CONFLICT (id) DO NOTHING
        """,
        (id,),
    )
    connection.commit()

    if cursor.rowcount == 0:
        logger.debug("Channel %d already exists", id)
        return False

    return True


def precut_post_exists(attachment_id: int) -> bool:
    cursor.execute(
        """
        SELECT 1
        FROM precut_posts
        WHERE attachment_id = %s
        """,
        (attachment_id,),
    )
    return cursor.fetchone() is not None


def get_indexed_precut_by_hash(content_hash: str) -> dict | None:
    cursor.execute(
        """
        SELECT id, content_hash, created_at
        FROM indexed_precuts
        WHERE content_hash = %s
        """,
        (content_hash,),
    )
    return cursor.fetchone()


def get_or_create_indexed_precut(content_hash: str) -> int:
    cursor.execute(
        """
        INSERT INTO indexed_precuts (content_hash)
        VALUES (%s)
        ON CONFLICT (content_hash) DO UPDATE
            SET content_hash = EXCLUDED.content_hash
        RETURNING id
        """,
        (content_hash,),
    )
    indexed_precut_id = cursor.fetchone()["id"]
    connection.commit()
    return indexed_precut_id


def indexed_precut_has_scenes(indexed_precut_id: int) -> bool:
    cursor.execute(
        """
        SELECT 1
        FROM scenes
        WHERE indexed_precut_id = %s
        LIMIT 1
        """,
        (indexed_precut_id,),
    )
    return cursor.fetchone() is not None


def indexed_precut_is_fully_indexed(indexed_precut_id: int) -> bool:
    cursor.execute(
        """
        SELECT
            COUNT(DISTINCT s.id) AS scene_count,
            COUNT(fe.frame_id) AS embedding_count
        FROM scenes s
        LEFT JOIN frame_embeddings fe
            ON fe.scene_id = s.id
        WHERE s.indexed_precut_id = %s
        """,
        (indexed_precut_id,),
    )
    row = cursor.fetchone()
    scene_count = row["scene_count"]

    if scene_count == 0:
        return False

    return row["embedding_count"] == scene_count * 3


def reset_incomplete_indexed_precut(indexed_precut_id: int) -> None:
    cursor.execute(
        """
        SELECT COUNT(*) AS post_count
        FROM precut_posts
        WHERE indexed_precut_id = %s
        """,
        (indexed_precut_id,),
    )
    post_count = cursor.fetchone()["post_count"]

    if post_count == 0:
        cursor.execute(
            """
            DELETE FROM indexed_precuts
            WHERE id = %s
            """,
            (indexed_precut_id,),
        )
    else:
        cursor.execute(
            """
            DELETE FROM scenes
            WHERE indexed_precut_id = %s
            """,
            (indexed_precut_id,),
        )

    connection.commit()


def prepare_indexed_precut(content_hash: str) -> tuple[int, bool]:
    existing = get_indexed_precut_by_hash(content_hash)

    if existing is None:
        return get_or_create_indexed_precut(content_hash), False

    indexed_precut_id = existing["id"]

    if indexed_precut_is_fully_indexed(indexed_precut_id):
        return indexed_precut_id, True

    reset_incomplete_indexed_precut(indexed_precut_id)

    existing = get_indexed_precut_by_hash(content_hash)
    if existing is None:
        return get_or_create_indexed_precut(content_hash), False

    return existing["id"], False


def add_precut_post(
    attachment_id: int,
    indexed_precut_id: int,
    message_id: int,
    channel_id: int,
    user_id: int,
    created_at: datetime,
) -> bool:
    cursor.execute(
        """
        INSERT INTO precut_posts (
            attachment_id,
            indexed_precut_id,
            message_id,
            channel_id,
            user_id,
            created_at
        )
        VALUES (%s, %s, %s, %s, %s, %s)
        ON CONFLICT (attachment_id) DO NOTHING
        """,
        (
            attachment_id,
            indexed_precut_id,
            message_id,
            channel_id,
            user_id,
            created_at,
        ),
    )

    if cursor.rowcount == 0:
        logger.debug("Precut post %d already exists", attachment_id)
        return False

    connection.commit()
    logger.debug(
        "Added precut post %d for indexed precut %d",
        attachment_id,
        indexed_precut_id,
    )
    return True


def add_scene(
    indexed_precut_id: int,
    scene_index: int,
    start_time: float,
    end_time: float,
    preview_path: str | None = None,
) -> int:
    cursor.execute(
        """
        INSERT INTO scenes (
            indexed_precut_id,
            scene_index,
            start_time,
            end_time,
            preview_path
        )
        VALUES (%s, %s, %s, %s, %s)
        RETURNING id
    """,
        (indexed_precut_id, scene_index, start_time, end_time, preview_path),
    )

    scene_id = cursor.fetchall()[0]["id"]
    connection.commit()
    logger.debug("Added scene %d", scene_id)

    return scene_id


def add_frame_embedding(
    scene_id: int,
    embedding: NDArray[np.float32],
) -> int:
    cursor.execute(
        """
        INSERT INTO frame_embeddings (
            scene_id,
            embedding
        )
        VALUES (%s, %s)
        RETURNING frame_id
        """,
        (scene_id, embedding),
    )

    row = cursor.fetchall()[0]
    frame_id = row["frame_id"]

    connection.commit()

    logger.debug(
        "Added frame embedding %d to scene %d",
        frame_id,
        scene_id,
    )

    return frame_id


def get_tracked_message_ids(channel_id: int) -> list[int]:
    cursor.execute(
        """
        SELECT DISTINCT message_id
        FROM precut_posts
        WHERE channel_id = %s
        """,
        (channel_id,),
    )
    return [row["message_id"] for row in cursor.fetchall()]


def delete_precut_posts_for_message(
    channel_id: int,
    message_id: int,
) -> list[str]:
    cursor.execute(
        """
        SELECT DISTINCT pp.indexed_precut_id, ip.content_hash
        FROM precut_posts pp
        JOIN indexed_precuts ip
            ON pp.indexed_precut_id = ip.id
        WHERE pp.channel_id = %s
          AND pp.message_id = %s
        """,
        (channel_id, message_id),
    )
    affected = cursor.fetchall()

    cursor.execute(
        """
        DELETE FROM precut_posts
        WHERE channel_id = %s
          AND message_id = %s
        """,
        (channel_id, message_id),
    )

    orphaned_hashes: list[str] = []

    for row in affected:
        cursor.execute(
            """
            SELECT 1
            FROM precut_posts
            WHERE indexed_precut_id = %s
            LIMIT 1
            """,
            (row["indexed_precut_id"],),
        )
        if cursor.fetchone() is not None:
            continue

        cursor.execute(
            """
            DELETE FROM indexed_precuts
            WHERE id = %s
            """,
            (row["indexed_precut_id"],),
        )
        orphaned_hashes.append(row["content_hash"])

    connection.commit()
    return orphaned_hashes


def search_similar_frames(
    embedding: NDArray[np.float32],
    limit: int = 10,
):
    cursor.execute(
        """
        SELECT
            fe.frame_id,
            fe.scene_id,
            s.indexed_precut_id,
            ip.content_hash,
            s.scene_index,
            s.start_time,
            s.end_time,
            s.preview_path,
            pp.message_id,
            pp.channel_id,
            fe.embedding <=> %s AS distance
        FROM frame_embeddings fe
        JOIN scenes s
            ON fe.scene_id = s.id
        JOIN indexed_precuts ip
            ON s.indexed_precut_id = ip.id
        JOIN precut_posts pp
            ON pp.indexed_precut_id = ip.id
        ORDER BY fe.embedding <=> %s
        LIMIT %s
        """,
        (
            embedding,
            embedding,
            limit,
        ),
    )

    return cursor.fetchall()
