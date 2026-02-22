import disnake
from disnake.ext import commands, tasks
from disnake import ui, SeparatorSpacing
from colorama import Fore, Style
from datetime import datetime, timezone
import json
import os
import re

# ==========================
# НАСТРОЙКИ
# ==========================

TOKEN = "your-discord-bot-token"
ALLOWED_USER_ID = userid
GLOBAL_BASE_ALLOWED_USER_IDS = {
    userid,
}
ZAYAVKI_STATIC_ALLOWED_USER_IDS = {
    userid,
    userid,
}
IMAGE_PATH = "assets/cristCatwebp.webp"
ACCENT_COLOR = disnake.Colour(0xD11D68)
DEBUG_MEMBERS = False

TEXT = """
## Недопустимые действия

Ниже перечислены основные нарушения, за которые участник может быть ограничен
в сообществе, а в отдельных случаях — получить наказание в игре.

Во всём остальном действуют общие правила **Majestic RP**.  
Модератор выдает степень наказания, полагаясь на своё субъективное мнение.  
Обжаловать любое наказание можно у <@userid>.

Запрещено:
- 1.1 Дезинформировать участников сообщества
- 1.2 Оскорблять проект, администрацию и участников
- 1.3 Спамить, флудить, злоупотреблять упоминаниями (@)
- 1.4 Использовать неподобающие ники, статусы или аватарки
- 1.5 Провоцировать конфликты, угрожать, вести себя токсично
- 1.6 Распространять файлы (кроме изображений, гифок и видео)
- 1.7 Мешать в голосовых каналах (громкие звуки, скримеры и т.п.)
- 1.8 Выдавать себя за модерацию, администрацию или команду проекта
- 1.9 Публиковать NSFW-контент, политические высказывания, агитацию
- 1.10 Распространять сторонний контент и ссылки, не относящиеся к проекту
- 1.11 Обсуждать или дискредитировать действия администрации в негативном ключе
"""

ROLE_GROUPS = [
    ("Chief Events", roleid),
    ("Deputy Chief Events", roleid),
    ("Senior Event Administrators", roleid),
    ("Event Administrators", roleid),
    ("Chief Event Helper", roleid),
    ("Senior Event Helpers", roleid),
    ("Event Helpers", roleid)
]

ROLE_COUNT_TITLES = {
    "Event Administrators",
    "Senior Event Helpers",
    "Event Helpers"
}

# ==========================
# БОТ
# ==========================

intents = disnake.Intents.default()
intents.message_content = True
intents.members = True
bot = commands.Bot(command_prefix=".", intents=intents)

_last_members_message = {
    "guild_id": None,
    "channel_id": None,
    "message_id": None
}

MEMBERS_MESSAGE_STATE_FILE = "data/members_message_state.json"
MEMBER_EXTRAS_FILE = "data/member_extras.json"
MEMBER_EXTRAS = {}
STATS_CHANNEL_ID = channelid
STATS_MESSAGE_ID = messageid
STATS_COUNTS = {}
PYTHON_ACCESS_FILE = "data/python_command_access.json"


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


