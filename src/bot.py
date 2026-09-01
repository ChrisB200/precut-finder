import logging

import discord
from discord.ext import commands

from src.database import add_channel, get_channels
from src.embed import similar_embed
from src.embedding import search_similar
from src.index import process_precuts
from src.precut import get_channel_precuts, get_precuts_from_message
from src.sync import remove_precut_posts_for_message, sync_channel_deletions

logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)

prefix = ":"
intents = discord.Intents.default()
intents.message_content = True

client = commands.Bot(command_prefix=prefix, intents=intents)
registered_channel_ids: set[int] = set()


def load_registered_channels() -> None:
    registered_channel_ids.clear()
    registered_channel_ids.update(channel.id for channel in get_channels())


@client.event
async def on_ready():
    logger.info("Logged in as %s", client.user)

    load_registered_channels()

    channels = get_channels()
    for channel in channels:
        dchannel = await client.fetch_channel(channel.id)
        if not isinstance(dchannel, discord.TextChannel):
            continue

        await sync_channel_deletions(dchannel)
        precuts = await get_channel_precuts(dchannel)
        await process_precuts(precuts)

    await client.tree.sync()


@client.event
async def on_message(message: discord.Message):
    if message.author.bot:
        return

    if client.user in message.mentions and message.attachments:
        image = message.attachments[0]

        results = await search_similar(image)

        if not results:
            await message.reply("No results found.")
            return

        embed, files, view = await similar_embed(
            client,
            results,
            message.author.id,
        )

        if embed is None:
            await message.reply("No results found.")
            return

        await message.reply(embed=embed, files=files, view=view)
        return

    if message.channel.id in registered_channel_ids:
        precuts = get_precuts_from_message(message, message.author.id)
        if precuts:
            await process_precuts(precuts)

    await client.process_commands(message)


@client.event
async def on_raw_message_delete(payload: discord.RawMessageDeleteEvent):
    if payload.channel_id not in registered_channel_ids:
        return

    await remove_precut_posts_for_message(payload.channel_id, payload.message_id)


@client.event
async def on_raw_bulk_message_delete(payload: discord.RawBulkMessageDeleteEvent):
    if payload.channel_id not in registered_channel_ids:
        return

    for message_id in payload.message_ids:
        await remove_precut_posts_for_message(payload.channel_id, message_id)


@client.tree.command(
    name="register",
    description="Register a channel",
)
async def register_channel(
    interaction: discord.Interaction,
    channel: discord.TextChannel,
):
    await interaction.response.defer(ephemeral=True)

    added = add_channel(channel.id)

    if not added:
        registered_channel_ids.add(channel.id)
        await interaction.followup.send(
            "Channel is already registered.",
            ephemeral=True,
        )
        return

    registered_channel_ids.add(channel.id)

    await sync_channel_deletions(channel)
    precuts = await get_channel_precuts(channel)

    await interaction.followup.send(
        f"Added channel. Found {len(precuts)} precuts. Starting processing.",
        ephemeral=True,
    )

    await process_precuts(precuts)
