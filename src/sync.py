import logging
import shutil

import discord

from src.config import PREVIEWS_DIR
from src.database import delete_precut_posts_for_message, get_tracked_message_ids

logger = logging.getLogger(__name__)


def cleanup_preview_files(content_hashes: list[str]) -> None:
    for content_hash in content_hashes:
        preview_dir = PREVIEWS_DIR / content_hash
        if not preview_dir.exists():
            continue

        shutil.rmtree(preview_dir)
        logger.info("Removed preview directory %s", preview_dir)


async def remove_precut_posts_for_message(
    channel_id: int,
    message_id: int,
) -> None:
    content_hashes = delete_precut_posts_for_message(channel_id, message_id)
    if not content_hashes:
        return

    cleanup_preview_files(content_hashes)
    logger.info(
        "Removed indexed precuts for deleted message %d in channel %d",
        message_id,
        channel_id,
    )


async def sync_channel_deletions(channel: discord.TextChannel) -> int:
    message_ids = get_tracked_message_ids(channel.id)
    removed = 0

    for message_id in message_ids:
        try:
            await channel.fetch_message(message_id)
        except discord.NotFound:
            await remove_precut_posts_for_message(channel.id, message_id)
            removed += 1
        except discord.HTTPException:
            logger.exception(
                "Could not verify message %d in channel %s",
                message_id,
                channel.name,
            )

    if removed:
        logger.info(
            "Removed %d deleted message(s) from channel %s",
            removed,
            channel.name,
        )

    return removed
