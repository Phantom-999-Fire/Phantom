import logging

import discord
from discord import app_commands
from discord.ext import commands
from cogs import _style as style

log = logging.getLogger("bot.say")


class Say(commands.Cog):
    """Lets staff send their own messages through the bot."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="say", description="Sends a message through the bot.")
    @app_commands.describe(
        channel="The channel where the message is sent",
        message="The text. Type \\n for a new line.",
        title="Optional. If set, the message is sent as a blue box with this title.",
    )
    @app_commands.guild_only()
    @app_commands.default_permissions(manage_messages=True)
    @app_commands.checks.has_permissions(manage_messages=True)
    async def say(
        self,
        interaction: discord.Interaction,
        channel: discord.TextChannel,
        message: app_commands.Range[str, 1, 2000],
        title: str | None = None,
    ) -> None:
        permissions = channel.permissions_for(interaction.guild.me)
        if not (permissions.view_channel and permissions.send_messages):
            await interaction.response.send_message(
                f"I can't write in {channel.mention}. Please give me access to it.", ephemeral=True
            )
            return

        text = message.replace("\\n", "\n")
        # Users can be mentioned, but @everyone and roles are not pinged by accident.
        mentions = discord.AllowedMentions(everyone=False, roles=False, users=True)

        try:
            if title:
                embed = discord.Embed(title=title[:256], description=text[:4096], color=style.INFO)
                await channel.send(embed=embed, allowed_mentions=mentions)
            else:
                await channel.send(text, allowed_mentions=mentions)
        except discord.HTTPException:
            log.exception("Could not send /say message to %s", channel.id)
            await interaction.response.send_message("The message could not be sent.", ephemeral=True)
            return

        await interaction.response.send_message(f"Message sent to {channel.mention}.", ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Say(bot))
