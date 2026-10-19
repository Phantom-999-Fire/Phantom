import os
import discord
from discord import app_commands

intents = discord.Intents.default()
client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)

@tree.command(name="ping", description="Antwortet mit Pong!")
async def ping(interaction: discord.Interaction):
    await interaction.response.send_message("Pong!")

@client.event
async def on_ready():
    await tree.sync()
    print(f"Online als {client.user}")

client.run(os.environ["DISCORD_TOKEN"])
