from dataclasses import dataclass
from pathlib import Path

import discord
from psycopg2.extras import RealDictRow

from src.utils import format_time

PREVIEW_FILENAME = "preview.jpg"


@dataclass(slots=True)
class SearchResultItem:
    similarity: float
    channel_mention: str
    scene_range: str
    jump_url: str
    preview_path: str | None


def similarity_color(similarity: float) -> discord.Color:
    if similarity >= 0.9:
        return discord.Color.green()
    if similarity >= 0.75:
        return discord.Color.gold()
    return discord.Color.orange()


def preview_files(items: list[SearchResultItem], index: int) -> list[discord.File]:
    preview_path = items[index].preview_path
    if preview_path and Path(preview_path).is_file():
        return [discord.File(preview_path, filename=PREVIEW_FILENAME)]

    return []


def build_search_embed(items: list[SearchResultItem], index: int) -> discord.Embed:
    item = items[index]

    embed = discord.Embed(
        title=f"#{index + 1} · {item.similarity:.1%} match",
        url=item.jump_url,
        description=(f"{item.jump_url}\n" f"{item.scene_range}"),
        color=similarity_color(item.similarity),
    )
    embed.set_footer(text=f"Match {index + 1} of {len(items)}")

    if item.preview_path and Path(item.preview_path).is_file():
        embed.set_image(url=f"attachment://{PREVIEW_FILENAME}")

    return embed


class SearchResultsView(discord.ui.View):
    def __init__(self, items: list[SearchResultItem], requester_id: int):
        super().__init__(timeout=300)
        self.items = items
        self.index = 0
        self.requester_id = requester_id

    async def _update(self, interaction: discord.Interaction) -> None:
        if interaction.user.id != self.requester_id:
            await interaction.response.send_message(
                "These buttons aren't for you.",
                ephemeral=True,
            )
            return

        embed = build_search_embed(self.items, self.index)
        files = preview_files(self.items, self.index)

        await interaction.response.edit_message(
            embed=embed,
            attachments=files,
            view=self,
        )

    @discord.ui.button(label="Previous", style=discord.ButtonStyle.secondary)
    async def previous(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        self.index = (self.index - 1) % len(self.items)
        await self._update(interaction)

    @discord.ui.button(label="Next", style=discord.ButtonStyle.primary)
    async def next(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        self.index = (self.index + 1) % len(self.items)
        await self._update(interaction)

    async def on_timeout(self) -> None:
        for child in self.children:
            if isinstance(child, discord.ui.Button):
                child.disabled = True


async def resolve_result_items(
    client: discord.Client,
    results: list[RealDictRow],
) -> list[SearchResultItem]:
    items: list[SearchResultItem] = []

    for result in results:
        channel = client.get_channel(result["channel_id"])

        if not isinstance(channel, discord.TextChannel):
            continue

        try:
            precut_message = await channel.fetch_message(result["message_id"])
        except discord.NotFound:
            continue

        similarity = 1 - result["distance"]
        scene_range = (
            f"{format_time(result['start_time'])} – "
            f"{format_time(result['end_time'])}"
        )

        items.append(
            SearchResultItem(
                similarity=similarity,
                channel_mention=channel.mention,
                scene_range=scene_range,
                jump_url=precut_message.jump_url,
                preview_path=result.get("preview_path"),
            )
        )

    return items


async def similar_embed(
    client: discord.Client,
    results: list[RealDictRow],
    requester_id: int,
) -> tuple[discord.Embed | None, list[discord.File], SearchResultsView | None]:
    items = await resolve_result_items(client, results)

    if not items:
        return None, [], None

    embed = build_search_embed(items, 0)
    files = preview_files(items, 0)
    view = SearchResultsView(items, requester_id) if len(items) > 1 else None

    return embed, files, view
