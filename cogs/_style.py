"""Shared colours for all bot messages (minimal style).

Use these instead of discord.Color.* so every embed looks the same:

    from cogs import _style as style
    embed = discord.Embed(title="Done", color=style.SUCCESS)

This file starts with "_", so the bot does not load it as a module.
"""

import discord

INFO = discord.Color.from_rgb(59, 130, 246)      # blue: general information (main colour)
SUCCESS = discord.Color.from_rgb(34, 197, 94)    # green: something worked
WARNING = discord.Color.from_rgb(245, 158, 11)   # amber: pending or needs attention
ERROR = discord.Color.from_rgb(239, 68, 68)      # red: something failed
