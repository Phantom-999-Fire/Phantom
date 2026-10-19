import asyncio
import logging
import re
from datetime import datetime, timedelta, timezone

import discord
from discord import app_commands
from discord.ext import commands
from cogs import _style as style

log = logging.getLogger("bot.dmreminder")

UNITS = {"s": 1, "m": 60, "h": 3600, "d": 86400}
DURATION_RE = re.compile(r"^(\d+)([smhd])$", re.IGNORECASE)
MAX_SECONDS = 30 * 86400  # 30 days


def parse_delay(text: str) -> int | None:
    """Turns '30s', '10m', '2h' or '1d' into seconds. Returns None if invalid."""
    match = DURATION_RE.match(text.strip())
    if not match:
        return None
    seconds = int(match.group(1)) * UNITS[match.group(2).lower()]
    if seconds < 10 or seconds > MAX_SECONDS:
        return None
    return seconds


async def _send_dm(user: discord.User, content: str) -> tuple[bool, str]:
    """Tries to send a DM. Returns (success, reason)."""
    try:
        await user.send(content)
        return True, ""
    except discord.Forbidden:
        return False, "Their DMs are closed, or they have blocked the bot."
    except discord.HTTPException:
        log.exception("Could not send DM to %s", user.id)
        return False, "Discord returned an error. Please try again."


def _status_embed(user: discord.User, ok: bool, reason: str) -> discord.Embed:
    if ok:
        return discord.Embed(
            title="Reminder delivered",
            description=f"The DM reached {user.mention}.",
            color=style.SUCCESS,
        )
    return discord.Embed(
        title="Reminder not delivered",
        description=f"Could not reach {user.mention}.\n**Reason:** {reason}",
        color=style.ERROR,
    )


class DMReminder(commands.Cog):
    """Sends reminders to users by DM and reports whether they arrived."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.tasks: set[asyncio.Task] = set()

    def cog_unload(self) -> None:
        for task in self.tasks:
            task.cancel()
        self.tasks.clear()

    @app_commands.command(name="remind", description="Sends a reminder to a user's DMs.")
    @app_commands.describe(
        user="Who to remind",
        message="The reminder text",
        delay="Optional: when to send, e.g. 10m, 2h or 1d (default: now)",
    )
    @app_commands.guild_only()
    @app_commands.default_permissions(manage_messages=True)
    @app_commands.checks.has_permissions(manage_messages=True)
    async def remind(
        self,
        interaction: discord.Interaction,
        user: discord.User,
        message: str,
        delay: str | None = None,
    ) -> None:
        if user.bot:
            await interaction.response.send_message("I can't send reminders to bots.", ephemeral=True)
            return

        seconds = 0
        if delay:
            parsed = parse_delay(delay)
            if parsed is None:
                await interaction.response.send_message(
                    "Invalid delay. Use e.g. `30s`, `10m`, `2h` or `1d` (10 seconds to 30 days).",
                    ephemeral=True,
                )
                return
            seconds = parsed

        content = (
            f"**Reminder** from {interaction.user.mention} "
            f"in **{interaction.guild.name}**:\n{message}"
        )

        if seconds == 0:
            ok, reason = await _send_dm(user, content)
            await interaction.response.send_message(embed=_status_embed(user, ok, reason), ephemeral=True)
            return

        send_at = datetime.now(timezone.utc) + timedelta(seconds=seconds)
        await interaction.response.send_message(
            embed=discord.Embed(
                title="Reminder scheduled",
                description=(
                    f"To: {user.mention}\n"
                    f"Sends: {discord.utils.format_dt(send_at, 'R')}\n"
                    "The result will be posted in this channel."
                ),
                color=style.INFO,
            ),
            ephemeral=True,
        )

        task = asyncio.create_task(
            self._send_later(seconds, user, content, interaction.user, interaction.channel)
        )
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)

    async def _send_later(
        self,
        seconds: int,
        user: discord.User,
        content: str,
        author: discord.abc.User,
        channel: discord.abc.Messageable,
    ) -> None:
        await asyncio.sleep(seconds)
        ok, reason = await _send_dm(user, content)
        try:
            await channel.send(
                f"{author.mention}, your scheduled reminder for {user.mention}:",
                embed=_status_embed(user, ok, reason),
            )
        except discord.HTTPException:
            log.exception("Could not post the reminder result in the channel")


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(DMReminder(bot))
