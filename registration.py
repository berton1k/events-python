import disnake
from disnake.ext import commands
from disnake import ui, SeparatorSpacing
import json
import os

with open("config.json", "r", encoding="utf-8") as f:
    cfg = json.load(f)

REGS = cfg.get("registrations", {})
SUBMIT_CHANNEL = cfg.get("registration_submission_channel", channelid)
NOTIFY_ID = cfg.get("registration_notify_id", roleid)


def _build_registration_container(mode_key: str, extra_texts: list[str], image_path: str | None, mention: str | None = None):
    components = []
    # First component: mode title
    title = REGS.get(mode_key, {}).get("label", mode_key)
    components.append(ui.TextDisplay(f"**Режим:** {title}"))
    components.append(ui.Separator(divider=True, spacing=SeparatorSpacing.small))

    # Next three text components
    for text in extra_texts:
        components.append(ui.TextDisplay(text))
        components.append(ui.Separator(divider=True, spacing=SeparatorSpacing.small))

    # Image component
    if image_path and os.path.exists(image_path):
        components.append(
            ui.MediaGallery(
                disnake.MediaGalleryItem(media=f"attachment://{os.path.basename(image_path)}")
            )
        )
        components.append(ui.Separator(divider=True, spacing=SeparatorSpacing.small))

    # Optional small mention at the end
    if mention:
        components.append(ui.TextDisplay(mention))

    container = ui.Container(*components, accent_colour=disnake.Color(0xD11D68))
    return container


class RegistrationModal(disnake.ui.Modal):
    def __init__(self, mode_key: str, author: disnake.Member):
        self.mode_key = mode_key
        self.author = author
        title = REGS.get(mode_key, {}).get("label", mode_key)
        components = [
            disnake.ui.TextInput(label="Фракция", placeholder="Ваша фракция", custom_id="faction", max_length=100),
            disnake.ui.TextInput(label="Количество людей", placeholder="Число участников", custom_id="count", max_length=10),
        ]
        super().__init__(title=f"Регистрация — {title}", components=components)

    async def callback(self, inter: disnake.ModalInteraction):
        faction = inter.text_values.get("faction") or "—"
        count = inter.text_values.get("count") or "—"

        image = REGS.get(self.mode_key, {}).get("image")
        file = None
        if image and os.path.exists(image):
            file = disnake.File(image, filename=os.path.basename(image))

        # Build container: first component — режим, then details, then mention at bottom
        extra_texts = [
            f"Автор: {self.author.mention}",
            f"Фракция: {faction}",
            f"Участников: {count}",
        ]

        container = _build_registration_container(self.mode_key, extra_texts, image, mention=f"<@{NOTIFY_ID}>")

        channel = inter.bot.get_channel(SUBMIT_CHANNEL)
        if channel is None:
            await inter.response.send_message("❌ Канал для заявок не найден.", ephemeral=True)
            return

        try:
            if file:
                await channel.send(components=[container], file=file)
            else:
                await channel.send(components=[container])
            await inter.response.send_message("✅ Регистрация отправлена.", ephemeral=True)
        except disnake.Forbidden:
            await inter.response.send_message("❌ Нет прав на отправку в канал заявок.", ephemeral=True)
        except Exception as e:
            await inter.response.send_message(f"❌ Ошибка: {e}", ephemeral=True)


class RegisterView(disnake.ui.View):
    def __init__(self, mode_key: str):
        super().__init__(timeout=None)
        self.mode_key = mode_key

    @disnake.ui.button(label="Регистрация", style=disnake.ButtonStyle.primary, custom_id="register_button")
    async def register_button(self, button: disnake.Button, inter: disnake.MessageInteraction):
        try:
            await inter.response.send_modal(RegistrationModal(self.mode_key, inter.author))
        except (disnake.NotFound, disnake.HTTPException) as e:
            # Interaction may be expired or invalid; inform user with ephemeral message
            try:
                await inter.response.send_message("❌ Не удалось открыть форму — попробуйте снова.", ephemeral=True)
            except Exception:
                # last-resort fallback
                try:
                    await inter.followup.send("❌ Не удалось открыть форму — попробуйте снова.", ephemeral=True)
                except Exception:
                    pass


class RegistrationCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def _send_panel(self, ctx: commands.Context, mode_key: str, channel_id: str):
        # validate channel id
        try:
            cid = int(channel_id)
        except ValueError:
            await ctx.send("❌ Неверный ID канала.")
            return

        channel = ctx.bot.get_channel(cid)
        if channel is None:
            await ctx.send("❌ Канал не найден.")
            return

        # prepare texts for components (three texts)
        label = REGS.get(mode_key, {}).get("label", mode_key)
        text1 = f"Регистрация на режим: {label}"
        text2 = "Правила участия: Участник должен быть в голосовом канале на момент старта и иметь действительную роль."
        text3 = "Информация: Используйте кнопку ниже, чтобы зарегистрировать фракцию и указать количество участников."

        image = REGS.get(mode_key, {}).get("image")

        # build container with small mention at end
        extra_texts = [text1, text2, text3]
        container = _build_registration_container(mode_key, extra_texts, image, mention=None)

        try:
            if image and os.path.exists(image):
                file = disnake.File(image, filename=os.path.basename(image))
                await channel.send(components=[container], file=file)
            else:
                await channel.send(components=[container])

            # send button separately
            await channel.send(view=RegisterView(mode_key))
        except disnake.Forbidden:
            await ctx.send("❌ Нет прав для отправки в указанный канал.")
        except Exception as e:
            await ctx.send(f"❌ Ошибка при отправке: {e}")

    @commands.command(name="regp")
    async def regp(self, ctx: commands.Context, channel_id: str = None):
        if channel_id is None:
            await ctx.send("❌ Укажите ID канала. Использование: .regp <channel_id>")
            return
        await self._send_panel(ctx, "regp", channel_id)

    @commands.command(name="regs")
    async def regs(self, ctx: commands.Context, channel_id: str = None):
        if channel_id is None:
            await ctx.send("❌ Укажите ID канала. Использование: .regs <channel_id>")
            return
        await self._send_panel(ctx, "regs", channel_id)

    @commands.command(name="regh")
    async def regh(self, ctx: commands.Context, channel_id: str = None):
        if channel_id is None:
            await ctx.send("❌ Укажите ID канала. Использование: .regh <channel_id>")
            return
        await self._send_panel(ctx, "regh", channel_id)

    @commands.command(name="regz")
    async def regz(self, ctx: commands.Context, channel_id: str = None):
        if channel_id is None:
            await ctx.send("❌ Укажите ID канала. Использование: .regz <channel_id>")
            return
        await self._send_panel(ctx, "regz", channel_id)

    @commands.command(name="regf")
    async def regf(self, ctx: commands.Context, channel_id: str = None):
        if channel_id is None:
            await ctx.send("❌ Укажите ID канала. Использование: .regf <channel_id>")
            return
        await self._send_panel(ctx, "regf", channel_id)

    @commands.command(name="regk")
    async def regk(self, ctx: commands.Context, channel_id: str = None):
        if channel_id is None:
            await ctx.send("❌ Укажите ID канала. Использование: .regk <channel_id>")
            return
        await self._send_panel(ctx, "regk", channel_id)


def setup(bot):
    bot.add_cog(RegistrationCog(bot))
