"""Shared colours for all bot messages (minimal style).

Use these instead of discord.Color.* so every embed looks the same:

    from cogs import _style as style
    embed = discord.Embed(title="Done", color=style.SUCCESS)

This file starts with "_", so the bot does not load it as a module.
"""

import discord

INFO = discord.Color.from_rgb(78, 80, 88)        # neutral grey: general information
SUCCESS = discord.Color.from_rgb(87, 242, 135)   # green: something worked
WARNING = discord.Color.from_rgb(254, 231, 92)   # yellow: pending or needs attention
ERROR = discord.Color.from_rgb(237, 66, 69)      # red: something failed
