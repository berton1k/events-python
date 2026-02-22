import disnake
from disnake.ext import commands
from disnake import ui, SeparatorSpacing
import json
import os
from typing import Optional

# Constants
SUBMIT_CHANNEL = 1467468720912728076
NOTIFY_ID = 1072166657549676726
PUBG_TEAMS_FILE = "data/pubg_teams.json"
PUBG_IMAGE_PATH = "assets/kva.png"
PUBG_PANEL_IMAGE_PATH = "assets/PUBG.png"
PUBG_PANEL_IMAGE_URL = "https://cdn.discordapp.com/attachments/965947335886667806/1469472731400634612/PUBG.png"
SUDNIY_TEAMS_FILE = "data/sudniy_teams.json"
SUDNIY_PANEL_IMAGE_PATH = "assets/sudniy.png"
PUBG_PANEL_STATE_FILE = "data/pubg_panel_state.json"
PUBG_LOCKS_FILE = "data/pubg_locks.json"
PUBG_PENDING_APPROVALS_FILE = "data/pubg_pending_approvals.json"

# In-memory storage for pending approvals (message_id -> team_data)
PENDING_APPROVALS: dict[str, dict] = {}

# Ensure data directory exists
os.makedirs("data", exist_ok=True)

PUBG_PANEL_STATE = {
    "channel_id": None,
    "container_message_id": None,
    "buttons_message_id": None,
    "image_url": None,
}

PUBG_LOCKS = {
    "solo": False,
    "duo": False,
    "squad": False,
}


