import json
import logging
import os
import re
from pathlib import Path

import discord
from discord import app_commands
from discord.ext import commands
from cogs import _style as style

log = logging.getLogger("bot.sponsors")

DATA_FILE = Path(__file__).resolve().parent.parent / "data" / "sponsors.json"
MULTIPLIERS = {"": 1, "k": 1_000, "m": 1_000_000, "b": 1_000_000_000}
AMOUNT_RE = re.compile(r"^(\d+(?:[.,]\d+)?)\s*([kmb]?)$", re.IGNORECASE)
TOP_N = 10
MEDALS = ["🥇", "🥈", "🥉"]


def parse_amount(text: str) -> int | None:
    """Turns '100m', '2.5k', '1b' or '5000' into an integer. Returns None if invalid."""
    match = AMOUNT_RE.match(text.strip())
    if not match:
        return None
    number = float(match.group(1).replace(",", "."))
    value = round(number * MULTIPLIERS[match.group(2).lower()])
    return value if value > 0 else None


def format_amount(value: int) -> str:
    for suffix, factor in (("b", 1e9), ("m", 1e6), ("k", 1e3)):
        if value >= factor:
            return f"{value / factor:g}{suffix}"
    return str(value)


def _load() -> dict:
    try:
        return json.loads(DATA_FILE.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except json.JSONDecodeError:
        log.exception("%s is corrupted, starting with an empty file", DATA_FILE)
        return {}


def _save(data: dict) -> None:
    DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = DATA_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    os.replace(tmp, DATA_FILE)  # Atomic replace, so a crash cannot corrupt the file


def add_amount(guild_id: int, user_id: int, amount: int) -> int:
    data = _load()
    guild = data.setdefault(str(guild_id), {})
    guild[str(user_id)] = guild.get(str(user_id), 0) + amount
    _save(data)
    return guild[str(user_id)]


def remove_amount(guild_id: int, user_id: int, amount: int) -> int | None:
    """Subtracts from a sponsor's total. Returns the new total, or None if not a sponsor."""
    data = _load()
    guild = data.get(str(guild_id), {})
    current = guild.get(str(user_id))
    if current is None:
        return None
    new_total = max(0, current - amount)
    if new_total == 0:
        guild.pop(str(user_id), None)
    else:
        guild[str(user_id)] = new_total
    _save(data)
    return new_total


def leaderboard(guild_id: int, limit: int = TOP_N) -> list[tuple[int, int]]:
    guild = _load().get(str(guild_id), {})
    ranked = sorted(
        ((int(user_id), total) for user_id, total in guild.items()),
        key=lambda item: item[1],
        reverse=True,
    )
    return ranked[:limit]


class Sponsors(commands.Cog):
    """Tracks giveaway sponsors and shows a leaderboard."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="addsponsorship", description="Adds a sponsorship amount to a user.")
    @app_commands.describe(
        user="The sponsor",
        amount="Amount, e.g. 100m, 2.5k, 1b or 5000",
    )
    @app_commands.guild_only()
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.checks.has_permissions(manage_guild=True)
    async def addsponsorship(
        self, interaction: discord.Interaction, user: discord.Member, amount: str
    ) -> None:
        value = parse_amount(amount)
        if value is None:
            await interaction.response.send_message(
                "Invalid amount. Use e.g. `100m`, `2.5k`, `1b` or `5000`.", ephemeral=True
            )
            return

        total = add_amount(interaction.guild_id, user.id, value)
        await interaction.response.send_message(
            f"Added **{format_amount(value)}** sponsorship for {user.mention}. "
            f"New total: **{format_amount(total)}**"
        )

    @app_commands.command(name="removesponsorship", description="Subtracts a sponsorship amount from a user.")
    @app_commands.describe(
        user="The sponsor",
        amount="Amount to subtract, e.g. 100m, 2.5k, 1b or 5000",
    )
    @app_commands.guild_only()
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.checks.has_permissions(manage_guild=True)
    async def removesponsorship(
        self, interaction: discord.Interaction, user: discord.Member, amount: str
    ) -> None:
        value = parse_amount(amount)
        if value is None:
            await interaction.response.send_message(
                "Invalid amount. Use e.g. `100m`, `2.5k`, `1b` or `5000`.", ephemeral=True
            )
            return

        total = remove_amount(interaction.guild_id, user.id, value)
        if total is None:
            await interaction.response.send_message(
                f"{user.mention} has no sponsorships.", ephemeral=True
            )
            return

        message = f"Removed **{format_amount(value)}** from {user.mention}. New total: **{format_amount(total)}**"
        if total == 0:
            message = f"Removed **{format_amount(value)}** from {user.mention}. They are no longer on the leaderboard."
        await interaction.response.send_message(message)

    @app_commands.command(name="sponsorboard", description="Shows the sponsor leaderboard.")
    @app_commands.guild_only()
    async def sponsorboard(self, interaction: discord.Interaction) -> None:
        ranking = leaderboard(interaction.guild_id)
        if not ranking:
            await interaction.response.send_message("No sponsors yet.")
            return

        lines = []
        for position, (user_id, total) in enumerate(ranking, start=1):
            prefix = MEDALS[position - 1] if position <= len(MEDALS) else f"**{position}.**"
            lines.append(f"{prefix} <@{user_id}> – **{format_amount(total)}**")

        embed = discord.Embed(
            title="Sponsor Leaderboard",
            description="\n".join(lines),
            color=style.INFO,
        )
        await interaction.response.send_message(embed=embed)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Sponsors(bot))
