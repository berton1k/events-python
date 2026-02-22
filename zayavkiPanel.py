import disnake
from disnake.ext import commands, tasks
from disnake import ui, SeparatorSpacing
import json
import os
import sqlite3
import re
from datetime import datetime

with open("config.json", "r", encoding="utf-8") as f:
    config = json.load(f)

# Канал для логов заявок (как у тебя в конфиге)
EVENT_HELPER_LOG_CHANNEL = channelid
PUBLISH_CHANNEL_ID = channelid
LIST_CHANNEL_ID = channelid

# Картинка ТОЛЬКО для панели .zayavki (не для логов)
IMAGE_PATH = "assets/das.png"

# ID пользователя, который может использовать .zayavki
ALLOWED_USER_ID = userid
ZAYAVKI_ALLOWED_USER_IDS = {
    userid,
    userid,
}

# Optional mention added to the log embed
EVENT_HELPER_NOTIFY_MENTION = "<@roleid>"

# Lock state for helper applications
HELPER_LOCK_FILE = "data/helper_lock.json"
ZAYAVKI_DB_FILE = "data/zayavki.sqlite"
PYTHON_ACCESS_FILE = "data/python_command_access.json"


def _load_helper_lock() -> bool:
    """Return True if applications are locked."""
    if os.path.exists(HELPER_LOCK_FILE):
        try:
            with open(HELPER_LOCK_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                return bool(data.get("locked", False))
        except Exception:
            return False
    return False


def _get_channel_or_thread(guild: disnake.Guild | None, channel_id: int) -> disnake.abc.GuildChannel | disnake.Thread | None:
    if guild is None:
        return None
    getter = getattr(guild, "get_channel_or_thread", None)
    if callable(getter):
        return getter(channel_id)
    return guild.get_channel(channel_id)


def _save_helper_lock(locked: bool) -> None:
    os.makedirs("data", exist_ok=True)
    with open(HELPER_LOCK_FILE, "w", encoding="utf-8") as f:
        json.dump({"locked": locked}, f, ensure_ascii=False, indent=2)


def _get_db_connection() -> sqlite3.Connection:
    os.makedirs("data", exist_ok=True)
    conn = sqlite3.connect(ZAYAVKI_DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn


def _init_db() -> None:
    conn = _get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS accepted_queue (
            user_id TEXT PRIMARY KEY
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS accepted_history (
            date_key TEXT NOT NULL,
            user_id TEXT NOT NULL
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS publish_queue (
            user_id TEXT PRIMARY KEY
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS publish_history (
            date_key TEXT NOT NULL,
            user_id TEXT NOT NULL
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS action_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL,
            actor_id TEXT NOT NULL,
            action TEXT NOT NULL,
            details TEXT
        )
        """
    )
    conn.commit()
    conn.close()


def _date_key(value: datetime | None = None) -> str:
    dt = value or datetime.now()
    return dt.strftime("%d.%m.%Y")


def _set_setting(key: str, value: str) -> None:
    conn = _get_db_connection()
    cursor = conn.cursor()
    cursor.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, value))
    conn.commit()
    conn.close()


def _get_setting(key: str) -> str | None:
    conn = _get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT value FROM settings WHERE key = ?", (key,))
    row = cursor.fetchone()
    conn.close()
    return row["value"] if row else None


def _add_to_table(table: str, user_id: int) -> None:
    conn = _get_db_connection()
    cursor = conn.cursor()
    cursor.execute(f"INSERT OR IGNORE INTO {table} (user_id) VALUES (?)", (str(user_id),))
    conn.commit()
    conn.close()


def _remove_from_table(table: str, user_id: int) -> None:
    conn = _get_db_connection()
    cursor = conn.cursor()
    cursor.execute(f"DELETE FROM {table} WHERE user_id = ?", (str(user_id),))
    conn.commit()
    conn.close()


def _list_table(table: str) -> list[str]:
    conn = _get_db_connection()
    cursor = conn.cursor()
    cursor.execute(f"SELECT user_id FROM {table} ORDER BY rowid ASC")
    rows = cursor.fetchall()
    conn.close()
    return [row["user_id"] for row in rows]


def _add_history(table: str, date_key: str, user_id: int) -> None:
    conn = _get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        f"INSERT INTO {table} (date_key, user_id) VALUES (?, ?)",
        (date_key, str(user_id))
    )
    conn.commit()
    conn.close()


def _get_history(table: str, date_key: str) -> list[str]:
    conn = _get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        f"SELECT user_id FROM {table} WHERE date_key = ? ORDER BY rowid ASC",
        (date_key,)
    )
    rows = cursor.fetchall()
    conn.close()
    return [row["user_id"] for row in rows]


def _parse_date(value: str) -> str | None:
    try:
        parsed = datetime.strptime(value.strip(), "%d.%m.%Y")
        return parsed.strftime("%d.%m.%Y")
    except ValueError:
        return None


def _parse_datetime(date_value: str, time_value: str) -> int | None:
    try:
        parsed = datetime.strptime(f"{date_value.strip()} {time_value.strip()}", "%d.%m.%Y %H:%M")
        return int(parsed.timestamp())
    except ValueError:
        return None


def _get_modal_value(inter: disnake.ModalInteraction, key: str, fallback_index: int) -> str:
    """
    Безопасно достаем значение из inter.text_values.
    Если вдруг key отсутствует (KeyError q1), берем по индексу из values().
    """
    if key in inter.text_values:
        return inter.text_values.get(key) or "—"

    values = list(inter.text_values.values())
    if 0 <= fallback_index < len(values):
        return values[fallback_index] or "—"

    return "—"


def _load_python_access() -> dict:
    default_data = {
        "users": [str(ALLOWED_USER_ID)],
        "roles": [],
        "allow_admin_roles": False,
    }
    if os.path.exists(PYTHON_ACCESS_FILE):
        try:
            with open(PYTHON_ACCESS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            users = [str(x) for x in data.get("users", []) if str(x).isdigit()]
            roles = [str(x) for x in data.get("roles", []) if str(x).isdigit()]
            allow_admin_roles = bool(data.get("allow_admin_roles", False))
            if str(ALLOWED_USER_ID) not in users:
                users.append(str(ALLOWED_USER_ID))
            return {
                "users": sorted(set(users)),
                "roles": sorted(set(roles)),
                "allow_admin_roles": allow_admin_roles,
            }
        except Exception:
            return default_data
    return default_data


def _has_dynamic_access(member: disnake.Member | None) -> bool:
    if member is None:
        return False
    access = _load_python_access()
    if str(member.id) in access["users"]:
        return True
    member_role_ids = {str(role.id) for role in member.roles}
    if member_role_ids.intersection(access["roles"]):
        return True
    if access.get("allow_admin_roles", False) and member.guild_permissions.administrator:
        return True
    return False


def _has_zayavki_access(author: disnake.abc.User, guild: disnake.Guild | None) -> bool:
    if author.id in ZAYAVKI_ALLOWED_USER_IDS:
        return True
    if guild is None or not isinstance(author, disnake.Member):
        return False
    return _has_dynamic_access(author)


async def _log_zayavki_action(
    guild: disnake.Guild | None,
    actor: disnake.abc.User,
    action: str,
    details: str | None = None,
) -> None:
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn = _get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "INSERT INTO action_logs (created_at, actor_id, action, details) VALUES (?, ?, ?, ?)",
            (now, str(actor.id), action, details),
        )
        conn.commit()
    finally:
        conn.close()


class ZayavkiModal(disnake.ui.Modal):
    def __init__(self, author: disnake.Member):
        self.author = author

        # ВАЖНО: label <= 45 символов. Полные формулировки держим в placeholder.
        components = [
            disnake.ui.TextInput(
                label="Как тебя зовут и сколько тебе лет?",
                placeholder="Дмитрий, 18",
                custom_id="q1",
                max_length=100,
            ),
            disnake.ui.TextInput(
                label="Твой  игровой никнейм и статик id",
                placeholder="Shinigami Miami 24606",
                custom_id="q2",
                max_length=100,
            ),
            disnake.ui.TextInput(
                label="Онлайн и время игры",
                placeholder="5+ 15:00-20:00",
                custom_id="q3",
                max_length=100,
            ),
            disnake.ui.TextInput(
                label="Идея нового мероприятия",
                placeholder="Развернуто напишите свою идею одного нового мероприятия",
                custom_id="q4",
                style=disnake.TextInputStyle.paragraph,
                max_length=1000,
            ),
            disnake.ui.TextInput(
                label="Почему именно ты?",
                placeholder="Почему именно ты должнен занять пост Event Helper?",
                custom_id="q5",
                style=disnake.TextInputStyle.paragraph,
                max_length=1000,
            ),
        ]

        super().__init__(
            title="Заявка на Event Helper",
            components=components,
        )

    async def callback(self, inter: disnake.ModalInteraction):
        channel = inter.bot.get_channel(EVENT_HELPER_LOG_CHANNEL)
        if channel is None:
            await inter.response.send_message("❌ Канал логов не найден.", ephemeral=True)
            return

        q1 = _get_modal_value(inter, "q1", 0)
        q2 = _get_modal_value(inter, "q2", 1)
        q3 = _get_modal_value(inter, "q3", 2)
        q4 = _get_modal_value(inter, "q4", 3)
        q5 = _get_modal_value(inter, "q5", 4)

        embed = disnake.Embed(
            title="📋 Заявка на Event Helper",
            color=0x1F6F5C
        )

        embed.add_field(name="От:", value=self.author.mention, inline=False)
        embed.add_field(name="Имя и возраст", value=q1, inline=False)
        embed.add_field(name="Никнейм и статик id", value=q2, inline=False)
        embed.add_field(name="Онлайн", value=q3, inline=False)
        embed.add_field(name="Идея МП", value=q4, inline=False)
        embed.add_field(name="Почему именно вы?", value=q5, inline=False)

        # В ЛОГИ КАРТИНКУ НЕ КИДАЕМ (как ты просил)
        embed.set_footer(text=f"Applicant ID: {self.author.id}")

        view = ApplicationActionView(applicant_id=self.author.id)
        if EVENT_HELPER_NOTIFY_MENTION:
            await channel.send(content=EVENT_HELPER_NOTIFY_MENTION, embed=embed, view=view)
        else:
            await channel.send(embed=embed, view=view)

        await inter.response.send_message("✅ Заявка отправлена!", ephemeral=True)


class ZayavkiView(disnake.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @disnake.ui.button(
        label="📋 Подать заявку",
    style=disnake.ButtonStyle.success,
 custom_id="zayavki_apply_button"
    )
    async def apply(self, button: disnake.ui.Button, inter: disnake.MessageInteraction):
        if _load_helper_lock():
            await inter.response.send_message("❌ Заявки закрыты.", ephemeral=True)
            return
        await inter.response.send_modal(ZayavkiModal(inter.author))


class ZayavkiPanel(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        if not self._panel_refresh.is_running():
            self._panel_refresh.start()

    @tasks.loop(seconds=60)
    async def _panel_refresh(self):
        for guild in self.bot.guilds:
            await _update_accepted_panel(guild)
            await _update_publish_panel(guild)

    @_panel_refresh.before_loop
    async def _before_panel_refresh(self):
        await self.bot.wait_until_ready()

    async def cog_check(self, ctx: commands.Context) -> bool:
        if ctx.guild is None:
            return False
        return _has_zayavki_access(ctx.author, ctx.guild)

    @commands.Cog.listener()
    async def on_button_click(self, inter: disnake.MessageInteraction):
        if inter.response.is_done():
            return
        custom_id = getattr(inter.component, "custom_id", "")
        protected_buttons = {
            "accepted_publish",
            "accepted_remove",
            "publish_add",
            "publish_remove",
            "publish_send",
        }

        if custom_id in protected_buttons and inter.author.id not in ZAYAVKI_ALLOWED_USER_IDS:
            await inter.response.send_message("❌ У вас нет доступа к этой кнопке.", ephemeral=True)
            await _log_zayavki_action(inter.guild, inter.author, "Попытка доступа к кнопке без прав", custom_id)
            return

        action_match = re.fullmatch(r"zayavki_(approve|decline)_(\d+)", custom_id or "")
        if action_match:
            action, applicant_id_raw = action_match.groups()
            if inter.author.id not in ZAYAVKI_ALLOWED_USER_IDS:
                await inter.response.send_message("❌ У вас нет доступа к этой кнопке.", ephemeral=True)
                await _log_zayavki_action(
                    inter.guild,
                    inter.author,
                    "Попытка обработки заявки без прав",
                    f"zayavki_{action}_{applicant_id_raw}",
                )
                return
            await _process_application_action(
                inter=inter,
                applicant_id=int(applicant_id_raw),
                approved=(action == "approve"),
            )
            return
        if custom_id == "accepted_publish":
            await _log_zayavki_action(inter.guild, inter.author, "Нажал кнопку Опубликовать", "show-accepted")
            await inter.response.send_modal(PublishInterviewModal())
            return
        if custom_id == "accepted_remove":
            await _log_zayavki_action(inter.guild, inter.author, "Нажал кнопку Удалить", "show-accepted")
            await inter.response.send_modal(
                AcceptedManageModal(panel_message_id=inter.message.id, panel_channel_id=inter.channel.id)
            )
            return
        if custom_id == "publish_add":
            await _log_zayavki_action(inter.guild, inter.author, "Нажал кнопку Добавить", "show-publish")
            await inter.response.send_modal(
                PublishManageModal(mode="add", panel_message_id=inter.message.id, panel_channel_id=inter.channel.id)
            )
            return
        if custom_id == "publish_remove":
            await _log_zayavki_action(inter.guild, inter.author, "Нажал кнопку Удалить", "show-publish")
            await inter.response.send_modal(
                PublishManageModal(mode="remove", panel_message_id=inter.message.id, panel_channel_id=inter.channel.id)
            )
            return
        if custom_id == "publish_send":
            await inter.response.defer(ephemeral=True)
            user_ids = _list_table("publish_queue")
            if not user_ids:
                await inter.edit_original_response("❌ Нет принятых участников.")
                await _log_zayavki_action(inter.guild, inter.author, "Нажал кнопку Опубликовать", "show-publish: список пуст")
                return

            mention_list = _format_mentions(user_ids)
            components = [
                ui.TextDisplay("<a:JABA:1464585875282460703> По результатам обзвона на пост <@&1275588344499277934> подошли следующие кандидаты:"),
                ui.Separator(divider=True, spacing=SeparatorSpacing.small),
                ui.TextDisplay(mention_list),
                ui.Separator(divider=True, spacing=SeparatorSpacing.small),
                ui.TextDisplay("Желаем удачи!\n*Просьба связаться с <@1072166657549676726>/<@438731964313370635> в личных сообщениях discord для дальнейшей информации"),
            ]

            container = ui.Container(*components, accent_colour=disnake.Color(0xD11D68))
            channel = inter.guild.get_channel(PUBLISH_CHANNEL_ID) if inter.guild else None
            if not channel:
                await inter.edit_original_response("❌ Канал для публикации не найден.")
                return

            await channel.send(components=[container])

            date_key = _date_key()
            for user_id in user_ids:
                _add_history("publish_history", date_key, int(user_id))

            conn = _get_db_connection()
            conn.execute("DELETE FROM publish_queue")
            conn.commit()
            conn.close()

            await _clear_list_channel(inter.guild)
            await _edit_panel_message(inter.guild, inter.channel.id, inter.message.id, is_publish=True)
            await _update_publish_panel(inter.guild)
            await inter.edit_original_response("✅ Опубликовано.")
            await _log_zayavki_action(
                inter.guild,
                inter.author,
                "Опубликовал список",
                f"show-publish: опубликовано {len(user_ids)} участник(ов)",
            )

    async def _check_helper_nabor_permission(self, ctx: commands.Context) -> bool:
        """Check if user is admin or has the specific user ID"""
        return _has_zayavki_access(ctx.author, ctx.guild)

    @commands.command(name="helper-lock")
    async def helper_lock(self, ctx: commands.Context):
        if ctx.guild is None:
            await ctx.send("❌ Эту команду можно использовать только на сервере.")
            return
        if not await self._check_helper_nabor_permission(ctx):
            await ctx.send("❌ У вас нет доступа к этой команде.")
            return
        _save_helper_lock(True)
        await ctx.send("🔒 Заявки закрыты.")

    @commands.command(name="helper-unlock")
    async def helper_unlock(self, ctx: commands.Context):
        if ctx.guild is None:
            await ctx.send("❌ Эту команду можно использовать только на сервере.")
            return
        if not await self._check_helper_nabor_permission(ctx):
            await ctx.send("❌ У вас нет доступа к этой команде.")
            return
        _save_helper_lock(False)
        await ctx.send("🔓 Заявки открыты.")

    @commands.command(name="helper-nabor")
    async def helper_nabor(self, ctx: commands.Context, channel_id: str = None):
        if ctx.guild is None:
            await ctx.send("❌ Эту команду можно использовать только на сервере.")
            return
        # Проверка юзера
        if not await self._check_helper_nabor_permission(ctx):
            await ctx.send("❌ У вас нет доступа к этой команде.")
            return

        # Проверка наличия channel_id
        if not channel_id:
            await ctx.send("❌ Ошибка: укажите ID канала. Использование: `.helper-nabor <channel_id>`")
            return

        # Проверка валидности channel_id
        try:
            channel_id_int = int(channel_id)
            channel = ctx.bot.get_channel(channel_id_int)
            if channel is None:
                await ctx.send(f"❌ Ошибка: канал с ID {channel_id} не найден.")
                return
        except ValueError:
            await ctx.send(f"❌ Ошибка: `{channel_id}` не является корректным ID канала.")
            return

        # Component 1: Title
        embed1 = disnake.Embed(
            title="# <a:rolliki:1464585284346839204> Привет! Мы открываем заявки на пост ивент хелпера",
            color=disnake.Color(0x1F6F5C)
        )

        # Component 2: Что ждет вас на посту
        embed2 = disnake.Embed(
            title="**Что ждет Вас на посту?**",
            description="- Приятные поощрения за ваш труд\n- Новый опыт работы с администрацией и игроками\n- Дружелюбный коллектив, который будет помогать вам в сложных ситуациях и проведении мероприятий",
            color=disnake.Color(0x1F6F5C)
        )

        # Component 3: Что требуется от вас
        embed3 = disnake.Embed(
            title="**Что требуется от Вас?**",
            description="- Креативность\n- Желание помогать и развиваться\n- Стрессоустойчивость и адекватность",
            color=disnake.Color(0x1F6F5C)
        )

        # Component 5: Image
        embed5 = disnake.Embed(
            color=disnake.Color(0x1F6F5C)
        )
        file = None
        if os.path.exists(IMAGE_PATH):
            file = disnake.File(IMAGE_PATH, filename="event_helper.png")
            embed5.set_image(url="attachment://event_helper.png")

        # Создаём контейнер со всеми компонентами
        components = [
            ui.TextDisplay(embed1.title or ""),
            ui.Separator(divider=True, spacing=SeparatorSpacing.small),
            ui.TextDisplay(f"**{embed2.title}**\n{embed2.description}"),
            ui.Separator(divider=True, spacing=SeparatorSpacing.small),
            ui.TextDisplay(f"**{embed3.title}**\n{embed3.description}"),
        ]

        # Добавляем фото если существует
        if file:
            components.append(ui.Separator(divider=True, spacing=SeparatorSpacing.small))
            components.append(
                ui.MediaGallery(
                    disnake.MediaGalleryItem(media="attachment://event_helper.png")
                )
            )

        # Добавляем упоминание в конце
        components.append(ui.Separator(divider=True, spacing=SeparatorSpacing.small))
        components.append(ui.TextDisplay("<@&1235673312630145085>"))

        container = ui.Container(
            *components,
            accent_colour=disnake.Color(0xD11D68)
        )

        # Отправляем контейнер и кнопку отдельно
        try:
            # Отправляем контейнер с файлом если он есть
            if file:
                await channel.send(
                    components=[container],
                    file=file
                )
            else:
                await channel.send(
                    components=[container]
                )
            
            # Отправляем кнопку отдельным сообщением
            await channel.send(view=ZayavkiView())
        except disnake.Forbidden:
            await ctx.send("❌ Ошибка: нет прав для отправки сообщений в этот канал.")
        except Exception as e:
            await ctx.send(f"❌ Ошибка при отправке сообщения: {str(e)}")

    @commands.command(name="show-accepted")
    async def show_accepted(self, ctx: commands.Context):
        if ctx.guild is None:
            await ctx.send("❌ Эту команду можно использовать только на сервере.")
            return
        user_ids = _list_table("accepted_queue")
        content = _format_mentions(user_ids)
        components = _accepted_panel_components(content)
        message = await ctx.send(components=components)

        _set_setting("show_accepted_message_id", str(message.id))
        _set_setting("show_accepted_channel_id", str(ctx.channel.id))

    @commands.command(name="get-show")
    async def get_show(self, ctx: commands.Context, date: str = None):
        if not date:
            await ctx.send("❌ Укажите дату в формате 12.02.2026")
            return

        date_key = _parse_date(date)
        if not date_key:
            await ctx.send("❌ Неверный формат даты. Используйте 12.02.2026")
            return

        user_ids = _get_history("accepted_history", date_key)
        content = _format_mentions(user_ids)
        container = ui.Container(ui.TextDisplay(content), accent_colour=disnake.Color(0xD11D68))
        await ctx.send(components=[container])

    @commands.command(name="show-publish")
    async def show_publish(self, ctx: commands.Context):
        if ctx.guild is None:
            await ctx.send("❌ Эту команду можно использовать только на сервере.")
            return
        user_ids = _list_table("publish_queue")
        content = _format_mentions(user_ids, "Нет принятых участников")
        components = _publish_panel_components(content)
        message = await ctx.send(components=components)

        _set_setting("show_publish_message_id", str(message.id))
        _set_setting("show_publish_channel_id", str(ctx.channel.id))

    @commands.command(name="accepted-clear")
    async def accepted_clear(self, ctx: commands.Context):
        if ctx.guild is None:
            await ctx.send("❌ Эту команду можно использовать только на сервере.")
            return
        conn = _get_db_connection()
        conn.execute("DELETE FROM accepted_queue")
        conn.commit()
        conn.close()

        await _update_accepted_panel(ctx.guild)
        await ctx.send("✅ Список одобренных очищен.")

    @commands.command(name="accepted-add")
    async def accepted_add(self, ctx: commands.Context, *user_ids_raw: str):
        if ctx.guild is None:
            await ctx.send("❌ Эту команду можно использовать только на сервере.")
            return

        if not user_ids_raw:
            await ctx.send("❌ Использование: .accepted-add <первый_айди> <второй_айди> ...")
            return

        added_ids: list[str] = []
        invalid_values: list[str] = []

        for raw in user_ids_raw:
            parsed = raw.strip().lstrip("<@!").rstrip(">")
            if not parsed.isdigit():
                invalid_values.append(raw)
                continue
            _add_to_table("accepted_queue", int(parsed))
            added_ids.append(parsed)

        await _update_accepted_panel(ctx.guild)

        if not added_ids:
            await ctx.send("❌ Не удалось добавить ни одного ID.")
            return

        response_text = f"✅ Добавлено в show-accepted: {', '.join(f'<@{uid}>' for uid in added_ids)}"
        if invalid_values:
            response_text += f"\n⚠️ Пропущены некорректные значения: {', '.join(invalid_values)}"

        await ctx.send(response_text)
        await _log_zayavki_action(
            ctx.guild,
            ctx.author,
            "Добавил участников в show-accepted",
            f"Добавлено: {', '.join(added_ids)}",
        )

    @commands.command(name="publish-clear")
    async def publish_clear(self, ctx: commands.Context):
        if ctx.guild is None:
            await ctx.send("❌ Эту команду можно использовать только на сервере.")
            return
        conn = _get_db_connection()
        conn.execute("DELETE FROM publish_queue")
        conn.commit()
        conn.close()

        await _update_publish_panel(ctx.guild)
        await ctx.send("✅ Список для публикации очищен.")

    @commands.command(name="get-publish")
    async def get_publish(self, ctx: commands.Context, date: str = None):
        if not date:
            await ctx.send("❌ Укажите дату в формате 12.02.2026")
            return

        date_key = _parse_date(date)
        if not date_key:
            await ctx.send("❌ Неверный формат даты. Используйте 12.02.2026")
            return

        user_ids = _get_history("publish_history", date_key)
        content = _format_mentions(user_ids)
        container = ui.Container(ui.TextDisplay(content), accent_colour=disnake.Color(0xD11D68))
        await ctx.send(components=[container])

    @commands.command(name="set-show-ids")
    async def set_show_ids(self, ctx: commands.Context, accepted_id: str = None, publish_id: str = None):
        if ctx.guild is None:
            await ctx.send("❌ Эту команду можно использовать только на сервере.")
            return
        if not accepted_id or not publish_id:
            await ctx.send("❌ Использование: .set-show-ids <show-accepted_message_id> <show-publish_message_id>")
            return

        if not accepted_id.isdigit() or not publish_id.isdigit():
            await ctx.send("❌ Укажите корректные числовые ID сообщений.")
            return

        _set_setting("show_accepted_message_id", accepted_id)
        _set_setting("show_accepted_channel_id", str(ctx.channel.id))
        _set_setting("show_publish_message_id", publish_id)
        _set_setting("show_publish_channel_id", str(ctx.channel.id))

        await _update_accepted_panel(ctx.guild)
        await _update_publish_panel(ctx.guild)
        await ctx.send("✅ ID сообщений сохранены и панели обновлены.")


def _format_mentions(user_ids: list[str], empty_text: str = "Нет участников") -> str:
    if not user_ids:
        return empty_text
    lines = []
    for index, user_id in enumerate(user_ids, start=1):
        lines.append(f"{index}. <@{user_id}>")
    return "\n".join(lines)


def _accepted_panel_components(content: str) -> list:
    container = ui.Container(ui.TextDisplay(content), accent_colour=disnake.Color(0xD11D68))
    actions = ui.ActionRow(
        disnake.ui.Button(label="Опубликовать", style=disnake.ButtonStyle.primary, custom_id="accepted_publish"),
        disnake.ui.Button(label="Удалить", style=disnake.ButtonStyle.danger, custom_id="accepted_remove"),
    )
    return [container, actions]


def _publish_panel_components(content: str) -> list:
    container = ui.Container(ui.TextDisplay(content), accent_colour=disnake.Color(0xD11D68))
    actions = ui.ActionRow(
        disnake.ui.Button(label="Добавить", style=disnake.ButtonStyle.success, custom_id="publish_add"),
        disnake.ui.Button(label="Удалить", style=disnake.ButtonStyle.danger, custom_id="publish_remove"),
        disnake.ui.Button(label="Опубликовать", style=disnake.ButtonStyle.primary, custom_id="publish_send"),
    )
    return [container, actions]


def _message_has_container(message: disnake.Message) -> bool:
    try:
        for component in message.components:
            if getattr(component, "type", None) == disnake.ComponentType.container:
                return True
    except Exception:
        return False
    return False


async def _fetch_panel_message(guild: disnake.Guild | None, message_id: str | None, channel_id: str | None) -> disnake.Message | None:
    if guild is None:
        return None

    if not message_id:
        return None

    channels: list[disnake.abc.GuildChannel | disnake.Thread] = []
    if channel_id and channel_id.isdigit():
        stored_channel = _get_channel_or_thread(guild, int(channel_id))
        if stored_channel:
            channels.append(stored_channel)
    list_channel = _get_channel_or_thread(guild, LIST_CHANNEL_ID)
    if list_channel and list_channel not in channels:
        channels.append(list_channel)

    # As a fallback, scan all text channels in the guild.
    for channel in guild.text_channels:
        if channel not in channels:
            channels.append(channel)

    for thread in getattr(guild, "threads", []):
        if thread not in channels:
            channels.append(thread)

    for channel in channels:
        try:
            message = await channel.fetch_message(int(message_id))
            return message
        except disnake.HTTPException:
            continue

    return None


class ApplicationActionView(disnake.ui.View):
    def __init__(self, applicant_id: int):
        super().__init__(timeout=None)
        self.applicant_id = applicant_id

        approve = disnake.ui.Button(label="✅ Одобрить", style=disnake.ButtonStyle.success, custom_id=f"zayavki_approve_{applicant_id}")
        decline = disnake.ui.Button(label="❌ Отклонить", style=disnake.ButtonStyle.danger, custom_id=f"zayavki_decline_{applicant_id}")
        approve.callback = self._approve
        decline.callback = self._decline

        self.add_item(approve)
        self.add_item(decline)

    async def _approve(self, inter: disnake.MessageInteraction):
        await _process_application_action(
            inter=inter,
            applicant_id=self.applicant_id,
            approved=True,
        )

    async def _decline(self, inter: disnake.MessageInteraction):
        await _process_application_action(
            inter=inter,
            applicant_id=self.applicant_id,
            approved=False,
        )


async def _process_application_action(
    inter: disnake.MessageInteraction,
    applicant_id: int,
    *,
    approved: bool,
) -> None:
    if not inter.response.is_done():
        await inter.response.defer()

    if not inter.message or not inter.message.embeds:
        await inter.followup.send("❌ Не удалось обработать заявку: сообщение повреждено.", ephemeral=True)
        return

    embed = inter.message.embeds[0]
    title = (embed.title or "").lower()
    if "одобрена" in title or "отклонена" in title:
        await inter.followup.send("ℹ️ Эта заявка уже обработана.", ephemeral=True)
        return

    updated = embed.copy()
    if approved:
        updated.title = "📋 Заявка на Event Helper одобрена"
        updated.add_field(name="Одобрил", value=inter.author.mention, inline=False)
        _add_to_table("accepted_queue", applicant_id)
        _add_history("accepted_history", _date_key(), applicant_id)
    else:
        updated.title = "📋 Заявка на Event Helper отклонена"
        updated.add_field(name="Отклонил", value=inter.author.mention, inline=False)
        _remove_from_table("accepted_queue", applicant_id)

    try:
        await inter.message.edit(embed=updated, view=None)
    except TypeError:
        await inter.message.edit(embed=updated, components=[])
    except disnake.HTTPException:
        try:
            await inter.message.edit(embed=updated, components=[])
        except disnake.HTTPException:
            pass

    await _update_accepted_panel(inter.guild)

class PublishInterviewModal(disnake.ui.Modal):
    def __init__(self):
        components = [
            disnake.ui.TextInput(
                label="Дата (ДД.ММ.ГГГГ)",
                placeholder="12.02.2026",
                custom_id="publish_date",
                max_length=10,
            ),
            disnake.ui.TextInput(
                label="Время (ЧЧ:ММ)",
                placeholder="19:00",
                custom_id="publish_time",
                max_length=5,
            ),
        ]
        super().__init__(title="Опубликовать обзвон", components=components)

    async def callback(self, inter: disnake.ModalInteraction):
        await inter.response.defer(ephemeral=True)
        date_value = inter.text_values.get("publish_date", "")
        time_value = inter.text_values.get("publish_time", "")
        timestamp = _parse_datetime(date_value, time_value)
        if timestamp is None:
            await inter.edit_original_response("❌ Неверный формат даты или времени.")
            return

        user_ids = _list_table("accepted_queue")
        if not user_ids:
            await inter.edit_original_response("❌ Нет одобренных кандидатов.")
            return

        mention_list = _format_mentions(user_ids)
        time_tag = f"<t:{timestamp}:f>"

        components = [
            ui.TextDisplay("<a:JABA:1464585875282460703>Доброго времени суток! По итогам заявок на обзвон приглашены следующие кандидаты:"),
            ui.Separator(divider=True, spacing=SeparatorSpacing.small),
            ui.TextDisplay(mention_list),
            ui.Separator(divider=True, spacing=SeparatorSpacing.small),
            ui.TextDisplay(
                f"Обзвон состоится {time_tag}, в случае если вы не сможете присутствовать на обзвоне, обратитесь в личные сообщения к <@1072166657549676726>/<@438731964313370635>"
            ),
            ui.Separator(divider=True, spacing=SeparatorSpacing.small),
            ui.TextDisplay("Кандидатам необходимо находится в голосовом канале сервера за 5 минут до начала обзвона."),
        ]

        container = ui.Container(*components, accent_colour=disnake.Color(0xD11D68))
        channel = inter.guild.get_channel(PUBLISH_CHANNEL_ID)
        if not channel:
            await inter.edit_original_response("❌ Канал для публикации не найден.")
            return

        await channel.send(components=[container])
        await inter.edit_original_response("✅ Опубликовано.")
        await _log_zayavki_action(
            inter.guild,
            inter.author,
            "Опубликовал обзвон",
            f"show-accepted: опубликовано {len(user_ids)} участник(ов), дата/время обзвона {date_value} {time_value}",
        )


class PublishManageView(disnake.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @disnake.ui.button(label="Добавить", style=disnake.ButtonStyle.success, custom_id="publish_add")
    async def add_item(self, button: disnake.ui.Button, inter: disnake.MessageInteraction):
        await inter.response.send_modal(PublishManageModal(mode="add"))

    @disnake.ui.button(label="Удалить", style=disnake.ButtonStyle.danger, custom_id="publish_remove")
    async def remove_item(self, button: disnake.ui.Button, inter: disnake.MessageInteraction):
        await inter.response.send_modal(PublishManageModal(mode="remove"))

    @disnake.ui.button(label="Опубликовать", style=disnake.ButtonStyle.primary, custom_id="publish_send")
    async def publish(self, button: disnake.ui.Button, inter: disnake.MessageInteraction):
        await inter.response.defer(ephemeral=True)
        user_ids = _list_table("publish_queue")
        if not user_ids:
            await inter.edit_original_response("❌ Нет принятых участников.")
            return

        mention_list = _format_mentions(user_ids)
        components = [
            ui.TextDisplay("<a:JABA:1464585875282460703> По результатам обзвона на пост <@&1275588344499277934> подошли следующие кандидаты:"),
            ui.Separator(divider=True, spacing=SeparatorSpacing.small),
            ui.TextDisplay(mention_list),
            ui.Separator(divider=True, spacing=SeparatorSpacing.small),
            ui.TextDisplay("Желаем удачи!\n*Просьба связаться с <@1072166657549676726>/<@438731964313370635> в личных сообщениях discord для дальнейшей информации"),
        ]

        container = ui.Container(*components, accent_colour=disnake.Color(0xD11D68))
        channel = inter.guild.get_channel(PUBLISH_CHANNEL_ID)
        if not channel:
            await inter.edit_original_response("❌ Канал для публикации не найден.")
            return

        await channel.send(components=[container])

        date_key = _date_key()
        for user_id in user_ids:
            _add_history("publish_history", date_key, int(user_id))

        conn = _get_db_connection()
        conn.execute("DELETE FROM publish_queue")
        conn.commit()
        conn.close()

        await _clear_list_channel(inter.guild)
        await _update_publish_panel(inter.guild)
        await inter.edit_original_response("✅ Опубликовано.")


class PublishManageModal(disnake.ui.Modal):
    def __init__(self, mode: str, panel_message_id: int | None = None, panel_channel_id: int | None = None):
        self.mode = mode
        self.panel_message_id = panel_message_id
        self.panel_channel_id = panel_channel_id
        components = [
            disnake.ui.TextInput(
                label="ID пользователя",
                placeholder="123456789012345678",
                custom_id="user_id",
                max_length=20,
            )
        ]
        title = "Добавить участника" if mode == "add" else "Удалить участника"
        super().__init__(title=title, components=components)

    async def callback(self, inter: disnake.ModalInteraction):
        await inter.response.defer(ephemeral=True)
        raw_id = inter.text_values.get("user_id", "").strip().lstrip("<@!").rstrip(">")
        if not raw_id.isdigit():
            await inter.edit_original_response("❌ Неверный ID пользователя.")
            return

        user_id = int(raw_id)
        if self.mode == "add":
            _add_to_table("publish_queue", user_id)
            action_text = "Добавил участника в show-publish"
        else:
            _remove_from_table("publish_queue", user_id)
            action_text = "Удалил участника из show-publish"

        await _edit_panel_message(inter.guild, self.panel_channel_id, self.panel_message_id, is_publish=True)
        await _update_publish_panel(inter.guild)
        await inter.edit_original_response("✅ Готово.")
        await _log_zayavki_action(inter.guild, inter.author, action_text, f"ID: {user_id}")


class AcceptedManageView(disnake.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @disnake.ui.button(label="Опубликовать", style=disnake.ButtonStyle.primary, custom_id="accepted_publish")
    async def publish(self, button: disnake.ui.Button, inter: disnake.MessageInteraction):
        await inter.response.send_modal(PublishInterviewModal())

    @disnake.ui.button(label="Удалить", style=disnake.ButtonStyle.danger, custom_id="accepted_remove")
    async def remove(self, button: disnake.ui.Button, inter: disnake.MessageInteraction):
        await inter.response.send_modal(AcceptedManageModal())


class AcceptedManageModal(disnake.ui.Modal):
    def __init__(self, panel_message_id: int | None = None, panel_channel_id: int | None = None):
        self.panel_message_id = panel_message_id
        self.panel_channel_id = panel_channel_id
        components = [
            disnake.ui.TextInput(
                label="ID пользователя",
                placeholder="123456789012345678",
                custom_id="user_id",
                max_length=20,
            )
        ]
        super().__init__(title="Удалить из одобренных", components=components)

    async def callback(self, inter: disnake.ModalInteraction):
        await inter.response.defer(ephemeral=True)
        raw_id = inter.text_values.get("user_id", "").strip().lstrip("<@!").rstrip(">")
        if not raw_id.isdigit():
            await inter.edit_original_response("❌ Неверный ID пользователя.")
            return

        target_id = int(raw_id)
        _remove_from_table("accepted_queue", target_id)
        await _edit_panel_message(inter.guild, self.panel_channel_id, self.panel_message_id, is_publish=False)
        await _update_accepted_panel(inter.guild)
        await inter.edit_original_response("✅ Удалено.")
        await _log_zayavki_action(inter.guild, inter.author, "Удалил участника из show-accepted", f"ID: {target_id}")


async def _edit_panel_message(
    guild: disnake.Guild | None,
    channel_id: int | None,
    message_id: int | None,
    *,
    is_publish: bool,
) -> None:
    if not guild or not channel_id or not message_id:
        return
    channel = _get_channel_or_thread(guild, int(channel_id))
    if not channel:
        return
    try:
        message = await channel.fetch_message(int(message_id))
    except disnake.HTTPException:
        return

    if is_publish:
        user_ids = _list_table("publish_queue")
        content = _format_mentions(user_ids, "Нет принятых участников")
        components = _publish_panel_components(content)
    else:
        user_ids = _list_table("accepted_queue")
        content = _format_mentions(user_ids)
        components = _accepted_panel_components(content)

    try:
        await message.edit(content=None, embed=None, components=components)
    except disnake.HTTPException as exc:
        return


async def _update_publish_panel(guild: disnake.Guild | None) -> None:
    if guild is None:
        return

    message_id = _get_setting("show_publish_message_id")
    channel_id = _get_setting("show_publish_channel_id")
    message = await _fetch_panel_message(guild, message_id, channel_id)

    if message is None:
        # Fallback: scan list channel for latest container message.
        list_channel = _get_channel_or_thread(guild, LIST_CHANNEL_ID)
        if not list_channel:
            return
        try:
            async for candidate in list_channel.history(limit=50):
                if candidate.author != guild.me:
                    continue
                if _message_has_container(candidate):
                    message = candidate
                    _set_setting("show_publish_message_id", str(candidate.id))
                    _set_setting("show_publish_channel_id", str(list_channel.id))
                    break
        except disnake.HTTPException:
            return

    if message is None:
        return

    _set_setting("show_publish_channel_id", str(message.channel.id))

    user_ids = _list_table("publish_queue")
    content = _format_mentions(user_ids, "Нет принятых участников")
    components = _publish_panel_components(content)
    try:
        await message.edit(content=None, embed=None, components=components)
    except disnake.HTTPException as exc:
        return


async def _update_accepted_panel(guild: disnake.Guild | None) -> None:
    if guild is None:
        return

    message_id = _get_setting("show_accepted_message_id")
    channel_id = _get_setting("show_accepted_channel_id")
    message = await _fetch_panel_message(guild, message_id, channel_id)

    if message is None:
        list_channel = _get_channel_or_thread(guild, LIST_CHANNEL_ID)
        if not list_channel:
            return
        try:
            async for candidate in list_channel.history(limit=50):
                if candidate.author != guild.me:
                    continue
                if _message_has_container(candidate):
                    message = candidate
                    _set_setting("show_accepted_message_id", str(candidate.id))
                    _set_setting("show_accepted_channel_id", str(list_channel.id))
                    break
        except disnake.HTTPException:
            return

    if message is None:
        return

    _set_setting("show_accepted_channel_id", str(message.channel.id))

    user_ids = _list_table("accepted_queue")
    content = _format_mentions(user_ids)
    components = _accepted_panel_components(content)
    try:
        await message.edit(content=None, embed=None, components=components)
    except disnake.HTTPException as exc:
        return


async def _clear_list_channel(guild: disnake.Guild | None) -> None:
    if guild is None:
        return

    channel = _get_channel_or_thread(guild, LIST_CHANNEL_ID)
    if not channel:
        return

    accepted_id = _get_setting("show_accepted_message_id")
    publish_id = _get_setting("show_publish_message_id")
    try:
        messages = [message async for message in channel.history(limit=50)]
    except disnake.HTTPException:
        return

    for message in messages:
        if message.author == guild.me:
            if str(message.id) in {accepted_id, publish_id}:
                continue
            try:
                await message.delete()
            except disnake.HTTPException:
                continue


def setup(bot):
    _init_db()
    bot.add_cog(ZayavkiPanel(bot))
    async def _register_views():
        await bot.wait_until_ready()
        bot.add_view(ZayavkiView())
    bot.loop.create_task(_register_views())