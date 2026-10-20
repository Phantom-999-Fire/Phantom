"""Template for new features.

Copy this file, rename it (e.g. cogs/polls.py) and remove the leading "_".
Every file in cogs/ without a leading "_" is loaded automatically on start.
This template itself is ignored.
"""

import discord
from discord import app_commands
from discord.ext import commands
from cogs import _style as style


class Vorlage(commands.Cog):
    """Short description of the module."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="beispiel", description="An example slash command.")
    async def beispiel(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_message("This is an example.")


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Vorlage(bot))
