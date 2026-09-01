import logging
import tempfile
from pathlib import Path

import discord
from discord.ext import commands

from src.database import add_channel, get_channels, search_similar_frames
from src.embed import similar_embed
from src.embedding import embed_image, search_similar
from src.index import process_precuts
from src.precut import get_channel_precuts

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


@client.event
async def on_ready():
    logger.info("Logged in as %s", client.user)

    channels = get_channels()
    for channel in channels:
        dchannel = await client.fetch_channel(channel.id)
        if not isinstance(dchannel, discord.TextChannel):
            continue

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

        embed = await similar_embed(client, results)

        await message.reply(embed=embed)
        return

    await client.process_commands(message)


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
        await interaction.followup.send(
            "Channel is already registered.",
            ephemeral=True,
        )
        return

    precuts = await get_channel_precuts(channel)

    await interaction.followup.send(
        f"Added channel. Found {len(precuts)} precuts. Starting processing.",
        ephemeral=True,
    )

    await process_precuts(precuts)
