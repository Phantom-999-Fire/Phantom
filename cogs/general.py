import discord
from discord import app_commands
from discord.ext import commands
from cogs import _style as style


class General(commands.Cog):
    """General slash commands."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="ping", description="Shows the bot's response time.")
    async def ping(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_message(
            f"Pong! {round(self.bot.latency * 1000)} ms"
        )

    @app_commands.command(name="serverinfo", description="Shows information about this server.")
    @app_commands.guild_only()
    async def serverinfo(self, interaction: discord.Interaction) -> None:
        guild = interaction.guild
        embed = discord.Embed(title=guild.name, color=style.INFO)
        embed.add_field(name="Members", value=str(guild.member_count))
        embed.add_field(name="Created on", value=discord.utils.format_dt(guild.created_at, "D"))
        if guild.icon:
            embed.set_thumbnail(url=guild.icon.url)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="help", description="Lists all available commands.")
    async def help_command(self, interaction: discord.Interaction) -> None:
        lines = [
            f"**/{cmd.name}** – {cmd.description}"
            for cmd in sorted(self.bot.tree.get_commands(), key=lambda c: c.name)
        ]
        embed = discord.Embed(
            title="Commands",
            description="\n".join(lines) or "No commands available.",
            color=style.INFO,
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(General(bot))
