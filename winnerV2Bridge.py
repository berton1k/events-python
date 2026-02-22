import disnake
from disnake import SeparatorSpacing, ui
from disnake.ext import commands
import re


WINNERS_CHANNEL_ID = channelid
ACCENT_COLOR = disnake.Color(0xD11D68)


def _format_title(title: str) -> str:
    cleaned = (title or "").strip()
    if not cleaned:
        return ""
    if cleaned.startswith("##"):
        return cleaned
    if cleaned.startswith("#"):
        return f"## {cleaned.lstrip('#').strip()}"
    return f"## {cleaned}"


def _format_description(description: str) -> str:
    text = (description or "").strip()
    if not text:
        return ""
    return re.sub(r"(?<!\*)#(\d+)(?!\*)", r"**#\1**", text)


def _has_container_components(message: disnake.Message) -> bool:
    try:
        for component in message.components:
            if getattr(component, "type", None) == disnake.ComponentType.container:
                return True
    except Exception:
        return False
    return False


class WinnerV2Bridge(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_message(self, message: disnake.Message):
        if not message.guild:
            return

        if message.channel.id != WINNERS_CHANNEL_ID:
            return

        if _has_container_components(message):
            return

        if not message.embeds:
            return

        embed = message.embeds[0]
        title = _format_title(embed.title or "")
        description = _format_description(embed.description or "")
        image_url = None
        if embed.image:
            image_url = getattr(embed.image, "url", None)
        footer_text = ""
        if embed.footer:
            footer_text = (getattr(embed.footer, "text", "") or "").strip()
        footer_icon_url = None
        if embed.footer:
            footer_icon_url = getattr(embed.footer, "icon_url", None)
        if not footer_icon_url and message.author:
            footer_icon_url = message.author.display_avatar.url

        if not any([title, description, image_url, footer_text]):
            return

        components = []
        if title:
            components.append(ui.TextDisplay(title))

        if description:
            if components:
                components.append(ui.Separator(divider=True, spacing=SeparatorSpacing.small))
            components.append(ui.TextDisplay(description))

        if image_url:
            if components:
                components.append(ui.Separator(divider=True, spacing=SeparatorSpacing.small))
            components.append(ui.MediaGallery(disnake.MediaGalleryItem(media=image_url)))

        if footer_text:
            if components:
                components.append(ui.Separator(divider=True, spacing=SeparatorSpacing.small))
            small_footer = f"-# {footer_text}"
            components.append(ui.TextDisplay(small_footer))

        container = ui.Container(*components, accent_colour=ACCENT_COLOR)

        try:
            await message.edit(content=None, embeds=[], components=[container], attachments=[])
        except disnake.HTTPException:
            return


def setup(bot):
    bot.add_cog(WinnerV2Bridge(bot))
