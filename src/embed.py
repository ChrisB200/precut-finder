import discord
from psycopg2.extras import RealDictRow

from src.utils import format_time


async def similar_embed(client: discord.Client, results: list[RealDictRow]):
    embed = discord.Embed(
        title="Most Similar",
        description="Precuts ranked by visual similarity",
    )

    for index, result in enumerate(results, start=1):
        channel = client.get_channel(result["channel_id"])

        if not isinstance(channel, discord.TextChannel):
            continue

        try:
            precut_message = await channel.fetch_message(result["message_id"])
        except discord.NotFound:
            continue

        similarity = 1 - result["distance"]

        embed.add_field(
            name=f"{index}. {precut_message.jump_url}",
            value=(
                f"**User:** {precut_message.author.mention}\n"
                f"**Channel:** {channel.mention}\n"
                f"**Scene:** "
                f"{format_time(result['start_time'])} → "
                f"{format_time(result['end_time'])}\n"
                f"**Similarity:** {similarity:.1%}\n"
            ),
            inline=False,
        )
    return embed
