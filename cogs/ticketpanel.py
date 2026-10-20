import asyncio
import json
import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path

import discord
from discord import app_commands
from discord.ext import commands
from cogs import _style as style

log = logging.getLogger("bot.ticketpanel")

DATA_FILE = Path(__file__).resolve().parent.parent / "data" / "ticket_panel.json"

# ---- Your ticket categories: edit this list ----
# key: short internal name (no spaces), used in the channel name
CATEGORIES = [
    {"key": "spawner_sell", "label": "Spawner Sell", "emoji": "💰", "description": "Sell a spawner", "env": "TICKET_CATEGORY_SPAWNER_SELL_ID"},
    {"key": "spawner_buy", "label": "Spawner Buy", "emoji": "🛒", "description": "Buy a spawner", "env": "TICKET_CATEGORY_SPAWNER_BUY_ID"},
    {"key": "support", "label": "Support", "emoji": "🛠️", "description": "Questions or help with anything", "env": "TICKET_CATEGORY_SUPPORT_ID"},
    {"key": "mod_purchase", "label": "Mod Purchase", "emoji": "🧩", "description": "Buy a mod", "env": "TICKET_CATEGORY_MOD_PURCHASE_ID"},
    {"key": "giveaway_claim", "label": "Giveaway Claim", "emoji": "🎁", "description": "Claim a giveaway prize", "env": "TICKET_CATEGORY_GIVEAWAY_CLAIM_ID"},
]
CATEGORY_BY_KEY = {c["key"]: c for c in CATEGORIES}


def _env_id(name: str) -> int:
    value = os.getenv(name, "").strip()
    return int(value) if value.isdigit() else 0


TICKET_CATEGORY_ID = _env_id("TICKET_CATEGORY_ID")  # Discord category where tickets are created
SUPPORT_ROLE_ID = _env_id("SUPPORT_ROLE_ID")        # staff role that can see all tickets


# ---------- storage ----------