def _load_pubg_panel_state():
    if os.path.exists(PUBG_PANEL_STATE_FILE):
        try:
            with open(PUBG_PANEL_STATE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                PUBG_PANEL_STATE.update({
                    "channel_id": data.get("channel_id"),
                    "container_message_id": data.get("container_message_id"),
                    "buttons_message_id": data.get("buttons_message_id"),
                    "image_url": data.get("image_url"),
                })
        except Exception:
            pass


def _save_pubg_panel_state():
    os.makedirs("data", exist_ok=True)
    with open(PUBG_PANEL_STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(PUBG_PANEL_STATE, f, ensure_ascii=False, indent=2)


def _load_pubg_locks():
    if os.path.exists(PUBG_LOCKS_FILE):
        try:
            with open(PUBG_LOCKS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                PUBG_LOCKS.update({
                    "solo": bool(data.get("solo", False)),
                    "duo": bool(data.get("duo", False)),
                    "squad": bool(data.get("squad", False)),
                })
        except Exception:
            pass


def _save_pubg_locks():
    os.makedirs("data", exist_ok=True)
    with open(PUBG_LOCKS_FILE, "w", encoding="utf-8") as f:
        json.dump(PUBG_LOCKS, f, ensure_ascii=False, indent=2)


def _load_pending_approvals():
    global PENDING_APPROVALS
    if os.path.exists(PUBG_PENDING_APPROVALS_FILE):
        try:
            with open(PUBG_PENDING_APPROVALS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    PENDING_APPROVALS = data
        except Exception:
            pass


def _save_pending_approvals():
    os.makedirs("data", exist_ok=True)
    with open(PUBG_PENDING_APPROVALS_FILE, "w", encoding="utf-8") as f:
        json.dump(PENDING_APPROVALS, f, ensure_ascii=False, indent=2)


def _get_pubg_counts() -> dict:
    teams = _load_teams()
    return {
        "solo": len(teams.get("solo", [])),
        "duo": len(teams.get("duo", [])),
        "squad": len(teams.get("squad", [])),
    }


def build_pubg_panel_container(image_url: str | None = None) -> ui.Container:
    counts = _get_pubg_counts()
    components = [
        ui.TextDisplay("# <a:1win1:1432977374097571900> Регистрация на PUBG"),
        ui.Separator(divider=True, spacing=SeparatorSpacing.small),
        ui.TextDisplay("**Условие: **нахождение в голосовом чате сервера во время проведения мероприятия"),
        ui.Separator(divider=True, spacing=SeparatorSpacing.small),
        ui.TextDisplay("**Правила: **https://discord.com/channels/1118611016863973499/1463900635748499508/1463908908883251286"),
        ui.Separator(divider=True, spacing=SeparatorSpacing.small),
        ui.TextDisplay(
            "**Режимы**\n"
            f"Solo - игра в одиночку — команд участвует: ``{counts['solo']}``\n"
            f"Duo - Командная игра из 2 человек — команд участвует: ``{counts['duo']}``\n"
            f"Squad - Командная игра из 4 человек — команд участвует: ``{counts['squad']}``"
        ),
    ]
    if image_url:
        components.append(ui.MediaGallery(disnake.MediaGalleryItem(media=image_url)))
    return ui.Container(*components, accent_colour=disnake.Color(0xD11D68))


async def update_pubg_panel(bot):
    _load_pubg_panel_state()
    _load_pubg_locks()
    channel_id = PUBG_PANEL_STATE.get("channel_id")
    container_message_id = PUBG_PANEL_STATE.get("container_message_id")
    buttons_message_id = PUBG_PANEL_STATE.get("buttons_message_id")
    if not channel_id or not container_message_id or not buttons_message_id:
        return False, "Панель не инициализирована. Отправь заново через .regpt"

    channel = bot.get_channel(channel_id)
    if channel is None:
        try:
            channel = await bot.fetch_channel(channel_id)
        except Exception:
            return False, "Канал панели не найден"

    try:
        container_message = await channel.fetch_message(container_message_id)
        buttons_message = await channel.fetch_message(buttons_message_id)
    except Exception:
        return False, "Сообщения панели не найдены"

    image_url = PUBG_PANEL_STATE.get("image_url") or PUBG_PANEL_IMAGE_URL

    container = build_pubg_panel_container(image_url=image_url)
    try:
        await container_message.edit(components=[container])
        await buttons_message.edit(view=PubgTeamButton())
    except Exception:
        # Fallback: resend container with image to preserve MediaGallery
        container = build_pubg_panel_container(image_url=PUBG_PANEL_IMAGE_URL)
        try:
            new_container = await channel.send(components=[container])
            new_buttons = await channel.send(view=PubgTeamButton())
            try:
                await container_message.delete()
            except Exception:
                pass
            try:
                await buttons_message.delete()
            except Exception:
                pass
            PUBG_PANEL_STATE["container_message_id"] = new_container.id
            PUBG_PANEL_STATE["buttons_message_id"] = new_buttons.id
            PUBG_PANEL_STATE["image_url"] = PUBG_PANEL_IMAGE_URL
            _save_pubg_panel_state()
        except Exception:
            return False, "Не удалось отредактировать контейнер"

    return True, "OK"


def _load_teams() -> dict:
    """Load teams from JSON file"""
    if os.path.exists(PUBG_TEAMS_FILE):
        with open(PUBG_TEAMS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"solo": [], "duo": [], "squad": []}


def _save_teams(teams: dict):
    """Save teams to JSON file"""
    with open(PUBG_TEAMS_FILE, "w", encoding="utf-8") as f:
        json.dump(teams, f, ensure_ascii=False, indent=2)


def _load_sudniy_teams() -> dict:
    """Load sudniy teams from JSON file"""
    if os.path.exists(SUDNIY_TEAMS_FILE):
        with open(SUDNIY_TEAMS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"solo": [], "duo": [], "squad": []}


def _save_sudniy_teams(teams: dict):
    """Save sudniy teams to JSON file"""
    with open(SUDNIY_TEAMS_FILE, "w", encoding="utf-8") as f:
        json.dump(teams, f, ensure_ascii=False, indent=2)


class PubgTeamModal(disnake.ui.Modal):
    def __init__(self, mode: str, author: disnake.Member, bot):
        self.mode = mode
        self.author = author
        self.bot = bot
        
        components = [
            disnake.ui.TextInput(
                label="Название команды",
                placeholder="Введите название команды",
                custom_id="team_name",
                max_length=100,
            ),
            disnake.ui.TextInput(
                label="Ники и StaticID участников",
                placeholder="Michael Jackson 8282, Event Advocatix 15. Можно закрыть форму — текст сохранится.",
                custom_id="team_members",
                style=disnake.TextInputStyle.paragraph,
                max_length=1000,
            ),
        ]
        super().__init__(
            title=f"Регистрация PUBG - {mode.upper()}",
            components=components,
        )

    async def callback(self, inter: disnake.ModalInteraction):
        team_name = inter.text_values.get("team_name", "—")
        team_members = inter.text_values.get("team_members", "—")
        
        # Create team entry (save on approval)
        team_data = {
            "author_id": self.author.id,
            "author_mention": self.author.mention,
            "team_name": team_name,
            "members": team_members,
            "mode": self.mode.lower(),
            "game": "PUBG",
        }
        
        # Send to submission channel
        channel = inter.bot.get_channel(SUBMIT_CHANNEL)
        if channel is None:
            await inter.response.send_message("❌ Канал для заявок не найден.", ephemeral=True)
            return
        
        # Build embed (v1) to allow sending with View
        embed = disnake.Embed(
            title="📋 Новая заявка на PUBG",
            color=0xD11D68
        )
        embed.add_field(name="Режим", value=f"PUBG - {self.mode.upper()}", inline=False)
        embed.add_field(name="Название команды", value=team_name, inline=False)
        embed.add_field(name="Ники и StaticID", value=team_members, inline=False)
        embed.add_field(name="От", value=self.author.mention, inline=False)

        file = None
        if os.path.exists(PUBG_IMAGE_PATH):
            file = disnake.File(PUBG_IMAGE_PATH, filename="kva.png")
            embed.set_image(url="attachment://kva.png")

        try:
            # Embed + кнопки в одном сообщении
            if file:
                msg = await channel.send(content=f"<@{NOTIFY_ID}>", embed=embed, view=PubgApprovalView(), file=file)
            else:
                msg = await channel.send(content=f"<@{NOTIFY_ID}>", embed=embed, view=PubgApprovalView())
            # Сохраняем данные заявки по message.id
            PENDING_APPROVALS[str(msg.id)] = team_data
            _save_pending_approvals()
            await inter.response.send_message(
                "✅ Заявка отправлена!",
                ephemeral=True
            )
        except Exception as e:
            await inter.response.send_message(f"❌ Ошибка: {e}", ephemeral=True)


class PubgApprovalView(disnake.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
    
    @disnake.ui.button(label="✅ Одобрить", style=disnake.ButtonStyle.success, custom_id="pubg_approve")
    async def approve(self, button: disnake.ui.Button, inter: disnake.MessageInteraction):
        await inter.response.defer()
        try:
            team_data = PENDING_APPROVALS.get(str(inter.message.id))
            if not team_data:
                await inter.followup.send("❌ Данные заявки не найдены (возможно, бот был перезапущен).", ephemeral=True)
                return
            teams = _load_teams()
            team_list = teams.get(team_data["mode"], [])
            team_data["id"] = len(team_list) + 1
            team_list.append(team_data)
            teams[team_data["mode"]] = team_list
            _save_teams(teams)
            user = await inter.bot.fetch_user(team_data["author_id"])
            await inter.message.delete()
            # Отправляем в канал статус без кнопок
            status_embed = disnake.Embed(
                title="✅ Заявка одобрена!",
                color=0x00FF00
            )
            await inter.channel.send(embed=status_embed)
            # Отправляем в ЛС embed с фото и участниками
            dm_embed = disnake.Embed(
                title="✅ Заявка одобрена!",
                color=0x00FF00
            )
            dm_embed.add_field(name="Название команды", value=team_data['team_name'], inline=False)
            dm_embed.add_field(name="Ники и StaticID", value=team_data['members'], inline=False)
            dm_embed.add_field(name="Режим", value=f"{team_data.get('game', 'PUBG')} - {team_data['mode'].upper()}", inline=False)
            file = None
            if os.path.exists(PUBG_IMAGE_PATH):
                file = disnake.File(PUBG_IMAGE_PATH, filename="kva.png")
                dm_embed.set_image(url="attachment://kva.png")
            if file:
                await user.send(embed=dm_embed, file=file)
            else:
                await user.send(embed=dm_embed)
            PENDING_APPROVALS.pop(str(inter.message.id), None)
            _save_pending_approvals()
            await update_pubg_panel(inter.bot)
            await inter.followup.send("✅ Пользователю отправлено уведомление об одобрении.", ephemeral=True)
        except Exception as e:
            await inter.followup.send(f"❌ Ошибка при отправке сообщения: {e}", ephemeral=True)
    
    @disnake.ui.button(label="❌ Отклонить", style=disnake.ButtonStyle.danger, custom_id="pubg_reject")
    async def reject(self, button: disnake.ui.Button, inter: disnake.MessageInteraction):
        team_data = PENDING_APPROVALS.get(str(inter.message.id))
        if not team_data:
            await inter.response.send_message("❌ Данные заявки не найдены (возможно, бот был перезапущен).", ephemeral=True)
            return
        await inter.response.send_modal(PubgRejectModal(team_data, inter.message.id))


class PubgRejectModal(disnake.ui.Modal):
    def __init__(self, team_data: dict, message_id: int):
        self.team_data = team_data
        self.message_id = message_id
        
        components = [
            disnake.ui.TextInput(
                label="Причина отклонения",
                placeholder="Укажите причину отклонения заявки",
                custom_id="reject_reason",
                style=disnake.TextInputStyle.paragraph,
                max_length=500,
            ),
        ]
        
        super().__init__(
            title="Причина отклонения",
            components=components,
        )
    
    async def callback(self, inter: disnake.ModalInteraction):
        reason = inter.text_values.get("reject_reason", "Нет причины")
        await inter.response.defer()
        try:
            user = await inter.bot.fetch_user(self.team_data["author_id"])
            try:
                msg = await inter.channel.fetch_message(self.message_id)
                await msg.delete()
            except disnake.NotFound:
                pass
            # Отправляем в канал статус без кнопок
            status_embed = disnake.Embed(
                title="❌ Заявка отклонена!",
                color=0xFF0000
            )
            await inter.channel.send(embed=status_embed)
            # Отправляем в ЛС embed с фото, участниками и причиной
            dm_embed = disnake.Embed(
                title="❌ Заявка отклонена!",
                color=0xFF0000
            )
            dm_embed.add_field(name="Название команды", value=self.team_data['team_name'], inline=False)
            dm_embed.add_field(name="Ники и StaticID", value=self.team_data['members'], inline=False)
            dm_embed.add_field(name="Режим", value=f"{self.team_data.get('game', 'PUBG')} - {self.team_data['mode'].upper()}", inline=False)
            dm_embed.add_field(name="Причина отклонения", value=reason, inline=False)
            file = None
            if os.path.exists(PUBG_IMAGE_PATH):
                file = disnake.File(PUBG_IMAGE_PATH, filename="kva.png")
                dm_embed.set_image(url="attachment://kva.png")
            if file:
                await user.send(embed=dm_embed, file=file)
            else:
                await user.send(embed=dm_embed)
            PENDING_APPROVALS.pop(str(self.message_id), None)
            _save_pending_approvals()
            await update_pubg_panel(inter.bot)
            await inter.followup.send("✅ Пользователю отправлено уведомление об отклонении.", ephemeral=True)
        except Exception as e:
            await inter.followup.send(f"❌ Ошибка при отправке сообщения: {e}", ephemeral=True)


class PubgTeamButton(disnake.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        _load_pubg_locks()
        self._apply_lock_labels()

    def _apply_lock_labels(self):
        for child in self.children:
            if not isinstance(child, disnake.ui.Button):
                continue
            if child.custom_id == "pubg_solo":
                base_label = "Solo"
                locked = PUBG_LOCKS.get("solo", False)
            elif child.custom_id == "pubg_duo":
                base_label = "Duo"
                locked = PUBG_LOCKS.get("duo", False)
            elif child.custom_id == "pubg_squad":
                base_label = "Squad"
                locked = PUBG_LOCKS.get("squad", False)
            else:
                continue
            child.label = f"{base_label} 🔒" if locked else base_label

    @disnake.ui.button(label="Solo", style=disnake.ButtonStyle.primary, custom_id="pubg_solo")
    async def solo(self, button: disnake.ui.Button, inter: disnake.MessageInteraction):
        if PUBG_LOCKS.get("solo", False):
            await inter.response.send_message("🔒 Регистрация закрыта.", ephemeral=True)
            return
        await inter.response.send_modal(PubgTeamModal("Solo", inter.author, inter.bot))

    @disnake.ui.button(label="Duo", style=disnake.ButtonStyle.primary, custom_id="pubg_duo")
    async def duo(self, button: disnake.ui.Button, inter: disnake.MessageInteraction):
        if PUBG_LOCKS.get("duo", False):
            await inter.response.send_message("🔒 Регистрация закрыта.", ephemeral=True)
            return
        await inter.response.send_modal(PubgTeamModal("Duo", inter.author, inter.bot))

    @disnake.ui.button(label="Squad", style=disnake.ButtonStyle.primary, custom_id="pubg_squad")
    async def squad(self, button: disnake.ui.Button, inter: disnake.MessageInteraction):
        if PUBG_LOCKS.get("squad", False):
            await inter.response.send_message("🔒 Регистрация закрыта.", ephemeral=True)
            return
        await inter.response.send_modal(PubgTeamModal("Squad", inter.author, inter.bot))


class SudniyTeamModal(disnake.ui.Modal):
    def __init__(self, mode: str, author: disnake.Member, bot):
        self.mode = mode
        self.author = author
        self.bot = bot

        components = [
            disnake.ui.TextInput(
                label="Название команды",
                placeholder="Введите название команды",
                custom_id="team_name",
                max_length=100,
            ),
            disnake.ui.TextInput(
                label="Ники и StaticID участников",
                placeholder="Michael Jackson 8282, Event Advocatix 15. Можно закрыть форму — текст сохранится.",
                custom_id="team_members",
                style=disnake.TextInputStyle.paragraph,
                max_length=1000,
            ),
        ]
        super().__init__(
            title=f"Регистрация Судный час - {mode.upper()}",
            components=components,
        )

    async def callback(self, inter: disnake.ModalInteraction):
        team_name = inter.text_values.get("team_name", "—")
        team_members = inter.text_values.get("team_members", "—")

        team_data = {
            "id": len(_load_sudniy_teams().get(self.mode.lower(), [])) + 1,
            "author_id": self.author.id,
            "author_mention": self.author.mention,
            "team_name": team_name,
            "members": team_members,
            "mode": self.mode.lower(),
            "game": "Судный час",
        }

        teams = _load_sudniy_teams()
        teams[self.mode.lower()].append(team_data)
        _save_sudniy_teams(teams)

        channel = inter.bot.get_channel(SUBMIT_CHANNEL)
        if channel is None:
            await inter.response.send_message("❌ Канал для заявок не найден.", ephemeral=True)
            return

        embed = disnake.Embed(
            title="📋 Новая заявка на Судный час",
            color=0xD11D68
        )
        embed.add_field(name="Режим", value=f"Судный час - {self.mode.upper()}", inline=False)
        embed.add_field(name="Название команды", value=team_name, inline=False)
        embed.add_field(name="Ники и StaticID", value=team_members, inline=False)
        embed.add_field(name="От", value=self.author.mention, inline=False)

        try:
            msg = await channel.send(content=f"<@{NOTIFY_ID}>", embed=embed, view=PubgApprovalView())
            PENDING_APPROVALS[msg.id] = team_data
            await inter.response.send_message("✅ Заявка отправлена!", ephemeral=True)
        except Exception as e:
            await inter.response.send_message(f"❌ Ошибка: {e}", ephemeral=True)


class SudniyTeamButton(disnake.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @disnake.ui.button(label="Solo", style=disnake.ButtonStyle.primary, custom_id="sudniy_solo")
    async def solo(self, button: disnake.ui.Button, inter: disnake.MessageInteraction):
        await inter.response.send_modal(SudniyTeamModal("Solo", inter.author, inter.bot))

    @disnake.ui.button(label="Duo", style=disnake.ButtonStyle.primary, custom_id="sudniy_duo")
    async def duo(self, button: disnake.ui.Button, inter: disnake.MessageInteraction):
        await inter.response.send_modal(SudniyTeamModal("Duo", inter.author, inter.bot))

    @disnake.ui.button(label="Squad", style=disnake.ButtonStyle.primary, custom_id="sudniy_squad")
    async def squad(self, button: disnake.ui.Button, inter: disnake.MessageInteraction):
        await inter.response.send_modal(SudniyTeamModal("Squad", inter.author, inter.bot))


class PubgPaginationView(disnake.ui.View):
    def __init__(self, mode: str, page: int = 0, items_per_page: int = 10):
        super().__init__(timeout=None)
        self.mode = mode
        self.page = page
        self.items_per_page = items_per_page
        self.teams = _load_teams().get(mode.lower(), [])
        self.total_pages = (len(self.teams) + items_per_page - 1) // items_per_page or 1
    
    @disnake.ui.button(label="◀️ Назад", style=disnake.ButtonStyle.secondary, custom_id="pubg_prev")
    async def prev_page(self, button: disnake.ui.Button, inter: disnake.MessageInteraction):
        if self.page == 0:
            await inter.response.send_message("📄 Это первая страница", ephemeral=True)
        else:
            self.page -= 1
            await inter.response.defer()
            await self._update_display(inter)
    
    @disnake.ui.button(label="▶️ Дальше", style=disnake.ButtonStyle.secondary, custom_id="pubg_next")
    async def next_page(self, button: disnake.ui.Button, inter: disnake.MessageInteraction):
        if self.page >= self.total_pages - 1:
            await inter.response.send_message("📄 Это последняя страница", ephemeral=True)
        else:
            self.page += 1
            await inter.response.defer()
            await self._update_display(inter)
    
    @disnake.ui.button(label="🚀 Запустить МП", style=disnake.ButtonStyle.success, custom_id="pubg_launch")
    async def launch(self, button: disnake.ui.Button, inter: disnake.MessageInteraction):
        await inter.response.send_modal(PubgLaunchModal(self.mode))
    
    @disnake.ui.button(label="👥 Изменить участников", style=disnake.ButtonStyle.danger, custom_id="pubg_edit_members")
    async def edit_members(self, button: disnake.ui.Button, inter: disnake.MessageInteraction):
        await inter.response.send_modal(PubgEditMembersModal(self.mode))
    
    async def _update_display(self, inter: disnake.MessageInteraction):
        """Update the display message with new page"""
        start = self.page * self.items_per_page
        end = start + self.items_per_page
        page_teams = self.teams[start:end]
        
        embed = self._build_embed(page_teams)
        await inter.edit_original_response(embed=embed, view=self)
    
    def _build_embed(self, page_teams: list) -> disnake.Embed:
        embed = disnake.Embed(
            title=f"PUBG - {self.mode.upper()} - ({len(self.teams)} команд)",
            color=0xD11D68
        )
        
        if not page_teams:
            embed.description = "Нет команд для отображения"
            return embed
        
        teams_text = ""
        for team in page_teams:
            teams_text += f"**{team['id']}.** {team['author_mention']}\n"
            teams_text += f"```{team['members']}```\n"
        
        embed.add_field(name="Команды", value=teams_text, inline=False)
        embed.set_footer(text=f"Страница {self.page + 1}/{self.total_pages}")
        
        return embed


class SudniyPaginationView(disnake.ui.View):
    def __init__(self, mode: str, page: int = 0, items_per_page: int = 10):
        super().__init__(timeout=None)
        self.mode = mode
        self.page = page
        self.items_per_page = items_per_page
        self.teams = _load_sudniy_teams().get(mode.lower(), [])
        self.total_pages = (len(self.teams) + items_per_page - 1) // items_per_page or 1

    @disnake.ui.button(label="◀️ Назад", style=disnake.ButtonStyle.secondary, custom_id="sudniy_prev")
    async def prev_page(self, button: disnake.ui.Button, inter: disnake.MessageInteraction):
        if self.page == 0:
            await inter.response.send_message("📄 Это первая страница", ephemeral=True)
        else:
            self.page -= 1
            await inter.response.defer()
            await self._update_display(inter)

    @disnake.ui.button(label="▶️ Дальше", style=disnake.ButtonStyle.secondary, custom_id="sudniy_next")
    async def next_page(self, button: disnake.ui.Button, inter: disnake.MessageInteraction):
        if self.page >= self.total_pages - 1:
            await inter.response.send_message("📄 Это последняя страница", ephemeral=True)
        else:
            self.page += 1
            await inter.response.defer()
            await self._update_display(inter)

    @disnake.ui.button(label="🚀 Запустить МП", style=disnake.ButtonStyle.success, custom_id="sudniy_launch")
    async def launch(self, button: disnake.ui.Button, inter: disnake.MessageInteraction):
        await inter.response.send_modal(SudniyLaunchModal(self.mode))

    @disnake.ui.button(label="👥 Изменить участников", style=disnake.ButtonStyle.danger, custom_id="sudniy_edit_members")
    async def edit_members(self, button: disnake.ui.Button, inter: disnake.MessageInteraction):
        await inter.response.send_modal(SudniyEditMembersModal(self.mode))

    async def _update_display(self, inter: disnake.MessageInteraction):
        start = self.page * self.items_per_page
        end = start + self.items_per_page
        page_teams = self.teams[start:end]

        embed = self._build_embed(page_teams)
        await inter.edit_original_response(embed=embed, view=self)

    def _build_embed(self, page_teams: list) -> disnake.Embed:
        embed = disnake.Embed(
            title=f"Судный час - {self.mode.upper()} - ({len(self.teams)} команд)",
            color=0xD11D68
        )

        if not page_teams:
            embed.description = "Нет команд для отображения"
            return embed

        teams_text = ""
        for team in page_teams:
            teams_text += f"**{team['id']}.** {team['author_mention']}\n"
            teams_text += f"```{team['members']}```\n"

        embed.add_field(name="Команды", value=teams_text, inline=False)
        embed.set_footer(text=f"Страница {self.page + 1}/{self.total_pages}")

        return embed


class PubgLaunchModal(disnake.ui.Modal):
    def __init__(self, mode: str):
        self.mode = mode
        
        components = [
            disnake.ui.TextInput(
                label="Время проведения МП",
                placeholder="Например: 15:00 или 15:00 MSK",
                custom_id="launch_time",
                max_length=100,
            ),
        ]
        
        super().__init__(
            title=f"Запуск PUBG - {mode.upper()}",
            components=components,
        )
    
    async def callback(self, inter: disnake.ModalInteraction):
        launch_time = inter.text_values.get("launch_time", "—")
        
        await inter.response.defer()
        
        teams = _load_teams().get(self.mode.lower(), [])
        
        for team in teams:
            try:
                user = await inter.bot.fetch_user(team["author_id"])
                
                embed = disnake.Embed(
                    title=f"🚀 PUBG - {self.mode.upper()} запущена!",
                    color=0x00FF00
                )
                embed.add_field(name="Название команды", value=team['team_name'], inline=False)
                embed.add_field(name="Участники", value=team['members'], inline=False)
                embed.add_field(name="Время проведения", value=launch_time, inline=False)
                embed.add_field(name="Мероприятие", value=f"PUBG - {self.mode.upper()}", inline=False)
                
                await user.send(embed=embed)
            except Exception as e:
                print(f"Ошибка при отправке сообщения {team['author_id']}: {e}")
        
        await inter.followup.send(f"✅ Уведомления отправлены всем участникам о запуске PUBG - {self.mode.upper()} на {launch_time}", ephemeral=True)


class SudniyLaunchModal(disnake.ui.Modal):
    def __init__(self, mode: str):
        self.mode = mode

        components = [
            disnake.ui.TextInput(
                label="Время проведения МП",
                placeholder="Например: 15:00 или 15:00 MSK",
                custom_id="launch_time",
                max_length=100,
            ),
        ]

        super().__init__(
            title=f"Запуск Судного часа - {mode.upper()}",
            components=components,
        )

    async def callback(self, inter: disnake.ModalInteraction):
        launch_time = inter.text_values.get("launch_time", "—")

        await inter.response.defer()

        teams = _load_sudniy_teams().get(self.mode.lower(), [])

        for team in teams:
            try:
                user = await inter.bot.fetch_user(team["author_id"])

                embed = disnake.Embed(
                    title=f"🚀 Судный час - {self.mode.upper()} запущен!",
                    color=0x00FF00
                )
                embed.add_field(name="Название команды", value=team['team_name'], inline=False)
                embed.add_field(name="Участники", value=team['members'], inline=False)
                embed.add_field(name="Время проведения", value=launch_time, inline=False)
                embed.add_field(name="Мероприятие", value=f"Судный час - {self.mode.upper()}", inline=False)

                await user.send(embed=embed)
            except Exception as e:
                print(f"Ошибка при отправке сообщения {team['author_id']}: {e}")

        await inter.followup.send(
            f"✅ Уведомления отправлены всем участникам о запуске Судного часа - {self.mode.upper()} на {launch_time}",
            ephemeral=True,
        )


class SudniyEditMembersModal(disnake.ui.Modal):
    def __init__(self, mode: str):
        self.mode = mode

        components = [
            disnake.ui.TextInput(
                label="Номер команды",
                placeholder="Например: 1",
                custom_id="team_number",
                max_length=10,
            ),
            disnake.ui.TextInput(
                label="Причина исключения",
                placeholder="Укажите причину исключения",
                custom_id="exclusion_reason",
                style=disnake.TextInputStyle.paragraph,
                max_length=500,
            ),
        ]

        super().__init__(
            title=f"Исключить команду из Судного часа - {mode.upper()}",
            components=components,
        )

    async def callback(self, inter: disnake.ModalInteraction):
        try:
            team_number = int(inter.text_values.get("team_number", "0"))
            reason = inter.text_values.get("exclusion_reason", "Нет причины")
        except ValueError:
            await inter.response.send_message("❌ Некорректный номер команды", ephemeral=True)
            return

        await inter.response.defer()

        teams = _load_sudniy_teams()
        mode_teams = teams.get(self.mode.lower(), [])

        team_to_remove = None
        for team in mode_teams:
            if team['id'] == team_number:
                team_to_remove = team
                break

        if not team_to_remove:
            await inter.followup.send(f"❌ Команда №{team_number} не найдена", ephemeral=True)
            return

        mode_teams.remove(team_to_remove)
        teams[self.mode.lower()] = mode_teams
        _save_sudniy_teams(teams)

        try:
            user = await inter.bot.fetch_user(team_to_remove["author_id"])

            embed = disnake.Embed(
                title=f"❌ Команда исключена из Судного часа - {self.mode.upper()}",
                color=0xFF0000
            )
            embed.add_field(name="Название команды", value=team_to_remove['team_name'], inline=False)
            embed.add_field(name="Мероприятие", value=f"Судный час - {self.mode.upper()}", inline=False)
            embed.add_field(name="Причина исключения", value=reason, inline=False)
            embed.add_field(name="В случае жалоб", value=f"<@{NOTIFY_ID}>", inline=False)

            await user.send(embed=embed)
        except Exception as e:
            print(f"Ошибка при отправке сообщения: {e}")

        await inter.followup.send(
            f"✅ Команда №{team_number} исключена. Пользователю отправлено уведомление.",
            ephemeral=True,
        )


class PubgEditMembersModal(disnake.ui.Modal):
    def __init__(self, mode: str):
        self.mode = mode
        
        components = [
            disnake.ui.TextInput(
                label="Номер команды",
                placeholder="Например: 1",
                custom_id="team_number",
                max_length=10,
            ),
            disnake.ui.TextInput(
                label="Причина исключения",
                placeholder="Укажите причину исключения",
                custom_id="exclusion_reason",
                style=disnake.TextInputStyle.paragraph,
                max_length=500,
            ),
        ]
        
        super().__init__(
            title=f"Исключить команду из PUBG - {mode.upper()}",
            components=components,
        )
    
    async def callback(self, inter: disnake.ModalInteraction):
        try:
            team_number = int(inter.text_values.get("team_number", "0"))
            reason = inter.text_values.get("exclusion_reason", "Нет причины")
        except ValueError:
            await inter.response.send_message("❌ Некорректный номер команды", ephemeral=True)
            return
        
        await inter.response.defer()
        
        teams = _load_teams()
        mode_teams = teams.get(self.mode.lower(), [])
        
        # Find team by number
        team_to_remove = None
        for team in mode_teams:
            if team['id'] == team_number:
                team_to_remove = team
                break
        
        if not team_to_remove:
            await inter.followup.send(f"❌ Команда №{team_number} не найдена", ephemeral=True)
            return
        
        # Remove team
        mode_teams.remove(team_to_remove)
        teams[self.mode.lower()] = mode_teams
        _save_teams(teams)
        await update_pubg_panel(inter.bot)
        
        # Notify user
        try:
            user = await inter.bot.fetch_user(team_to_remove["author_id"])
            
            embed = disnake.Embed(
                title=f"❌ Команда исключена из PUBG - {self.mode.upper()}",
                color=0xFF0000
            )
            embed.add_field(name="Название команды", value=team_to_remove['team_name'], inline=False)
            embed.add_field(name="Мероприятие", value=f"PUBG - {self.mode.upper()}", inline=False)
            embed.add_field(name="Причина исключения", value=reason, inline=False)
            embed.add_field(name="В случае жалоб", value=f"<@{NOTIFY_ID}>", inline=False)
            
            await user.send(embed=embed)
        except Exception as e:
            print(f"Ошибка при отправке сообщения: {e}")
        
        await inter.followup.send(f"✅ Команда №{team_number} исключена. Пользователю отправлено уведомление.", ephemeral=True)


class PubgRegistrationCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        _load_pubg_panel_state()
        _load_pubg_locks()
        _load_pending_approvals()
    
    @commands.command(name="regpt")
    async def regpt(self, ctx: commands.Context, channel_id: str = None):
        """Send PUBG team registration panel"""
        if channel_id is None:
            await ctx.send("❌ Укажите ID канала. Использование: `.regpt <channel_id>`")
            return
        
        try:
            cid = int(channel_id)
        except ValueError:
            await ctx.send("❌ Некорректный ID канала")
            return
        
        channel = ctx.bot.get_channel(cid)
        if channel is None:
            await ctx.send("❌ Канал не найден")
            return
        
        # Create v2 container
        container = build_pubg_panel_container(image_url=PUBG_PANEL_IMAGE_URL)
        
        try:
            container_msg = await channel.send(components=[container])
            buttons_msg = await channel.send(view=PubgTeamButton())
            PUBG_PANEL_STATE["channel_id"] = channel.id
            PUBG_PANEL_STATE["container_message_id"] = container_msg.id
            PUBG_PANEL_STATE["buttons_message_id"] = buttons_msg.id
            PUBG_PANEL_STATE["image_url"] = PUBG_PANEL_IMAGE_URL
            _save_pubg_panel_state()
            await ctx.send("✅ Панель регистрации отправлена")
        except disnake.Forbidden:
            await ctx.send("❌ Нет прав на отправку в указанный канал")
        except Exception as e:
            await ctx.send(f"❌ Ошибка: {e}")

    @commands.command(name="regst")
    async def regst(self, ctx: commands.Context, channel_id: str = None):
        """Send SUDNIY team registration panel"""
        if channel_id is None:
            await ctx.send("❌ Укажите ID канала. Использование: `.regst <channel_id>`")
            return

        try:
            cid = int(channel_id)
        except ValueError:
            await ctx.send("❌ Некорректный ID канала")
            return

        channel = ctx.bot.get_channel(cid)
        if channel is None:
            await ctx.send("❌ Канал не найден")
            return

        components = [
            ui.TextDisplay("# <a:1win1:1432977374097571900> Регистрация на Судный час"),
            ui.Separator(divider=True, spacing=SeparatorSpacing.small),
            ui.TextDisplay("**Условие: **нахождение в голосовом чате сервера во время проведения мероприятия"),
            ui.Separator(divider=True, spacing=SeparatorSpacing.small),
            ui.TextDisplay("**Правила: **https://discord.com/channels/1118611016863973499/1463900564344537312/1463908541382262784"),
            ui.Separator(divider=True, spacing=SeparatorSpacing.small),
            ui.TextDisplay(
                "**Режимы**\n"
                "Solo - игра в одиночку\n"
                "Duo - Командная игра из 2 человек\n"
                "Squad - Командная игра из 4 человек"
            ),
        ]
        file = None
        if os.path.exists(SUDNIY_PANEL_IMAGE_PATH):
            file = disnake.File(SUDNIY_PANEL_IMAGE_PATH, filename="sudniy.png")
            components.append(ui.MediaGallery(disnake.MediaGalleryItem(media="attachment://sudniy.png")))
        container = ui.Container(*components, accent_colour=disnake.Color(0xD11D68))

        try:
            if file:
                await channel.send(components=[container], file=file)
            else:
                await channel.send(components=[container])
            await channel.send(view=SudniyTeamButton())
            await ctx.send("✅ Панель регистрации отправлена")
        except disnake.Forbidden:
            await ctx.send("❌ Нет прав на отправку в указанный канал")
        except Exception as e:
            await ctx.send(f"❌ Ошибка: {e}")

    @commands.command(name="pclear-solo")
    async def pclear_solo(self, ctx: commands.Context):
        teams = _load_teams()
        teams["solo"] = []
        _save_teams(teams)
        await update_pubg_panel(ctx.bot)
        await ctx.send("✅ Список PUBG Solo очищен")

    @commands.command(name="pclear-duo")
    async def pclear_duo(self, ctx: commands.Context):
        teams = _load_teams()
        teams["duo"] = []
        _save_teams(teams)
        await update_pubg_panel(ctx.bot)
        await ctx.send("✅ Список PUBG Duo очищен")

    @commands.command(name="pclear-squad")
    async def pclear_squad(self, ctx: commands.Context):
        teams = _load_teams()
        teams["squad"] = []
        _save_teams(teams)
        await update_pubg_panel(ctx.bot)
        await ctx.send("✅ Список PUBG Squad очищен")

    @commands.command(name="lock-solo")
    async def plock_solo(self, ctx: commands.Context):
        PUBG_LOCKS["solo"] = True
        _save_pubg_locks()
        await update_pubg_panel(ctx.bot)
        await ctx.send("🔒 Solo регистрация закрыта")

    @commands.command(name="lock-duo")
    async def plock_duo(self, ctx: commands.Context):
        PUBG_LOCKS["duo"] = True
        _save_pubg_locks()
        await update_pubg_panel(ctx.bot)
        await ctx.send("🔒 Duo регистрация закрыта")

    @commands.command(name="lock-squad")
    async def plock_squad(self, ctx: commands.Context):
        PUBG_LOCKS["squad"] = True
        _save_pubg_locks()
        await update_pubg_panel(ctx.bot)
        await ctx.send("🔒 Squad регистрация закрыта")

    @commands.command(name="unlock-solo")
    async def punlock_solo(self, ctx: commands.Context):
        PUBG_LOCKS["solo"] = False
        _save_pubg_locks()
        await update_pubg_panel(ctx.bot)
        await ctx.send("🔓 Solo регистрация открыта")

    @commands.command(name="unlock-duo")
    async def punlock_duo(self, ctx: commands.Context):
        PUBG_LOCKS["duo"] = False
        _save_pubg_locks()
        await update_pubg_panel(ctx.bot)
        await ctx.send("🔓 Duo регистрация открыта")

    @commands.command(name="unlock-squad")
    async def punlock_squad(self, ctx: commands.Context):
        PUBG_LOCKS["squad"] = False
        _save_pubg_locks()
        await update_pubg_panel(ctx.bot)
        await ctx.send("🔓 Squad регистрация открыта")

    @commands.command(name="refresh-pubg")
    async def refresh_pubg(self, ctx: commands.Context):
        ok, reason = await update_pubg_panel(ctx.bot)
        if ok:
            await ctx.send("✅ Панель PUBG обновлена")
        else:
            await ctx.send(f"❌ Не удалось обновить панель: {reason}")

    @commands.command(name="sclear-solo")
    async def sclear_solo(self, ctx: commands.Context):
        teams = _load_sudniy_teams()
        teams["solo"] = []
        _save_sudniy_teams(teams)
        await ctx.send("✅ Список Судный час Solo очищен")

    @commands.command(name="sclear-duo")
    async def sclear_duo(self, ctx: commands.Context):
        teams = _load_sudniy_teams()
        teams["duo"] = []
        _save_sudniy_teams(teams)
        await ctx.send("✅ Список Судный час Duo очищен")

    @commands.command(name="sclear-squad")
    async def sclear_squad(self, ctx: commands.Context):
        teams = _load_sudniy_teams()
        teams["squad"] = []
        _save_sudniy_teams(teams)
        await ctx.send("✅ Список Судный час Squad очищен")
    
    @commands.command(name="show-solo")
    async def show_solo(self, ctx: commands.Context):
        """Show Solo teams"""
        await self._show_teams(ctx, "solo")
    
    @commands.command(name="show-duo")
    async def show_duo(self, ctx: commands.Context):
        """Show Duo teams"""
        await self._show_teams(ctx, "duo")
    
    @commands.command(name="show-squad")
    async def show_squad(self, ctx: commands.Context):
        """Show Squad teams"""
        await self._show_teams(ctx, "squad")
    
    async def _show_teams(self, ctx: commands.Context, mode: str):
        """Display teams in pagination format"""
        teams = _load_teams().get(mode.lower(), [])
        
        if not teams:
            await ctx.send(f"❌ Нет команд в режиме {mode.upper()}")
            return
        
        view = PubgPaginationView(mode)
        
        # Build first page embed
        start = 0
        end = view.items_per_page
        page_teams = teams[start:end]
        
        embed = view._build_embed(page_teams)
        
        await ctx.send(embed=embed, view=view)

    @commands.command(name="shows-solo")
    async def shows_solo(self, ctx: commands.Context):
        """Show Sudniy Solo teams"""
        await self._show_sudniy_teams(ctx, "solo")

    @commands.command(name="shows-duo")
    async def shows_duo(self, ctx: commands.Context):
        """Show Sudniy Duo teams"""
        await self._show_sudniy_teams(ctx, "duo")

    @commands.command(name="shows-squad")
    async def shows_squad(self, ctx: commands.Context):
        """Show Sudniy Squad teams"""
        await self._show_sudniy_teams(ctx, "squad")

    async def _show_sudniy_teams(self, ctx: commands.Context, mode: str):
        """Display Sudniy teams in pagination format"""
        teams = _load_sudniy_teams().get(mode.lower(), [])

        if not teams:
            await ctx.send(f"❌ Нет команд в режиме {mode.upper()}")
            return

        view = SudniyPaginationView(mode)

        start = 0
        end = view.items_per_page
        page_teams = teams[start:end]

        embed = view._build_embed(page_teams)

        await ctx.send(embed=embed, view=view)


def setup(bot):
    bot.add_cog(PubgRegistrationCog(bot))
    # Persistent views registration (after loop is running)
    async def _register_views():
        await bot.wait_until_ready()
        bot.add_view(PubgTeamButton())
        bot.add_view(PubgApprovalView())
        bot.add_view(SudniyTeamButton())
    bot.loop.create_task(_register_views())
