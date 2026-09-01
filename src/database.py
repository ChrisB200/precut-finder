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


def init_database():
    schema = SCHEMA_PATH.read_text()
    cursor.execute(schema)
    register_vector(connection)
    connection.commit()


def get_last_message_id(channel_id: int) -> int | None:
    cursor.execute(
        """
        SELECT MAX(message_id) AS message_id
        FROM precuts
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


def add_scene(
    precut_id: int, scene_index: int, start_time: float, end_time: float
) -> int:
    cursor.execute(
        """
        INSERT INTO scenes (
            precut_id,
            scene_index,
            start_time,
            end_time
        )
        VALUES (%s, %s, %s, %s)
        RETURNING id
    """,
        (precut_id, scene_index, start_time, end_time),
    )

    scene_id = cursor.fetchall()[0]["id"]
    connection.commit()
    logger.debug("Added scene %d", scene_id)

    return scene_id


def add_precut(
    id: int,
    message_id: int,
    channel_id: int,
    user_id: int,
    created_at: datetime,
) -> bool:
    cursor.execute(
        """
        INSERT INTO precuts (
            id,
            message_id,
            channel_id,
            user_id,
            created_at
        )
        VALUES (%s, %s, %s, %s, %s)
        ON CONFLICT (id) DO NOTHING
        """,
        (id, message_id, channel_id, user_id, created_at),
    )

    if cursor.rowcount == 0:
        logger.debug("Precut %d already exists", id)
        return False

    connection.commit()
    logger.debug("Added precut %d", id)

    return True


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


def search_similar_frames(
    embedding: NDArray[np.float32],
    limit: int = 10,
):
    cursor.execute(
        """
        SELECT
            fe.frame_id,
            fe.scene_id,
            s.precut_id,
            s.scene_index,
            s.start_time,
            s.end_time,
            p.message_id,
            p.channel_id,
            fe.embedding <=> %s AS distance
        FROM frame_embeddings fe
        JOIN scenes s
            ON fe.scene_id = s.id
        JOIN precuts p
            ON s.precut_id = p.id
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