def _save_python_access(data: dict) -> None:
    os.makedirs("data", exist_ok=True)
    users = sorted({str(x) for x in data.get("users", []) if str(x).isdigit()} | {str(ALLOWED_USER_ID)})
    roles = sorted({str(x) for x in data.get("roles", []) if str(x).isdigit()})
    payload = {
        "users": users,
        "roles": roles,
        "allow_admin_roles": bool(data.get("allow_admin_roles", False)),
    }
    with open(PYTHON_ACCESS_FILE, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


def _member_has_dynamic_access(member: disnake.Member | None, guild: disnake.Guild | None, *, include_admin_roles: bool = True) -> bool:
    if member is None or guild is None:
        return False

    access = _load_python_access()
    if str(member.id) in access["users"]:
        return True

    role_ids = {str(role.id) for role in getattr(member, "roles", [])}
    if role_ids.intersection(access["roles"]):
        return True

    if include_admin_roles and access.get("allow_admin_roles", False) and member.guild_permissions.administrator:
        return True

    return False


def _is_allowed_for_command(author: disnake.abc.User, guild: disnake.Guild | None, command: commands.Command | None) -> bool:
    is_zayavki = bool(command and getattr(command, "cog_name", "") == "ZayavkiPanel")

    if author.id in GLOBAL_BASE_ALLOWED_USER_IDS:
        return True
    if is_zayavki and author.id in ZAYAVKI_STATIC_ALLOWED_USER_IDS:
        return True

    member = author if isinstance(author, disnake.Member) else None
    return _member_has_dynamic_access(member, guild, include_admin_roles=True)


@bot.check
async def global_prefix_command_access(ctx: commands.Context) -> bool:
    if ctx.guild is None:
        return False

    if not _is_allowed_for_command(ctx.author, ctx.guild, ctx.command):
        return False

    return True


async def global_application_command_access(inter: disnake.ApplicationCommandInteraction) -> bool:
    if inter.guild_id is None:
        return False

    author = getattr(inter, "author", None)
    command = getattr(inter, "application_command", None)
    guild = inter.guild
    if author is None or not _is_allowed_for_command(author, guild, command):
        return False

    return True


try:
    bot.add_app_command_check(global_application_command_access)
except Exception:
    pass


def _load_members_message_state():
    if os.path.exists(MEMBERS_MESSAGE_STATE_FILE):
        try:
            with open(MEMBERS_MESSAGE_STATE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                _last_members_message.update({
                    "guild_id": data.get("guild_id"),
                    "channel_id": data.get("channel_id"),
                    "message_id": data.get("message_id"),
                })
        except Exception:
            pass


def _save_members_message_state():
    os.makedirs("data", exist_ok=True)
    with open(MEMBERS_MESSAGE_STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(_last_members_message, f, ensure_ascii=False, indent=2)


def _load_member_extras():
    global MEMBER_EXTRAS
    if os.path.exists(MEMBER_EXTRAS_FILE):
        try:
            with open(MEMBER_EXTRAS_FILE, "r", encoding="utf-8") as f:
                MEMBER_EXTRAS = json.load(f)
        except Exception:
            MEMBER_EXTRAS = {}


def _save_member_extras():
    os.makedirs("data", exist_ok=True)
    with open(MEMBER_EXTRAS_FILE, "w", encoding="utf-8") as f:
        json.dump(MEMBER_EXTRAS, f, ensure_ascii=False, indent=2)


def _can_manage_python_access(ctx: commands.Context) -> bool:
    return ctx.author.id == ALLOWED_USER_ID and ctx.guild is not None


def build_members_container(guild: disnake.Guild, members=None):
    role_ids = [role_id for _, role_id in ROLE_GROUPS]
    buckets = {role_id: [] for role_id in role_ids}

    if members is None:
        members = guild.members

    for member in members:
        member_roles = [role for role in member.roles if role.id in role_ids]
        if not member_roles:
            continue

        highest = max(member_roles, key=lambda r: r.position)
        buckets[highest.id].append(member)

    components = []
    for index, (title, role_id) in enumerate(ROLE_GROUPS):
        members = buckets.get(role_id, [])
        members.sort(key=lambda m: (m.display_name or m.name).lower())
        if members:
            lines_list = []
            for m in members:
                extra = MEMBER_EXTRAS.get(str(m.id))
                count = STATS_COUNTS.get(str(m.id), 0)
                suffix = f" - ({count})"
                if extra and extra.get("nickname") and extra.get("static"):
                    lines_list.append(f"<@{m.id}> - {extra['nickname']}, #{extra['static']}{suffix}")
                else:
                    lines_list.append(f"<@{m.id}>" + suffix)
            lines = "\n".join(lines_list)
        else:
            lines = "—"

        display_title = title
        if title in ROLE_COUNT_TITLES:
            display_title = f"{title} ({len(members)})"

        components.append(ui.TextDisplay(f"**{display_title}**\n{lines}"))
        if index < len(ROLE_GROUPS) - 1:
            components.append(ui.Separator(divider=True, spacing=SeparatorSpacing.small))

    return ui.Container(*components, accent_colour=ACCENT_COLOR)


@tasks.loop(seconds=60)
async def update_members_message():
    guild_id = _last_members_message.get("guild_id")
    channel_id = _last_members_message.get("channel_id")
    message_id = _last_members_message.get("message_id")

    if not guild_id or not channel_id or not message_id:
        return

    guild = bot.get_guild(guild_id)
    if not guild:
        return

    channel = guild.get_channel(channel_id)
    if not channel:
        try:
            channel = await bot.fetch_channel(channel_id)
        except disnake.NotFound:
            return
        except disnake.HTTPException:
            return

    # If this is a thread, ensure it's not archived
    if isinstance(channel, disnake.Thread) and channel.archived:
        try:
            await channel.edit(archived=False)
        except disnake.Forbidden:
            return
        except disnake.HTTPException:
            return

    if isinstance(channel, disnake.Thread):
        try:
            await channel.join()
        except disnake.Forbidden:
            return
        except disnake.HTTPException:
            return

    try:
        message = await channel.fetch_message(message_id)
    except disnake.NotFound:
        return
    except disnake.HTTPException:
        return

    await _refresh_stats_counts(guild)
    members = [m async for m in guild.fetch_members(limit=None)]
    if not members and guild.member_count:
        try:
            await guild.chunk()
            members = list(guild.members)
        except disnake.HTTPException:
            pass
    container = build_members_container(guild, members=members)
    try:
        await message.edit(components=[container])
    except disnake.HTTPException:
        pass


class MembersSelfAddModal(disnake.ui.Modal):
    def __init__(self, author: disnake.Member):
        self.author = author
        components = [
            disnake.ui.TextInput(
                label="Полный никнейм",
                placeholder="Например: Michael Jackson",
                custom_id="nickname",
                max_length=100,
            ),
            disnake.ui.TextInput(
                label="Статик",
                placeholder="Например: 8282",
                custom_id="static",
                max_length=20,
            ),
        ]
        super().__init__(
            title="Добавить себя в список",
            components=components,
        )

    async def callback(self, inter: disnake.ModalInteraction):
        await inter.response.defer(ephemeral=True)
        nickname = (inter.text_values.get("nickname") or "").strip()
        static_id = (inter.text_values.get("static") or "").strip().lstrip("#")

        if not nickname or not static_id:
            await inter.edit_original_response("❌ Заполните оба поля.")
            return

        MEMBER_EXTRAS[str(self.author.id)] = {
            "nickname": nickname,
            "static": static_id,
        }
        _save_member_extras()

        await update_members_message()
        await inter.edit_original_response("✅ Данные обновлены.")


async def _refresh_stats_counts(guild: disnake.Guild):
    global STATS_COUNTS
    try:
        channel = guild.get_channel(STATS_CHANNEL_ID) or await guild.fetch_channel(STATS_CHANNEL_ID)
    except disnake.HTTPException:
        return
    if not channel:
        return

    try:
        message = await channel.fetch_message(STATS_MESSAGE_ID)
    except disnake.HTTPException:
        return

    text_parts = []
    if message.content:
        text_parts.append(message.content)
    for embed in message.embeds or []:
        if embed.title:
            text_parts.append(embed.title)
        if embed.description:
            text_parts.append(embed.description)
        for field in embed.fields or []:
            text_parts.append(f"{field.name} {field.value}")

    counts = {}
    for line in "\n".join(text_parts).split("\n"):
        user_match = re.search(r"<@!?(\d+)>", line)
        count_match = re.search(r"-\s*(\d+)", line)
        if user_match and count_match:
            counts[user_match.group(1)] = int(count_match.group(1))

    STATS_COUNTS = counts


class MembersSelfAddView(disnake.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @disnake.ui.button(label="Добавить себя", style=disnake.ButtonStyle.primary, custom_id="members_add_self")
    async def add_self(self, button: disnake.ui.Button, inter: disnake.MessageInteraction):
        await inter.response.send_modal(MembersSelfAddModal(inter.author))


@bot.event
async def on_ready():
    print(f"{Fore.GREEN}✓ Bot logged in as {bot.user}{Style.RESET_ALL}")
    _load_members_message_state()
    _load_member_extras()
    if not update_members_message.is_running():
        update_members_message.start()
    bot.add_view(MembersSelfAddView())
    await update_members_message()


@bot.event
async def on_member_join(member: disnake.Member):
    await update_members_message()


@bot.event
async def on_member_remove(member: disnake.Member):
    await update_members_message()


@bot.event
async def on_command_error(ctx, error):
    """Игнорируем ошибки CommandNotFound"""
    if isinstance(error, (commands.CommandNotFound, commands.CheckFailure, commands.NoPrivateMessage)):
        return
    raise error


# ==========================
# ЗАГРУЗКА COGS
# ==========================

def load_cogs():
    # Load specific cogs if their files exist
    for cog_name in ("zayavkiPanel", "registration", "pubgRegistration", "questionsPanel", "winnerV2Bridge"):
        cog_file = f"{cog_name}.py"
        if os.path.exists(cog_file):
            try:
                bot.load_extension(cog_name)
                print(f"{Fore.GREEN}✓ Loaded {cog_name}{Style.RESET_ALL}")
            except Exception as e:
                print(f"{Fore.RED}✗ Failed to load {cog_name}: {e}{Style.RESET_ALL}")

load_cogs()


@bot.command(name="debug-members")
async def debug_members(ctx: commands.Context):
    role_map = {role_id: title for title, role_id in ROLE_GROUPS}
    roles = {role.id: role for role in ctx.guild.roles if role.id in role_map}

    members = [m async for m in ctx.guild.fetch_members(limit=None)]
    if not members and ctx.guild.member_count:
        try:
            await ctx.guild.chunk()
            members = list(ctx.guild.members)
        except disnake.HTTPException:
            pass

    counts = {role_id: 0 for role_id in role_map}
    for m in members:
        for r in m.roles:
            if r.id in counts:
                counts[r.id] += 1

    lines = [
        f"members_total: {len(members)}",
        f"member_count: {ctx.guild.member_count}",
        f"last_message: {json.dumps(_last_members_message, ensure_ascii=False)}",
    ]
    for role_id, title in role_map.items():
        role = roles.get(role_id)
        lines.append(f"{title}: role_exists={bool(role)} count={counts.get(role_id, 0)}")

    await ctx.send("\n".join(lines))


@bot.command(name="refresh-members")
async def refresh_members(ctx: commands.Context):
    await update_members_message()
    await ctx.send("✅ Обновление запущено.")


@bot.command(name="send_rules", aliases=["sendrules", "rulespanel"])
async def send_rules(ctx: commands.Context):
    if ctx.author.id != ALLOWED_USER_ID:
        return

    components = []
    components.append(ui.TextDisplay(TEXT))

    file = None
    if os.path.exists(IMAGE_PATH):
        file = disnake.File(IMAGE_PATH, filename="rules.webp")
        components.append(ui.Separator(divider=True, spacing=SeparatorSpacing.small))
        components.append(
            ui.MediaGallery(
                disnake.MediaGalleryItem(
                    media="attachment://rules.webp"
                )
            )
        )
    else:
        print(f"{Fore.RED}✗ Image not found: {IMAGE_PATH}{Style.RESET_ALL}")

    container = ui.Container(
        *components,
        accent_colour=ACCENT_COLOR
    )

    if file:
        await ctx.send(components=[container], file=file)
    else:
        await ctx.send(components=[container])


@bot.command(name="show-members")
async def show_members(ctx: commands.Context):
    await _refresh_stats_counts(ctx.guild)
    members = [m async for m in ctx.guild.fetch_members(limit=None)]
    if not members and ctx.guild.member_count:
        try:
            await ctx.guild.chunk()
            members = list(ctx.guild.members)
        except disnake.HTTPException:
            pass
    container = build_members_container(ctx.guild, members=members)

    message = await ctx.send(components=[container])
    await ctx.send(view=MembersSelfAddView())
    try:
        await ctx.message.delete()
    except disnake.HTTPException:
        pass

    _last_members_message["guild_id"] = ctx.guild.id
    _last_members_message["channel_id"] = ctx.channel.id
    _last_members_message["message_id"] = message.id
    _save_members_message_state()

    await update_members_message()


@bot.command(name="pythongiveAccess-id")
async def pythongive_access_id(ctx: commands.Context, discord_id: str = None):
    if not _can_manage_python_access(ctx):
        return
    if not discord_id or not discord_id.isdigit():
        await ctx.send("❌ Использование: .pythongiveAccess-id <discord_id>")
        return

    access = _load_python_access()
    access["users"] = sorted(set(access.get("users", [])) | {discord_id, str(ALLOWED_USER_ID)})
    _save_python_access(access)
    await ctx.send(f"✅ Доступ выдан пользователю <@{discord_id}>.")


@bot.command(name="pythongiveAccess-admin", aliases=["pythoniveAccess-admin"])
async def pythongive_access_admin(ctx: commands.Context):
    if not _can_manage_python_access(ctx):
        return
    access = _load_python_access()
    access["allow_admin_roles"] = True
    _save_python_access(access)
    await ctx.send("✅ Доступ выдан всем ролям с правами администратора.")


@bot.command(name="pythongiveAccess-role")
async def pythongive_access_role(ctx: commands.Context, role_id: str = None):
    if not _can_manage_python_access(ctx):
        return
    if not role_id or not role_id.isdigit():
        await ctx.send("❌ Использование: .pythongiveAccess-role <role_id>")
        return

    role = ctx.guild.get_role(int(role_id)) if ctx.guild else None
    if role is None:
        await ctx.send("❌ Роль не найдена.")
        return

    access = _load_python_access()
    access["roles"] = sorted(set(access.get("roles", [])) | {role_id})
    _save_python_access(access)
    await ctx.send(f"✅ Доступ выдан роли <@&{role_id}>.")


@bot.command(name="pythonremoveAccess-id")
async def pythonremove_access_id(ctx: commands.Context, discord_id: str = None):
    if not _can_manage_python_access(ctx):
        return
    if not discord_id or not discord_id.isdigit():
        await ctx.send("❌ Использование: .pythonremoveAccess-id <discord_id>")
        return

    access = _load_python_access()
    users = set(access.get("users", []))
    if discord_id == str(ALLOWED_USER_ID):
        await ctx.send("❌ Нельзя удалить доступ у основного владельца.")
        return

    users.discard(discord_id)
    access["users"] = sorted(users)
    _save_python_access(access)
    await ctx.send(f"✅ Доступ у пользователя <@{discord_id}> удалён.")


@bot.command(name="pythonremoveAccess-role")
async def pythonremove_access_role(ctx: commands.Context, role_id: str = None):
    if not _can_manage_python_access(ctx):
        return
    if not role_id or not role_id.isdigit():
        await ctx.send("❌ Использование: .pythonremoveAccess-role <role_id>")
        return

    access = _load_python_access()
    roles = set(access.get("roles", []))
    roles.discard(role_id)
    access["roles"] = sorted(roles)
    _save_python_access(access)
    await ctx.send(f"✅ Доступ у роли <@&{role_id}> удалён.")


@bot.command(name="pythonremoveAccess-admin", aliases=["pythonremoveiveAccess-admin"])
async def pythonremove_access_admin(ctx: commands.Context):
    if not _can_manage_python_access(ctx):
        return

    access = _load_python_access()
    access["allow_admin_roles"] = False
    _save_python_access(access)
    await ctx.send("✅ Доступ для ролей с правами администратора отключён.")


@bot.command(name="pythonshowAccess")
async def pythonshow_access(ctx: commands.Context):
    if not _can_manage_python_access(ctx):
        return

    access = _load_python_access()
    users = access.get("users", [])
    roles = access.get("roles", [])
    allow_admin_roles = bool(access.get("allow_admin_roles", False))

    users_text = "\n".join(f"- <@{user_id}> ({user_id})" for user_id in users) if users else "- —"
    roles_text = "\n".join(f"- <@&{role_id}> ({role_id})" for role_id in roles) if roles else "- —"
    admin_text = "включен" if allow_admin_roles else "выключен"

    await ctx.send(
        "**Python access**\n"
        f"**Users:**\n{users_text}\n"
        f"**Roles:**\n{roles_text}\n"
        f"**Admin roles mode:** {admin_text}"
    )


# ==========================
# ЗАПУСК
# ==========================

bot.run(TOKEN)
