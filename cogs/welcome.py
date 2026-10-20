import logging
import os

import discord
from discord.ext import commands
from cogs import _style as style

log = logging.getLogger("bot.welcome")

# Optional: set WELCOME_CHANNEL_ID in .env to choose the channel.
# If it is not set, the server's system channel is used.
WELCOME_CHANNEL_ID = os.getenv("WELCOME_CHANNEL_ID")

WELCOME_MESSAGE = (
    "Welcome to **{server}**, {member}! \n"
    "We're glad you're here. Feel free to introduce yourself and say hi."
)


class Welcome(commands.Cog):
    """Greets new members when they join the server."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    def _get_channel(self, guild: discord.Guild) -> discord.abc.Messageable | None:
        if WELCOME_CHANNEL_ID and WELCOME_CHANNEL_ID.isdigit():
            channel = guild.get_channel(int(WELCOME_CHANNEL_ID))
            if channel is not None:
                return channel
        return guild.system_channel

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member) -> None:
        if member.bot:
            return
        channel = self._get_channel(member.guild)
        if channel is None:
            log.warning("No welcome channel found in %s", member.guild.name)
            return
        try:
            await channel.send(
                WELCOME_MESSAGE.format(server=member.guild.name, member=member.mention)
            )
        except discord.Forbidden:
            log.warning("Missing permission to send in %s", channel)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Welcome(bot))
