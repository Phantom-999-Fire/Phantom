import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

import discord
from discord import app_commands
from discord.ext import commands
from cogs import _style as style

log = logging.getLogger("bot.applications")

DATA_FILE = Path(__file__).resolve().parent.parent / "data" / "applications.json"


# ---- The application questions (edit here) ----
# "label" is the short field title in the form (max. 45 characters).
# "text" is the full question, shown to the applicant before each part.
QUESTIONS = [
    {"n": 1, "key": "q1", "label": "Age", "text": "How old are you?"},
    {"n": 2, "key": "q2", "label": "Time in our Discord", "text": "How long have you been in our Discord?"},
    {"n": 3, "key": "q3", "label": "Activity on Discord & Donut SMP", "text": "How active are you on Discord and Donut SMP?"},
    {"n": 4, "key": "q4", "label": "Why General Support?", "text": "Why do you want to join the General Support Team?"},
    {"n": 5, "key": "q5", "label": "Previous Staff/mod experience", "text": "Do you have any previous Staff or moderation experience?"},
    {"n": 6, "key": "q6", "label": "What makes a good staff member", "text": "What makes a good Staff member?"},
    {"n": 7, "key": "q7", "label": "Disrespectful user", "text": "How would you handle a user who is being disrespectful towards you?"},
    {"n": 8, "key": "q8", "label": "Two users arguing", "text": "Two users are arguing, and both claim the other person is at fault. What would you do?"},
    {"n": 9, "key": "q9", "label": "Friend breaks a rule", "text": "A friend of yours breaks a server rule. How would you handle it?"},
    {"n": 10, "key": "q10", "label": "Unsure about a rule", "text": "What would you do if you were unsure about a rule or punishment?"},
    {"n": 11, "key": "q11", "label": "Same question again", "text": "How would you handle a user who keeps asking the same question after you have already answered it?"},
    {"n": 12, "key": "q12", "label": "Staff treating user unfairly", "text": "What would you do if another Staff member was treating a user unfairly?"},
    {"n": 13, "key": "q13", "label": "Time you can dedicate", "text": "How much time can you regularly dedicate to General Support?"},
]
# Discord forms hold max. 5 fields, so the questions are split into parts.
PAGES = [QUESTIONS[0:5], QUESTIONS[5:10], QUESTIONS[10:13]]


def _env_id(name: str) -> int:
    value = os.getenv(name, "").strip()
    return int(value) if value.isdigit() else 0


REVIEW_CHANNEL_ID = _env_id("APPLICATION_REVIEW_CHANNEL_ID")  # where applications are posted
STAFF_ROLE_ID = _env_id("STAFF_ROLE_ID")                      # role given when accepted

# Answers of applications in progress, per user (in memory until submitted)
_drafts: dict[int, dict[str, str]] = {}


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


def _pending_for(guild_id: int, user_id: int) -> bool:
    return any(
        item["guild_id"] == guild_id and item["user_id"] == user_id and item["status"] == "pending"
        for item in _load()
    )


# ---------- embeds ----------

def _page_embed(page: int) -> discord.Embed:
    lines = [f"**{q['n']}.** {q['text']}" for q in PAGES[page]]
    return discord.Embed(
        title=f"General Support application – Part {page + 1} of {len(PAGES)}",
        description="\n\n".join(lines) + "\n\nPress **Continue** to answer these questions.",
        color=style.INFO,
    )


def _header_embed(application: dict, status: str, color: discord.Color) -> discord.Embed:
    embed = discord.Embed(title="General Support Application", color=color)
    embed.add_field(name="Applicant", value=f"<@{application['user_id']}> (`{application['user_id']}`)", inline=False)
    embed.add_field(name="Status", value=status, inline=False)
    return embed


# ---------- modal and buttons ----------

class ApplyModal(discord.ui.Modal):
    def __init__(self, page: int) -> None:
        super().__init__(title=f"General Support – Part {page + 1}/{len(PAGES)}", timeout=None)
        self.page = page
        self.fields: list[tuple[str, discord.ui.TextInput]] = []
        for q in PAGES[page]:
            field = discord.ui.TextInput(
                label=f"{q['n']}. {q['label']}",
                style=discord.TextStyle.paragraph,
                max_length=1000,
                required=True,
            )
            self.add_item(field)
            self.fields.append((q["key"], field))

    async def on_submit(self, interaction: discord.Interaction) -> None:
        draft = _drafts.setdefault(interaction.user.id, {})
        for key, field in self.fields:
            draft[key] = field.value.strip()

        if self.page + 1 < len(PAGES):
            await interaction.response.send_message(
                embed=_page_embed(self.page + 1),
                view=PageButtonView(self.page + 1),
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True, thinking=True)
        answers = _drafts.pop(interaction.user.id, {})
        if len(answers) != len(QUESTIONS):
            await interaction.followup.send(
                "Your application session expired. Please start again with the Apply button.",
                ephemeral=True,
            )
            return
        await _submit(interaction, answers)


