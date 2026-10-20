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

EMOJI = "🎉"
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


class Giveaway(commands.Cog):
    """Giveaways with a timer, automatic winner selection and history."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.tasks: dict[int, asyncio.Task] = {}  # message_id -> task

    async def cog_load(self) -> None:
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
        embed = discord.Embed(
            title=prize.upper(),
            description=f"React with {EMOJI} to enter!",
            color=style.INFO,
        )
        embed.add_field(name="Ends", value=discord.utils.format_dt(ends_at, "R"), inline=True)
        embed.add_field(name="Winners", value=str(winners), inline=True)
        embed.add_field(name="Hosted by", value=interaction.user.mention, inline=True)

        await interaction.response.send_message(embed=embed)
        message = await interaction.original_response()
        await message.add_reaction(EMOJI)

        store.add({
            "message_id": message.id,
            "channel_id": message.channel.id,
            "guild_id": interaction.guild_id,
            "host_id": interaction.user.id,
            "prize": prize,
            "winners_count": winners,
            "created_at": now.isoformat(),
            "ends_at": ends_at.isoformat(),
            "status": "active",
            "winner_ids": [],
        })
        self._schedule(message.id, seconds)

    async def _finish(self, message_id: int, seconds: float) -> None:
        try:
            await asyncio.sleep(seconds)

            entry = store.get(message_id)
            if entry is None or entry["status"] != "active":
                return

            channel = self.bot.get_channel(entry["channel_id"]) or await self.bot.fetch_channel(
                entry["channel_id"]
            )
            message = await channel.fetch_message(message_id)
            reaction = discord.utils.get(message.reactions, emoji=EMOJI)
            entrants = []
            if reaction is not None:
                entrants = [user async for user in reaction.users() if not user.bot]

            picked = random.sample(entrants, min(entry["winners_count"], len(entrants)))
            store.update(message_id, status="ended", winner_ids=[user.id for user in picked])

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
                value=", ".join(user.mention for user in picked) if picked else "Nobody entered",
                inline=False,
            )
            await message.edit(embed=ended)

            if picked:
                mentions = ", ".join(user.mention for user in picked)
                await channel.send(
                    f"Congratulations {mentions}! You won **{entry['prize']}**!"
                )
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
