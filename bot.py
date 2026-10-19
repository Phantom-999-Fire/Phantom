import asyncio
import os
import traceback

import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv

load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")

# Intents bestimmen, welche Events der Bot empfängt.
# "members" und "message_content" musst du zusätzlich im Developer Portal aktivieren.
intents = discord.Intents.default()
intents.members = True
intents.message_content = True


async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.MissingPermissions):
        message = "Dafür fehlen dir die nötigen Rechte."
    elif isinstance(error, app_commands.CommandOnCooldown):
        message = f"Bitte warte noch {error.retry_after:.0f} Sekunden."
    else:
        traceback.print_exception(type(error), error, error.__traceback__)
        message = "Es ist ein Fehler aufgetreten."

    if interaction.response.is_done():
        await interaction.followup.send(message, ephemeral=True)
    else:
        await interaction.response.send_message(message, ephemeral=True)


class MyBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix="!", intents=intents)
        self.tree.on_error = on_app_command_error

    async def setup_hook(self):
        # Lädt alle Module (Cogs) aus dem Ordner cogs/
        for filename in os.listdir("./cogs"):
            if filename.endswith(".py") and not filename.startswith("_"):
                await self.load_extension(f"cogs.{filename[:-3]}")
                print(f"Cog geladen: {filename}")

        # Registriert die Slash-Commands bei Discord
        await self.tree.sync()

    async def on_ready(self):
        print(f"Eingeloggt als {self.user} (ID: {self.user.id})")


async def main():
    bot = MyBot()
    async with bot:
        await bot.start(TOKEN)


if __name__ == "__main__":
    asyncio.run(main())

