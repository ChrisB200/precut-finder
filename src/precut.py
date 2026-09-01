import hashlib
import logging
from pathlib import Path
from urllib.parse import urlparse

import aiohttp
import discord

from src.database import precut_post_exists

logger = logging.getLogger(__name__)


async def download_precut_from_url(
    url: str,
    output_dir: Path,
) -> tuple[Path, str]:
    extension = Path(urlparse(url).path).suffix
    output_path = output_dir / f"download{extension}"
    hasher = hashlib.sha256()

    async with aiohttp.ClientSession() as session:
        async with session.get(url) as response:
            response.raise_for_status()
            with output_path.open("wb") as file:
                async for chunk in response.content.iter_chunked(1024 * 1024):
                    hasher.update(chunk)
                    file.write(chunk)

    return output_path, hasher.hexdigest()


def get_precuts_from_message(message: discord.Message, user_id: int):
    attachments = list(message.attachments)
    precuts = []

    # some precuts are forwarded messages
    if message.message_snapshots:
        snapshot = message.message_snapshots[0]
        attachments = list(snapshot.attachments)

    for attachment in attachments:
        # elegible precuts
        if not attachment.content_type:
            continue

        if not attachment.content_type.startswith("video/"):
            continue

        is_video = (
            attachment.content_type is not None
            and attachment.content_type.startswith("video/")
        ) or attachment.filename.lower().endswith((".mp4", ".mov", ".webm", ".mkv"))

        if not is_video:
            continue

        channel_id = message.channel.id
        precut = {
            "id": attachment.id,
            "message_id": message.id,
            "user_id": user_id,
            "channel_id": channel_id,
            "attachment_url": attachment.url,
            "created_at": message.created_at.isoformat(),
        }

        precuts.append(precut)

    logger.debug("Found %d precuts attached to message %d", len(precuts), message.id)
    return precuts


def filter_pending_precuts(precuts: list[dict]) -> list[dict]:
    return [precut for precut in precuts if not precut_post_exists(precut["id"])]


async def get_channel_precuts(channel: discord.TextChannel) -> list[dict]:
    precuts: list[dict] = []

    logger.info("Scanning channel #%s for precuts", channel.name)

    async for message in channel.history(limit=None):
        precuts.extend(get_precuts_from_message(message, message.author.id))

    pending = filter_pending_precuts(precuts)

    logger.info(
        "Channel #%s: %d total precuts, %d indexed, %d remaining",
        channel.name,
        len(precuts),
        len(precuts) - len(pending),
        len(pending),
    )

    return precuts