class PageButtonView(discord.ui.View):
    def __init__(self, page: int) -> None:
        super().__init__(timeout=900)
        self.page = page

    @discord.ui.button(label="Continue", style=discord.ButtonStyle.primary, emoji="✏️")
    async def continue_(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.send_modal(ApplyModal(self.page))


async def _submit(interaction: discord.Interaction, answers: dict[str, str]) -> None:
    guild = interaction.guild
    channel = guild.get_channel(REVIEW_CHANNEL_ID)
    if channel is None:
        await interaction.followup.send(
            "Applications are not set up yet. Please tell an admin.", ephemeral=True
        )
        return

    record = {
        "message_id": 0,
        "guild_id": guild.id,
        "channel_id": channel.id,
        "user_id": interaction.user.id,
        "status": "pending",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "answers": answers,
    }
    header = await channel.send(
        embed=_header_embed(record, "Pending – waiting for a decision", style.WARNING),
        view=ApplicationReviewView(),
    )
    record["message_id"] = header.id
    _add(record)

    # Answers go into embeds of 4 questions each, to stay under Discord's size limits.
    for start in range(0, len(QUESTIONS), 4):
        embed = discord.Embed(color=style.INFO)
        for q in QUESTIONS[start:start + 4]:
            embed.add_field(name=f"{q['n']}. {q['label']}", value=answers[q["key"]][:1024], inline=False)
        await channel.send(embed=embed)

    await interaction.followup.send(
        "Your application was submitted. You will get a DM when it has been reviewed.",
        ephemeral=True,
    )


async def _decide(interaction: discord.Interaction, approve: bool) -> None:
    await interaction.response.defer()

    application = _get(interaction.message.id)
    if application is None or application["status"] != "pending":
        await interaction.followup.send("This application is no longer open.", ephemeral=True)
        return

    guild = interaction.guild
    decider = interaction.user
    if not (decider.guild_permissions.manage_guild or decider.id == guild.owner_id):
        await interaction.followup.send(
            "Only members with the Manage Server permission can decide applications.", ephemeral=True
        )
        return
    if decider.id == application["user_id"]:
        await interaction.followup.send("You can't decide your own application.", ephemeral=True)
        return

    applicant = guild.get_member(application["user_id"])

    if approve:
        role = guild.get_role(STAFF_ROLE_ID) if STAFF_ROLE_ID else None
        if role is None:
            await interaction.followup.send(
                "The staff role is not set up. Please set `STAFF_ROLE_ID` in `.env`.", ephemeral=True
            )
            return
        if applicant is None:
            await interaction.followup.send(
                "The applicant is no longer on the server.", ephemeral=True
            )
            return
        try:
            await applicant.add_roles(role, reason=f"Application accepted by {decider}")
        except discord.Forbidden:
            await interaction.followup.send(
                "I can't give out that role. Check that my role is above the staff role.", ephemeral=True
            )
            return
        status = f"Accepted by {decider.mention}"
        color = style.SUCCESS
        dm_text = f"Your General Support application on **{guild.name}** was accepted. Welcome to the team!"
        new_status = "approved"
    else:
        status = f"Denied by {decider.mention}"
        color = style.ERROR
        dm_text = f"Your General Support application on **{guild.name}** was not accepted this time."
        new_status = "denied"

    _update(interaction.message.id, status=new_status, decided_by=decider.id)

    try:
        user = await interaction.client.fetch_user(application["user_id"])
        await user.send(dm_text)
    except discord.HTTPException:
        log.info("Could not DM applicant %s about the decision", application["user_id"])

    await interaction.edit_original_response(
        embed=_header_embed(application, status, color),
        view=None,
    )


class ApplicationReviewView(discord.ui.View):
    """Buttons under each application. Persistent, so they work after a restart."""

    def __init__(self) -> None:
        super().__init__(timeout=None)

    @discord.ui.button(label="Accept", style=discord.ButtonStyle.success, emoji="✅", custom_id="apply:approve")
    async def approve(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await _decide(interaction, approve=True)

    @discord.ui.button(label="Deny", style=discord.ButtonStyle.danger, emoji="✖️", custom_id="apply:deny")
    async def deny(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await _decide(interaction, approve=False)


class ApplyPanelView(discord.ui.View):
    """The panel with the Apply button. Persistent, so it works after a restart."""

    def __init__(self) -> None:
        super().__init__(timeout=None)

    @discord.ui.button(label="Apply for General Support", style=discord.ButtonStyle.primary, emoji="📝", custom_id="apply:start")
    async def start(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not REVIEW_CHANNEL_ID:
            await interaction.response.send_message(
                "Applications are not set up yet. Please tell an admin.", ephemeral=True
            )
            return

        member = interaction.user
        if STAFF_ROLE_ID and any(role.id == STAFF_ROLE_ID for role in member.roles):
            await interaction.response.send_message("You already have the staff role.", ephemeral=True)
            return
        if _pending_for(interaction.guild_id, member.id):
            await interaction.response.send_message(
                "You already have an application under review.", ephemeral=True
            )
            return

        _drafts[member.id] = {}
        await interaction.response.send_message(
            embed=_page_embed(0), view=PageButtonView(0), ephemeral=True
        )


# ---------- cog ----------

class Applications(commands.Cog):
    """Staff applications with questions, review buttons and automatic role assignment."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    async def cog_load(self) -> None:
        self.bot.add_view(ApplyPanelView())
        self.bot.add_view(ApplicationReviewView())

    @app_commands.command(name="applypanel", description="Posts the staff application panel in this channel.")
    @app_commands.guild_only()
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.checks.has_permissions(manage_guild=True)
    async def applypanel(self, interaction: discord.Interaction) -> None:
        embed = discord.Embed(
            title="General Support – Apply",
            description=(
                "Want to join the General Support Team? Press the button below.\n"
                "The application has 13 questions and takes a few minutes."
            ),
            color=style.INFO,
        )
        await interaction.channel.send(embed=embed, view=ApplyPanelView())
        await interaction.response.send_message("Application panel posted.", ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Applications(bot))