def _load() -> list[dict]:
    try:
        return json.loads(DATA_FILE.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return []
    except json.JSONDecodeError:
        log.exception("%s is corrupted, starting with an empty list", DATA_FILE)
        return []


def _save(items: list[dict]) -> None:
    DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = DATA_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(items, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, DATA_FILE)


def _open_ticket_for(guild_id: int, user_id: int) -> dict | None:
    for item in _load():
        if item["guild_id"] == guild_id and item["user_id"] == user_id:
            return item
    return None


def _by_channel(channel_id: int) -> dict | None:
    for item in _load():
        if item["channel_id"] == channel_id:
            return item
    return None


def _add(entry: dict) -> None:
    items = _load()
    items.append(entry)
    _save(items)


def _remove(channel_id: int) -> None:
    _save([item for item in _load() if item["channel_id"] != channel_id])


# ---------- buttons and menus ----------

class CloseView(discord.ui.View):
    """Shown inside each ticket. Persistent, so it works after a restart."""

    def __init__(self) -> None:
        super().__init__(timeout=None)

    @discord.ui.button(label="Close ticket", style=discord.ButtonStyle.danger, emoji="🔒", custom_id="ticketpanel:close")
    async def close(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if _by_channel(interaction.channel_id) is None:
            await interaction.response.send_message("This is not an open ticket.", ephemeral=True)
            return

        await interaction.response.send_message("Closing this ticket in 5 seconds…")
        _remove(interaction.channel_id)
        await asyncio.sleep(5)
        try:
            await interaction.channel.delete(reason=f"Ticket closed by {interaction.user}")
        except discord.HTTPException:
            log.exception("Could not delete ticket channel %s", interaction.channel_id)


async def _open_ticket(interaction: discord.Interaction, key: str) -> None:
    category = CATEGORY_BY_KEY.get(key)
    if category is None:
        await interaction.response.send_message("This category no longer exists.", ephemeral=True)
        return

    guild = interaction.guild
    member = interaction.user

    existing = _open_ticket_for(guild.id, member.id)
    if existing is not None:
        channel = guild.get_channel(existing["channel_id"])
        if channel is not None:
            await interaction.response.send_message(
                f"You already have an open ticket: {channel.mention}", ephemeral=True
            )
            return
        _remove(existing["channel_id"])  # Channel was deleted by hand, clean up the record

    await interaction.response.defer(ephemeral=True)

    overwrites = {
        guild.default_role: discord.PermissionOverwrite(view_channel=False),
        member: discord.PermissionOverwrite(
            view_channel=True, send_messages=True, read_message_history=True,
            attach_files=True, embed_links=True,
        ),
        guild.me: discord.PermissionOverwrite(
            view_channel=True, send_messages=True, manage_channels=True, read_message_history=True,
        ),
    }
    support_role = guild.get_role(SUPPORT_ROLE_ID) if SUPPORT_ROLE_ID else None
    if support_role is not None:
        overwrites[support_role] = discord.PermissionOverwrite(
            view_channel=True, send_messages=True, read_message_history=True,
        )

    # Each ticket type has its own Discord category. Falls back to TICKET_CATEGORY_ID if not set.
    category_id = _env_id(category["env"]) or TICKET_CATEGORY_ID
    parent = guild.get_channel(category_id) if category_id else None
    if not isinstance(parent, discord.CategoryChannel):
        log.warning(
            "Category for '%s' not found. Check %s in .env (it must be a category ID, not a channel ID).",
            category["label"], category["env"],
        )
        parent = None

    base = re.sub(r"[^a-z0-9-]", "-", member.name.lower()).strip("-")[:40] or "user"
    try:
        channel = await guild.create_text_channel(
            f"{key}-{base}",
            overwrites=overwrites,
            category=parent,
            reason=f"Ticket opened by {member}",
        )
    except discord.HTTPException:
        log.exception("Could not create ticket channel for %s", member.id)
        await interaction.followup.send(
            "I could not create your ticket. Please tell an admin.", ephemeral=True
        )
        return

    _add({
        "guild_id": guild.id,
        "channel_id": channel.id,
        "user_id": member.id,
        "category": key,
        "created_at": datetime.now(timezone.utc).isoformat(),
    })

    embed = discord.Embed(
        title=f"{category['emoji']} {category['label']}",
        description=(
            f"Hi {member.mention}! Please describe your request in as much detail as you can. "
            "A staff member will be with you soon."
        ),
        color=style.INFO,
    )
    await channel.send(content=member.mention, embed=embed, view=CloseView())
    await interaction.followup.send(f"Your ticket is ready: {channel.mention}", ephemeral=True)


class TicketSelect(discord.ui.Select):
    def __init__(self) -> None:
        options = [
            discord.SelectOption(
                label=c["label"], value=c["key"], description=c["description"], emoji=c["emoji"]
            )
            for c in CATEGORIES
        ]
        super().__init__(
            placeholder="Choose a ticket category…",
            min_values=1,
            max_values=1,
            options=options,
            custom_id="ticketpanel:select",
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        await _open_ticket(interaction, self.values[0])


class PanelView(discord.ui.View):
    """The panel with the category menu. Persistent, so it works after a restart."""

    def __init__(self) -> None:
        super().__init__(timeout=None)
        self.add_item(TicketSelect())


class CloseRequestView(discord.ui.View):
    """Shown on a close request. Only the ticket creator can answer it."""

    def __init__(self) -> None:
        super().__init__(timeout=None)

    @discord.ui.button(label="Accept close", style=discord.ButtonStyle.success, emoji="✅", custom_id="ticketpanel:reqclose:accept")
    async def accept(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        ticket = _by_channel(interaction.channel_id)
        if ticket is None:
            await interaction.response.send_message("This is not an open ticket.", ephemeral=True)
            return
        if interaction.user.id != ticket["user_id"]:
            await interaction.response.send_message(
                "Only the ticket creator can answer this request.", ephemeral=True
            )
            return

        await interaction.response.edit_message(
            content=f"Accepted by {interaction.user.mention}. Closing this ticket in 5 seconds…",
            embed=None,
            view=None,
        )
        _remove(interaction.channel_id)
        await asyncio.sleep(5)
        try:
            await interaction.channel.delete(reason=f"Close request accepted by {interaction.user}")
        except discord.HTTPException:
            log.exception("Could not delete ticket channel %s", interaction.channel_id)

    @discord.ui.button(label="Decline", style=discord.ButtonStyle.secondary, emoji="✖️", custom_id="ticketpanel:reqclose:decline")
    async def decline(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        ticket = _by_channel(interaction.channel_id)
        if ticket is None:
            await interaction.response.send_message("This is not an open ticket.", ephemeral=True)
            return
        if interaction.user.id != ticket["user_id"]:
            await interaction.response.send_message(
                "Only the ticket creator can answer this request.", ephemeral=True
            )
            return

        await interaction.response.edit_message(
            content=f"Declined by {interaction.user.mention}. The ticket stays open.",
            embed=None,
            view=None,
        )


# ---------- cog ----------

class TicketPanel(commands.Cog):
    """Ticket panel: members open private tickets by choosing a category."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    async def cog_load(self) -> None:
        self.bot.add_view(PanelView())
        self.bot.add_view(CloseView())
        self.bot.add_view(CloseRequestView())

    @app_commands.command(name="ticketpanel", description="Posts the ticket panel in this channel.")
    @app_commands.guild_only()
    @app_commands.default_permissions(manage_channels=True)
    @app_commands.checks.has_permissions(manage_channels=True)
    async def ticketpanel(self, interaction: discord.Interaction) -> None:
        embed = discord.Embed(
            title="Ticket Rules",
            description="Choose a category below to open a private ticket.",
            color=style.INFO,
        )
        embed.add_field(
            name="Before you open a ticket",
            value=(
                "Check `#spawner-prices` and `#faq` first.\n"
                "Ask your question clearly and right away.\n"
                "Spawner sales only happen on certain occasions. If it is not announced, don't ask."
            ),
            inline=False,
        )
        embed.add_field(
            name="Rules",
            value=(
                "No troll tickets or unnecessary pings to staff.\n"
                "Tickets inactive for 1+ days will be closed.\n"
                "Fake giveaway claims or trolling will result in a timeout.\n"
                "Staff will never DM you. All responses stay in the ticket."
            ),
            inline=False,
        )
        await interaction.channel.send(embed=embed, view=PanelView())
        await interaction.response.send_message("Ticket panel posted.", ephemeral=True)

    @app_commands.command(name="add", description="Adds a member to the current ticket.")
    @app_commands.describe(user="The member to add to this ticket")
    @app_commands.guild_only()
    async def add(self, interaction: discord.Interaction, user: discord.Member) -> None:
        ticket = _by_channel(interaction.channel_id)
        if ticket is None:
            await interaction.response.send_message(
                "This command only works inside a ticket.", ephemeral=True
            )
            return

        member = interaction.user
        is_owner = member.id == ticket["user_id"]
        is_staff = member.guild_permissions.manage_channels or (
            SUPPORT_ROLE_ID and any(role.id == SUPPORT_ROLE_ID for role in member.roles)
        )
        if not (is_owner or is_staff):
            await interaction.response.send_message(
                "Only the ticket owner or staff can add members.", ephemeral=True
            )
            return

        if user.bot:
            await interaction.response.send_message("Bots can't be added to tickets.", ephemeral=True)
            return
        if user.id in (member.id, interaction.guild.me.id):
            await interaction.response.send_message("That user is already part of this ticket.", ephemeral=True)
            return

        try:
            await interaction.channel.set_permissions(
                user,
                view_channel=True,
                send_messages=True,
                read_message_history=True,
                attach_files=True,
                embed_links=True,
                reason=f"Added to ticket by {member}",
            )
        except discord.HTTPException:
            log.exception("Could not add %s to ticket %s", user.id, interaction.channel_id)
            await interaction.response.send_message(
                "I could not add that member. Please try again.", ephemeral=True
            )
            return

        await interaction.response.send_message(
            f"{user.mention} was added to this ticket by {member.mention}."
        )

    @app_commands.command(name="requestclose", description="Asks the ticket creator to approve closing this ticket.")
    @app_commands.guild_only()
    async def requestclose(self, interaction: discord.Interaction) -> None:
        ticket = _by_channel(interaction.channel_id)
        if ticket is None:
            await interaction.response.send_message(
                "This command only works inside a ticket.", ephemeral=True
            )
            return

        member = interaction.user
        is_staff = member.guild_permissions.manage_channels or (
            SUPPORT_ROLE_ID and any(role.id == SUPPORT_ROLE_ID for role in member.roles)
        )
        if not is_staff:
            await interaction.response.send_message(
                "Only staff can request that a ticket is closed.", ephemeral=True
            )
            return

        embed = discord.Embed(
            title="Close request",
            description=(
                f"{member.mention} would like to close this ticket.\n"
                f"<@{ticket['user_id']}>, please accept or decline below."
            ),
            color=style.WARNING,
        )
        await interaction.channel.send(
            content=f"<@{ticket['user_id']}>",
            embed=embed,
            view=CloseRequestView(),
        )
        await interaction.response.send_message("Close request sent.", ephemeral=True)

    @app_commands.command(name="close", description="Closes the current ticket.")
    @app_commands.guild_only()
    async def close(self, interaction: discord.Interaction) -> None:
        ticket = _by_channel(interaction.channel_id)
        if ticket is None:
            await interaction.response.send_message(
                "This command only works inside a ticket.", ephemeral=True
            )
            return

        member = interaction.user
        is_owner = member.id == ticket["user_id"]
        is_staff = member.guild_permissions.manage_channels or (
            SUPPORT_ROLE_ID and any(role.id == SUPPORT_ROLE_ID for role in member.roles)
        )
        if not (is_owner or is_staff):
            await interaction.response.send_message(
                "Only the ticket owner or staff can close this ticket.", ephemeral=True
            )
            return

        await interaction.response.send_message("Closing this ticket in 5 seconds…")
        _remove(interaction.channel_id)
        await asyncio.sleep(5)
        try:
            await interaction.channel.delete(reason=f"Ticket closed by {member}")
        except discord.HTTPException:
            log.exception("Could not delete ticket channel %s", interaction.channel_id)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(TicketPanel(bot))
