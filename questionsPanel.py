import json
import os

import disnake
from disnake import SeparatorSpacing, ui
from disnake.ext import commands


ACCENT_COLOR = disnake.Color(0xD11D68)
QUESTIONS_THREAD_ID = channelid
QUESTIONS_ROLE_IDS = [
    roleid,
    roleid,
    roleid,
    roleid,
]
ANSWER_ALLOWED_ROLE_IDS = {
    roleid,
    roleid,
    roleid,
    roleid,
    roleid,
}
ANSWER_ALLOWED_USER_ID = userid

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CAT1_PATH = os.path.join(BASE_DIR, "assets", "cat1.jpg")
CAT10_PATH = os.path.join(BASE_DIR, "assets", "cat10.jpg")
CHRISTMAS_PATH = os.path.join(BASE_DIR, "assets", "christmas.jpg")

QUESTIONS_STATE_FILE = "data/questions_state.json"
QUESTIONS_STATE: dict[str, dict] = {}


def _load_questions_state() -> None:
    global QUESTIONS_STATE
    if os.path.exists(QUESTIONS_STATE_FILE):
        try:
            with open(QUESTIONS_STATE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    QUESTIONS_STATE = data
        except Exception:
            QUESTIONS_STATE = {}


def _save_questions_state() -> None:
    os.makedirs("data", exist_ok=True)
    with open(QUESTIONS_STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(QUESTIONS_STATE, f, ensure_ascii=False, indent=2)


def _get_channel_or_thread(guild: disnake.Guild, channel_id: int):
    getter = getattr(guild, "get_channel_or_thread", None)
    if callable(getter):
        channel = getter(channel_id)
        if channel is not None:
            return channel
    return guild.get_channel(channel_id)


async def _resolve_channel_or_thread(bot: commands.Bot, guild: disnake.Guild, channel_id: int):
    channel = _get_channel_or_thread(guild, channel_id)
    if channel is not None:
        return channel
    try:
        return await bot.fetch_channel(channel_id)
    except disnake.HTTPException:
        return None


async def _prepare_target_channel(channel) -> bool:
    if isinstance(channel, disnake.Thread):
        if channel.archived:
            try:
                await channel.edit(archived=False)
            except disnake.HTTPException:
                return False
        try:
            await channel.join()
        except disnake.HTTPException:
            return False
    return True


def _roles_mention_text() -> str:
    return " ".join(f"<@&{role_id}>" for role_id in QUESTIONS_ROLE_IDS)


def _extract_question_text(message: disnake.Message) -> str:
    stored = QUESTIONS_STATE.get(str(message.id), {})
    if stored.get("question"):
        return stored["question"]

    for component in message.components:
        if getattr(component, "type", None) == disnake.ComponentType.container:
            children = getattr(component, "children", []) or []
            if len(children) >= 2:
                second = children[1]
                text = getattr(second, "content", None) or getattr(second, "text", None)
                if isinstance(text, str) and text.strip():
                    return text.strip()
    return "—"


def _extract_image_url(message: disnake.Message) -> str | None:
    if message.attachments:
        return message.attachments[0].url
    return None


class AskQuestionModal(disnake.ui.Modal):
    def __init__(self, author: disnake.Member):
        self.author = author
        components = [
            disnake.ui.TextInput(
                label="Ваш вопрос",
                placeholder="Введите вопрос для старшего состава",
                custom_id="question_text",
                style=disnake.TextInputStyle.paragraph,
                max_length=1000,
            )
        ]
        super().__init__(title="Задать вопрос", components=components)

    async def callback(self, inter: disnake.ModalInteraction):
        await inter.response.defer(ephemeral=True)

        question_text = (inter.text_values.get("question_text") or "").strip()
        if not question_text:
            await inter.edit_original_response("❌ Вопрос не может быть пустым.")
            return

        if inter.guild is None:
            await inter.edit_original_response("❌ Команда доступна только на сервере.")
            return

        thread = await _resolve_channel_or_thread(inter.bot, inter.guild, QUESTIONS_THREAD_ID)
        if thread is None:
            await inter.edit_original_response("❌ Ветка для вопросов не найдена.")
            return

        prepared = await _prepare_target_channel(thread)
        if not prepared:
            await inter.edit_original_response("❌ Не удалось получить доступ к ветке для вопросов.")
            return

        file = None
        if os.path.exists(CAT10_PATH):
            file = disnake.File(CAT10_PATH, filename="cat10.jpg")

        components = [
            ui.TextDisplay(f"Новый вопрос от {self.author.mention}"),
            ui.Separator(divider=True, spacing=SeparatorSpacing.small),
            ui.TextDisplay(question_text),
        ]

        if file:
            components.append(ui.Separator(divider=True, spacing=SeparatorSpacing.small))
            components.append(ui.MediaGallery(disnake.MediaGalleryItem(media="attachment://cat10.jpg")))

        components.append(ui.Separator(divider=True, spacing=SeparatorSpacing.small))
        components.append(ui.TextDisplay(_roles_mention_text()))

        container = ui.Container(*components, accent_colour=ACCENT_COLOR)
        actions = ui.ActionRow(
            disnake.ui.Button(
                label="Дать ответ",
                style=disnake.ButtonStyle.success,
                custom_id=f"questions_answer:{self.author.id}",
            )
        )

        try:
            if file:
                sent = await thread.send(
                    components=[container, actions],
                    file=file,
                    allowed_mentions=disnake.AllowedMentions(roles=True, users=True),
                )
            else:
                sent = await thread.send(
                    components=[container, actions],
                    allowed_mentions=disnake.AllowedMentions(roles=True, users=True),
                )
        except disnake.HTTPException:
            await inter.edit_original_response("❌ Не удалось отправить вопрос в ветку.")
            return

        QUESTIONS_STATE[str(sent.id)] = {
            "asker_id": self.author.id,
            "question": question_text,
        }
        _save_questions_state()

        await inter.edit_original_response("✅ Вопрос отправлен старшему составу.")


class AnswerQuestionModal(disnake.ui.Modal):
    def __init__(self, asker_id: int, question_text: str, source_message_id: int, source_channel_id: int):
        self.asker_id = asker_id
        self.question_text = question_text
        self.source_message_id = source_message_id
        self.source_channel_id = source_channel_id

        components = [
            disnake.ui.TextInput(
                label="Ответ",
                placeholder="Введите ответ на вопрос",
                custom_id="answer_text",
                style=disnake.TextInputStyle.paragraph,
                max_length=1000,
            )
        ]
        super().__init__(title="Дать ответ", components=components)

    async def callback(self, inter: disnake.ModalInteraction):
        await inter.response.defer(ephemeral=True)

        answer_text = (inter.text_values.get("answer_text") or "").strip()
        if not answer_text:
            await inter.edit_original_response("❌ Ответ не может быть пустым.")
            return

        if inter.guild is None:
            await inter.edit_original_response("❌ Ответ можно дать только на сервере.")
            return

        source_channel = await _resolve_channel_or_thread(inter.bot, inter.guild, self.source_channel_id)
        if source_channel is None:
            await inter.edit_original_response("❌ Не найден канал/ветка с вопросом.")
            return

        prepared = await _prepare_target_channel(source_channel)
        if not prepared:
            await inter.edit_original_response("❌ Не удалось открыть ветку с вопросом.")
            return

        try:
            source_message = await source_channel.fetch_message(self.source_message_id)
        except disnake.HTTPException:
            await inter.edit_original_response("❌ Сообщение с вопросом не найдено.")
            return

        image_url = _extract_image_url(source_message)
        components = [
            ui.TextDisplay(
                f"Вопрос от <@{self.asker_id}> отвечен {inter.author.mention}"
            ),
            ui.Separator(divider=True, spacing=SeparatorSpacing.small),
            ui.TextDisplay(self.question_text or "—"),
        ]
        if image_url:
            components.append(ui.Separator(divider=True, spacing=SeparatorSpacing.small))
            components.append(ui.MediaGallery(disnake.MediaGalleryItem(media=image_url)))
        components.append(ui.Separator(divider=True, spacing=SeparatorSpacing.small))
        components.append(ui.TextDisplay(answer_text))

        updated_container = ui.Container(*components, accent_colour=ACCENT_COLOR)

        try:
            await source_message.edit(
                components=[updated_container],
                allowed_mentions=disnake.AllowedMentions(users=True),
            )
        except disnake.HTTPException:
            await inter.edit_original_response("❌ Не удалось обновить сообщение в ветке.")
            return

        member = inter.guild.get_member(self.asker_id)
        user = member or inter.bot.get_user(self.asker_id)
        if user is None:
            try:
                user = await inter.bot.fetch_user(self.asker_id)
            except disnake.HTTPException:
                user = None

        dm_sent = False
        if user is not None:
            dm_file = None
            if os.path.exists(CHRISTMAS_PATH):
                dm_file = disnake.File(CHRISTMAS_PATH, filename="christmas.jpg")

            dm_components = [
                ui.TextDisplay(self.question_text or "—"),
                ui.Separator(divider=True, spacing=SeparatorSpacing.small),
                ui.TextDisplay(answer_text),
                ui.Separator(divider=True, spacing=SeparatorSpacing.small),
                ui.TextDisplay(f"{inter.author.mention} — {inter.author}"),
            ]
            if dm_file:
                dm_components.append(ui.Separator(divider=True, spacing=SeparatorSpacing.small))
                dm_components.append(ui.MediaGallery(disnake.MediaGalleryItem(media="attachment://christmas.jpg")))

            dm_container = ui.Container(*dm_components, accent_colour=ACCENT_COLOR)

            try:
                if dm_file:
                    await user.send(components=[dm_container], file=dm_file)
                else:
                    await user.send(components=[dm_container])
                dm_sent = True
            except disnake.Forbidden:
                dm_sent = False
            except disnake.HTTPException:
                dm_sent = False

        QUESTIONS_STATE.pop(str(self.source_message_id), None)
        _save_questions_state()

        if dm_sent:
            await inter.edit_original_response("✅ Ответ отправлен. Кнопка удалена, пользователь уведомлен в ЛС.")
        else:
            await inter.edit_original_response("✅ Ответ отправлен. Кнопка удалена, но ЛС пользователю отправить не удалось.")


class QuestionsPanel(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        _load_questions_state()

    @commands.Cog.listener()
    async def on_button_click(self, inter: disnake.MessageInteraction):
        if inter.response.is_done():
            return

        custom_id = getattr(inter.component, "custom_id", "")
        if custom_id == "questions_ask":
            try:
                await inter.response.send_modal(AskQuestionModal(inter.author))
            except disnake.NotFound:
                return
            except disnake.HTTPException:
                return
            return

        if custom_id.startswith("questions_answer:"):
            member = inter.author if isinstance(inter.author, disnake.Member) else None
            has_allowed_role = False
            if member is not None:
                has_allowed_role = any(role.id in ANSWER_ALLOWED_ROLE_IDS for role in member.roles)

            if inter.author.id != ANSWER_ALLOWED_USER_ID and not has_allowed_role:
                await inter.response.send_message("❌ У вас нет доступа к этой кнопке.", ephemeral=True)
                return

            parts = custom_id.split(":", 1)
            if len(parts) != 2 or not parts[1].isdigit():
                await inter.response.send_message("❌ Некорректный идентификатор вопроса.", ephemeral=True)
                return

            asker_id = int(parts[1])
            question_text = _extract_question_text(inter.message)

            state_item = QUESTIONS_STATE.get(str(inter.message.id), {})
            if state_item.get("asker_id"):
                asker_id = int(state_item["asker_id"])
            if state_item.get("question"):
                question_text = state_item["question"]

            try:
                await inter.response.send_modal(
                    AnswerQuestionModal(
                        asker_id=asker_id,
                        question_text=question_text,
                        source_message_id=inter.message.id,
                        source_channel_id=inter.channel.id,
                    )
                )
            except disnake.NotFound:
                return
            except disnake.HTTPException:
                return

    @commands.command(name="questions")
    async def questions(self, ctx: commands.Context, channel_id: str = None):
        if channel_id is None:
            await ctx.send("❌ Укажите ID канала. Использование: .questions <channel_id>")
            return

        if ctx.guild is None:
            await ctx.send("❌ Команда доступна только на сервере.")
            return

        try:
            cid = int(channel_id)
        except ValueError:
            await ctx.send("❌ Неверный ID канала.")
            return

        channel = await _resolve_channel_or_thread(self.bot, ctx.guild, cid)
        if channel is None:
            await ctx.send("❌ Канал не найден.")
            return

        prepared = await _prepare_target_channel(channel)
        if not prepared:
            await ctx.send("❌ Не удалось получить доступ к указанному каналу.")
            return

        file = None
        if os.path.exists(CAT1_PATH):
            file = disnake.File(CAT1_PATH, filename="cat1.jpg")

        components = [
            ui.TextDisplay(
                "Привет! Здесь ты можешь задать свой вопрос старшему составу и получить на него ответ"
            ),
        ]
        if file:
            components.append(ui.Separator(divider=True, spacing=SeparatorSpacing.small))
            components.append(ui.MediaGallery(disnake.MediaGalleryItem(media="attachment://cat1.jpg")))

        container = ui.Container(*components, accent_colour=ACCENT_COLOR)
        actions = ui.ActionRow(
            disnake.ui.Button(
                label="Задать вопрос",
                style=disnake.ButtonStyle.success,
                custom_id="questions_ask",
            )
        )

        try:
            if file:
                await channel.send(components=[container, actions], file=file)
            else:
                await channel.send(components=[container, actions])
            await ctx.send("✅ Панель вопросов отправлена.")
        except disnake.Forbidden:
            await ctx.send("❌ Нет прав на отправку в указанный канал.")
        except disnake.HTTPException:
            await ctx.send("❌ Не удалось отправить панель вопросов.")


def setup(bot):
    bot.add_cog(QuestionsPanel(bot))
