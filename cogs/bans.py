import logging

import discord
from discord import app_commands
from discord.ext import commands
from cogs import _style as style
from cogs import _logs as logs

log = logging.getLogger("bot.bans")


class Bans(commands.Cog):
    """Ban and unban users."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="ban", description="Bans a user from the server.")
    @app_commands.describe(
        user="The user to ban",
        reason="Why they are banned (saved in the audit log)",
        delete_days="Also delete their messages from the last 0 to 7 days",
    )
    @app_commands.guild_only()
    @app_commands.default_permissions(ban_members=True)
    @app_commands.checks.has_permissions(ban_members=True)
    async def ban(
        self,
        interaction: discord.Interaction,
        user: discord.User,
        reason: str = "No reason given",
        delete_days: app_commands.Range[int, 0, 7] = 0,
    ) -> None:
        guild = interaction.guild
        moderator = interaction.user

        if user.id == moderator.id:
            await interaction.response.send_message("You can't ban yourself.", ephemeral=True)
            return
        if user.id == self.bot.user.id:
            await interaction.response.send_message("I can't ban myself.", ephemeral=True)
            return
        if user.id == guild.owner_id:
            await interaction.response.send_message("You can't ban the server owner.", ephemeral=True)
            return

        member = guild.get_member(user.id)
        if member is not None:
            if moderator.id != guild.owner_id and member.top_role >= moderator.top_role:
                await interaction.response.send_message(
                    "You can't ban someone with an equal or higher role than yours.", ephemeral=True
                )
                return
            if member.top_role >= guild.me.top_role:
                await interaction.response.send_message(
                    "I can't ban someone with a role equal to or higher than mine.", ephemeral=True
                )
                return

        try:
            await guild.ban(
                user,
                reason=f"{reason} (by {moderator})",
                delete_message_seconds=delete_days * 86400,
            )
        except discord.Forbidden:
            await interaction.response.send_message(
                "I don't have permission to ban that user.", ephemeral=True
            )
            return
        except discord.HTTPException:
            log.exception("Could not ban %s", user.id)
            await interaction.response.send_message("The ban failed. Please try again.", ephemeral=True)
            return

        await logs.log_mod_action(guild, "Ban", moderator, target_id=user.id, reason=reason)
        await interaction.response.send_message(
            f"Banned {user.mention} (`{user}`). Reason: {reason}"
        )

    @app_commands.command(name="unban", description="Removes a ban by user ID.")
    @app_commands.describe(
        user_id="The ID of the user to unban (right-click the user → Copy User ID)",
        reason="Why the ban is removed",
    )
    @app_commands.guild_only()
    @app_commands.default_permissions(ban_members=True)
    @app_commands.checks.has_permissions(ban_members=True)
    async def unban(
        self,
        interaction: discord.Interaction,
        user_id: str,
        reason: str = "No reason given",
    ) -> None:
        if not user_id.strip().isdigit():
            await interaction.response.send_message("Invalid user ID.", ephemeral=True)
            return

        try:
            user = await self.bot.fetch_user(int(user_id))
        except discord.NotFound:
            await interaction.response.send_message("No user found with that ID.", ephemeral=True)
            return

        try:
            await interaction.guild.unban(user, reason=f"{reason} (by {interaction.user})")
        except discord.NotFound:
            await interaction.response.send_message(f"`{user}` is not banned.", ephemeral=True)
            return
        except discord.Forbidden:
            await interaction.response.send_message(
                "I don't have permission to unban users.", ephemeral=True
            )
            return

        await logs.log_mod_action(
            interaction.guild, "Unban", interaction.user, target_id=user.id, reason=reason
        )
        await interaction.response.send_message(f"Unbanned `{user}`. Reason: {reason}")


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Bans(bot))
