import asyncio
import logging
import random
import re
from datetime import datetime, timedelta, timezone

import discord
from discord import app_commands
from discord.ext import commands
from cogs import _style as style

from cogs import _giveaway_store as store

log = logging.getLogger("bot.giveaway")

UNITS = {"s": 1, "m": 60, "h": 3600, "d": 86400}
DURATION_RE = re.compile(r"^(\d+)([smhd])$", re.IGNORECASE)
MAX_SECONDS = 30 * 86400  # 30 days


def parse_duration(text: str) -> int | None:
    """Turns '30s', '10m', '2h' or '1d' into seconds. Returns None if invalid."""
    match = DURATION_RE.match(text.strip())
    if not match:
        return None
    seconds = int(match.group(1)) * UNITS[match.group(2).lower()]
    if seconds < 10 or seconds > MAX_SECONDS:
        return None
    return seconds


def active_embed(entry: dict) -> discord.Embed:
    """Embed for a running giveaway."""
    ends_at = datetime.fromisoformat(entry["ends_at"])
    embed = discord.Embed(
        title=entry["prize"].upper(),
        description="Press **Join Giveaway** below to enter.",
        color=style.INFO,
    )
    embed.add_field(name="Ends", value=discord.utils.format_dt(ends_at, "R"), inline=True)
    embed.add_field(name="Winners", value=str(entry["winners_count"]), inline=True)
    embed.add_field(name="Entries", value=str(len(entry.get("entrants", []))), inline=True)
    embed.add_field(name="Hosted by", value=f"<@{entry['host_id']}>", inline=False)
    return embed


class JoinView(discord.ui.View):
    """Button under each giveaway. Registered once at startup, so it keeps working after a restart."""

    def __init__(self) -> None:
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Join Giveaway",
        style=discord.ButtonStyle.primary,
        emoji="🎉",
        custom_id="giveaway:join",
    )
    async def join(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        entry = store.get(interaction.message.id)
        if entry is None or entry["status"] != "active":
            await interaction.response.send_message("This giveaway has ended.", ephemeral=True)
            return

        entrants = entry.get("entrants", [])
        if interaction.user.id in entrants:
            await interaction.response.send_message("You already joined this giveaway.", ephemeral=True)
            return

        entrants.append(interaction.user.id)
        store.update(interaction.message.id, entrants=entrants)
        entry["entrants"] = entrants

        await interaction.response.edit_message(embed=active_embed(entry))
        await interaction.followup.send("You joined the giveaway. Good luck!", ephemeral=True)


class Giveaway(commands.Cog):
    """Giveaways with a join button, automatic winner selection and history."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.tasks: dict[int, asyncio.Task] = {}  # message_id -> task

    async def cog_load(self) -> None:
        # Buttons of older giveaways keep working after a restart.
        self.bot.add_view(JoinView())

        # Restore giveaways that were still running when the bot last stopped.
        now = datetime.now(timezone.utc)
        restored = store.active()
        for entry in restored:
            ends_at = datetime.fromisoformat(entry["ends_at"])
            remaining = max(0.0, (ends_at - now).total_seconds())
            self._schedule(entry["message_id"], remaining)
        if restored:
            log.info("Restored %d running giveaway(s)", len(restored))

    def cog_unload(self) -> None:
        for task in self.tasks.values():
            task.cancel()
        self.tasks.clear()

    def _schedule(self, message_id: int, seconds: float) -> None:
        self.tasks[message_id] = asyncio.create_task(self._finish(message_id, seconds))

    @app_commands.command(name="giveaway", description="Starts a giveaway.")
    @app_commands.describe(
        duration="How long it runs, e.g. 30s, 10m, 2h or 1d (max 30d)",
        winners="How many winners to draw (1 to 20)",
        prize="What the winners get, e.g. 100m",
    )
    @app_commands.guild_only()
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.checks.has_permissions(manage_guild=True)
    async def giveaway(
        self,
        interaction: discord.Interaction,
        duration: str,
        winners: app_commands.Range[int, 1, 20],
        prize: str,
    ) -> None:
        seconds = parse_duration(duration)
        if seconds is None:
            await interaction.response.send_message(
                "Invalid duration. Use e.g. `30s`, `10m`, `2h` or `1d` (10 seconds to 30 days).",
                ephemeral=True,
            )
            return

        now = datetime.now(timezone.utc)
        ends_at = now + timedelta(seconds=seconds)
        entry = {
            "channel_id": interaction.channel_id,
            "guild_id": interaction.guild_id,
            "host_id": interaction.user.id,
            "prize": prize,
            "winners_count": winners,
            "created_at": now.isoformat(),
            "ends_at": ends_at.isoformat(),
            "status": "active",
            "entrants": [],
            "winner_ids": [],
        }

        await interaction.response.send_message(embed=active_embed(entry), view=JoinView())
        message = await interaction.original_response()

        entry["message_id"] = message.id
        entry["channel_id"] = message.channel.id
        store.add(entry)
        self._schedule(message.id, seconds)

    async def _finish(self, message_id: int, seconds: float) -> None:
        try:
            await asyncio.sleep(seconds)

            entry = store.get(message_id)
            if entry is None or entry["status"] != "active":
                return

            entrants = entry.get("entrants", [])
            picked = random.sample(entrants, min(entry["winners_count"], len(entrants)))
            store.update(message_id, status="ended", winner_ids=picked)

            channel = self.bot.get_channel(entry["channel_id"]) or await self.bot.fetch_channel(
                entry["channel_id"]
            )
            message = await channel.fetch_message(message_id)

            now = datetime.now(timezone.utc)
            ended = discord.Embed(
                title=entry["prize"].upper(),
                description="Giveaway ended",
                color=style.INFO,
            )
            ended.add_field(
                name="Ended",
                value=f"{discord.utils.format_dt(now, 'R')} ({discord.utils.format_dt(now, 'f')})",
                inline=False,
            )
            ended.add_field(name="Hosted by", value=f"<@{entry['host_id']}>", inline=True)
            ended.add_field(name="Entries", value=str(len(entrants)), inline=True)
            ended.add_field(
                name="Winners",
                value=", ".join(f"<@{user_id}>" for user_id in picked) if picked else "Nobody entered",
                inline=False,
            )
            await message.edit(embed=ended, view=None)

            if picked:
                mentions = ", ".join(f"<@{user_id}>" for user_id in picked)
                await channel.send(f"Congratulations {mentions}! You won **{entry['prize']}**!")
            else:
                await channel.send(f"Nobody entered the giveaway for **{entry['prize']}**.")
        except asyncio.CancelledError:
            raise
        except discord.HTTPException:
            # Message or channel is gone: close the giveaway so it is not retried forever.
            log.exception("Could not finish giveaway %s", message_id)
            store.update(message_id, status="ended")
        finally:
            self.tasks.pop(message_id, None)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Giveaway(bot))
