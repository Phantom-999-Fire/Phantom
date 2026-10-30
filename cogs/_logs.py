"""Shared logging: mod actions and ticket transcripts.

This file starts with "_", so the bot does not load it as a module.
Other cogs import it like this:

    from cogs import _logs as logs

    await logs.log_mod_action(guild, "Ban", moderator, target_id=user.id, reason="Spam")
    await logs.save_transcript(channel, closed_by)

Every mod action is appended to data/mod_log.jsonl. Transcripts are saved to data/transcripts/.
If MOD_LOG_CHANNEL_ID or TRANSCRIPT_CHANNEL_ID is set, the same information is also posted there.
"""

import io
import json
import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path

import discord
from cogs import _style as style

log = logging.getLogger("bot.logs")

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
MOD_LOG_FILE = DATA_DIR / "mod_log.jsonl"
TRANSCRIPT_DIR = DATA_DIR / "transcripts"


def _env_id(name: str) -> int:
    value = os.getenv(name, "").strip()
    return int(value) if value.isdigit() else 0


MOD_LOG_CHANNEL_ID = _env_id("MOD_LOG_CHANNEL_ID")        # where mod actions are posted
TRANSCRIPT_CHANNEL_ID = _env_id("TRANSCRIPT_CHANNEL_ID")  # where ticket transcripts are posted


async def log_mod_action(
    guild: discord.Guild,
    action: str,
    moderator: discord.abc.User,
    target_id: int | None = None,
    reason: str | None = None,
) -> None:
    """Saves a mod action to the file and posts it in the mod log channel."""
    now = datetime.now(timezone.utc)
    record = {
        "time": now.isoformat(),
        "guild_id": guild.id,
        "action": action,
        "moderator_id": moderator.id,
        "moderator": str(moderator),
        "target_id": target_id,
        "reason": reason,
    }
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        with MOD_LOG_FILE.open("a", encoding="utf-8") as file:
            file.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError:
        log.exception("Could not write the mod log file")

    channel = guild.get_channel(MOD_LOG_CHANNEL_ID) if MOD_LOG_CHANNEL_ID else None
    if channel is None:
        return

    embed = discord.Embed(title=action, color=style.INFO, timestamp=now)
    embed.add_field(name="Moderator", value=moderator.mention, inline=True)
    if target_id:
        embed.add_field(name="Target", value=f"<@{target_id}>", inline=True)
    if reason:
        embed.add_field(name="Reason", value=reason[:1024], inline=False)
    try:
        await channel.send(embed=embed, allowed_mentions=discord.AllowedMentions.none())
    except discord.HTTPException:
        log.exception("Could not post the mod action to the log channel")


async def save_transcript(channel: discord.TextChannel, closed_by: discord.abc.User) -> None:
    """Saves every message of a ticket to a text file and posts it in the transcript channel."""
    lines = []
    try:
        async for message in channel.history(limit=None, oldest_first=True):
            time = message.created_at.strftime("%Y-%m-%d %H:%M:%S")
            text = message.content or ""
            if message.attachments:
                text = (text + " " + " ".join(a.url for a in message.attachments)).strip()
            if not text and message.embeds:
                text = "[embed]"
            lines.append(f"[{time} UTC] {message.author} ({message.author.id}): {text}")
    except discord.HTTPException:
        log.exception("Could not read the history of %s", channel.id)
        return

    now = datetime.now(timezone.utc)
    header = (
        f"Ticket: #{channel.name}\n"
        f"Channel ID: {channel.id}\n"
        f"Closed by: {closed_by} ({closed_by.id})\n"
        f"Closed at: {now.strftime('%Y-%m-%d %H:%M:%S')} UTC\n"
        f"Messages: {len(lines)}\n"
        + "-" * 60 + "\n"
    )
    content = header + ("\n".join(lines) if lines else "(no messages)") + "\n"

    safe_name = re.sub(r"[^a-zA-Z0-9-_]", "-", channel.name)[:60]
    filename = f"{now.strftime('%Y%m%d-%H%M%S')}-{safe_name}.txt"
    try:
        TRANSCRIPT_DIR.mkdir(parents=True, exist_ok=True)
        (TRANSCRIPT_DIR / filename).write_text(content, encoding="utf-8")
    except OSError:
        log.exception("Could not save the transcript file")

    log_channel = channel.guild.get_channel(TRANSCRIPT_CHANNEL_ID) if TRANSCRIPT_CHANNEL_ID else None
    if log_channel is None:
        return

    embed = discord.Embed(title="Ticket closed", color=style.INFO, timestamp=now)
    embed.add_field(name="Ticket", value=f"#{channel.name}", inline=True)
    embed.add_field(name="Closed by", value=closed_by.mention, inline=True)
    embed.add_field(name="Messages", value=str(len(lines)), inline=True)
    file = discord.File(io.BytesIO(content.encode("utf-8")), filename=filename)
    try:
        await log_channel.send(embed=embed, file=file, allowed_mentions=discord.AllowedMentions.none())
    except discord.HTTPException:
        log.exception("Could not post the transcript to the log channel")
