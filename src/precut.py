import hashlib
import json
import logging
from pathlib import Path
from urllib.parse import urlparse

import aiohttp
import discord

from src.database import get_last_message_id

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


async def get_channel_precuts(channel: discord.TextChannel, fresh=False):
    precuts = []
    history = channel.history(limit=None)

    # getting the last message
    if fresh:
        logger.info("Syncing channel %s from the start", channel.name)
        history = channel.history(limit=None)
    else:
        last_message_id = get_last_message_id(channel.id)
        if not last_message_id:
            history = channel.history(limit=None)
            logger.info("Syncing channel %s from the start", channel.name)
        else:
            history = channel.history(
                limit=None, after=discord.Object(id=last_message_id), oldest_first=True
            )
            logger.info(
                "Syncing channel %s after message %d", channel.name, last_message_id
            )

    async for message in history:
        attachments = get_precuts_from_message(message, message.author.id)
        precuts.extend(attachments)

    if fresh:
        with open("src/precuts.json") as file:
            json.dump(precuts, file)

    return precuts
