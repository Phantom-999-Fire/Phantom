import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

import discord
from discord import app_commands
from discord.ext import commands
from cogs import _style as style

log = logging.getLogger("bot.banreq")

DATA_FILE = Path(__file__).resolve().parent.parent / "data" / "banreqs.json"


def _env_id(name: str) -> int:
    value = os.getenv(name, "").strip()
    return int(value) if value.isdigit() else 0


REQUESTER_ROLE_ID = _env_id("BANREQ_ROLE_ID")          # role that may create requests
REVIEW_CHANNEL_ID = _env_id("BAN_REVIEW_CHANNEL_ID")   # channel where requests appear


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


def _get(message_id: int) -> dict | None:
    for item in _load():
        if item["message_id"] == message_id:
            return item
    return None


def _add(entry: dict) -> None:
    items = _load()
    items.append(entry)
    _save(items)


def _update(message_id: int, **fields) -> None:
    items = _load()
    for item in items:
        if item["message_id"] == message_id:
            item.update(fields)
            break
    _save(items)


def _has_pending_for(guild_id: int, target_id: int) -> bool:
    return any(
        item["guild_id"] == guild_id and item["target_id"] == target_id and item["status"] == "pending"
        for item in _load()
    )


# ---------- embeds ----------

def _review_embed(request: dict, status: str, color: discord.Color) -> discord.Embed:
    embed = discord.Embed(title="Ban Request", color=color)
    embed.add_field(name="Target", value=f"<@{request['target_id']}> (`{request['target_id']}`)", inline=False)
    embed.add_field(name="Requested by", value=f"<@{request['requester_id']}>", inline=True)
    embed.add_field(name="Reason", value=request["reason"], inline=False)
    embed.add_field(name="Status", value=status, inline=False)
    return embed


# ---------- review buttons ----------

async def _decide(interaction: discord.Interaction, approve: bool) -> None:
    await interaction.response.defer()  # Gives us time for the ban call

    request = _get(interaction.message.id)
    if request is None or request["status"] != "pending":
        await interaction.followup.send("This request is no longer open.", ephemeral=True)
        return

    guild = interaction.guild
    decider = interaction.user
    requester = guild.get_member(request["requester_id"])

    if decider.id == request["requester_id"]:
        await interaction.followup.send("You can't decide your own request.", ephemeral=True)
        return
    if decider.id != guild.owner_id:
        if requester is None or decider.top_role <= requester.top_role:
            await interaction.followup.send(
                "Only a member with a higher role than the requester can decide this.", ephemeral=True
            )
            return

    if not approve:
        _update(interaction.message.id, status="denied", decided_by=decider.id)
        embed = _review_embed(request, f"Denied by {decider.mention}", style.ERROR)
        await interaction.edit_original_response(embed=embed, view=None)
        return

    target_id = request["target_id"]
    target = guild.get_member(target_id)
    if target_id == guild.owner_id:
        await interaction.followup.send("The server owner can't be banned.", ephemeral=True)
        return
    if target is not None and target.top_role >= guild.me.top_role:
        await interaction.followup.send(
            "I can't ban this user because their role is equal to or higher than mine.", ephemeral=True
        )
        return

    try:
        user = await interaction.client.fetch_user(target_id)
        await guild.ban(
            user,
            reason=f"Ban request approved by {decider}: {request['reason']}",
        )
    except discord.Forbidden:
        await interaction.followup.send("I don't have permission to ban that user.", ephemeral=True)
        return
    except discord.HTTPException:
        log.exception("Could not ban %s", target_id)
        await interaction.followup.send("The ban failed. Please try again.", ephemeral=True)
        return

    _update(interaction.message.id, status="approved", decided_by=decider.id)
    embed = _review_embed(request, f"Approved by {decider.mention}", style.SUCCESS)
    await interaction.edit_original_response(embed=embed, view=None)


class BanReviewView(discord.ui.View):
    """Persistent view: its buttons keep working after the bot restarts."""

    def __init__(self) -> None:
        super().__init__(timeout=None)

    @discord.ui.button(label="Approve ban", style=discord.ButtonStyle.danger, emoji="🔨", custom_id="banreq:approve")
    async def approve(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await _decide(interaction, approve=True)

    @discord.ui.button(label="Deny", style=discord.ButtonStyle.secondary, emoji="✖️", custom_id="banreq:deny")
    async def deny(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await _decide(interaction, approve=False)


# ---------- cog ----------

class BanRequests(commands.Cog):
    """Lets certain members request bans that higher roles must approve."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    async def cog_load(self) -> None:
        self.bot.add_view(BanReviewView())

    @app_commands.command(name="banreq", description="Requests a ban. A higher role has to approve it.")
    @app_commands.describe(user="The user to request a ban for", reason="Why the ban is needed")
    @app_commands.guild_only()
    async def banreq(self, interaction: discord.Interaction, user: discord.User, reason: str) -> None:
        guild = interaction.guild
        requester = interaction.user

        if not REQUESTER_ROLE_ID or not REVIEW_CHANNEL_ID:
            await interaction.response.send_message(
                "Ban requests are not set up yet. The admin needs to set `BANREQ_ROLE_ID` "
                "and `BAN_REVIEW_CHANNEL_ID` in `.env`.",
                ephemeral=True,
            )
            return

        if not any(role.id == REQUESTER_ROLE_ID for role in requester.roles):
            await interaction.response.send_message(
                "You don't have permission to request bans.", ephemeral=True
            )
            return

        if user.id == requester.id:
            await interaction.response.send_message("You can't request a ban for yourself.", ephemeral=True)
            return
        if user.id == self.bot.user.id:
            await interaction.response.send_message("You can't request a ban for me.", ephemeral=True)
            return
        if user.id == guild.owner_id:
            await interaction.response.send_message("The server owner can't be banned.", ephemeral=True)
            return

        target = guild.get_member(user.id)
        if target is not None and target.top_role >= requester.top_role:
            await interaction.response.send_message(
                "You can't request a ban for someone with an equal or higher role than yours.", ephemeral=True
            )
            return

        if _has_pending_for(guild.id, user.id):
            await interaction.response.send_message(
                "There is already an open ban request for this user.", ephemeral=True
            )
            return

        channel = guild.get_channel(REVIEW_CHANNEL_ID)
        if channel is None:
            await interaction.response.send_message(
                "The review channel was not found. Please tell an admin.", ephemeral=True
            )
            return

        request = {
            "message_id": 0,
            "guild_id": guild.id,
            "channel_id": channel.id,
            "requester_id": requester.id,
            "target_id": user.id,
            "reason": reason,
            "status": "pending",
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        message = await channel.send(
            embed=_review_embed(request, "Pending – waiting for a higher role", style.WARNING),
            view=BanReviewView(),
        )
        request["message_id"] = message.id
        _add(request)

        await interaction.response.send_message(
            f"Your ban request for {user.mention} was sent to {channel.mention}.", ephemeral=True
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(BanRequests(bot))
