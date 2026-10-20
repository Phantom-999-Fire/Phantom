"""Shared giveaway storage and claim checks.

This file starts with "_", so the bot does not load it as a module.
Other cogs (e.g. tickets) import it like this:

    from cogs import _giveaway_store as giveaways

    win = giveaways.find_recent_win(user.id)
    embed = giveaways.claim_embed(user.id, ign, amount, win)
"""

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

import discord

from cogs import _style as style

log = logging.getLogger("bot.giveaway_store")

DATA_FILE = Path(__file__).resolve().parent.parent / "data" / "giveaways.json"
RECENT_LIMIT = 20  # A claim counts as verified if the user won one of the last 20 giveaways


def _load() -> list[dict]:
    try:
        return json.loads(DATA_FILE.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return []
    except json.JSONDecodeError:
        log.exception("%s is corrupted, starting with an empty list", DATA_FILE)
        return []


def _save(items: list[dict]) -> None:
    DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = DATA_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(items, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, DATA_FILE)  # Atomic replace, so a crash cannot corrupt the file


def get(message_id: int) -> dict | None:
    for item in _load():
        if item["message_id"] == message_id:
            return item
    return None


def add(entry: dict) -> None:
    items = _load()
    items.append(entry)
    _save(items)


def update(message_id: int, **fields) -> None:
    items = _load()
    for item in items:
        if item["message_id"] == message_id:
            item.update(fields)
            break
    _save(items)


def active() -> list[dict]:
    return [item for item in _load() if item["status"] == "active"]


def recent_ended(limit: int = RECENT_LIMIT) -> list[dict]:
    ended = [item for item in _load() if item["status"] == "ended"]
    ended.sort(key=lambda item: item["created_at"], reverse=True)
    return ended[:limit]


def find_recent_win(user_id: int) -> dict | None:
    """Returns the most recent giveaway the user won among the last 20, or None."""
    for giveaway in recent_ended():
        if user_id in giveaway.get("winner_ids", []):
            return giveaway
    return None


def claim_embed(user_id: int, ign: str, amount: str, win: dict | None) -> discord.Embed:
    """Builds the verification embed for a claim ticket.

    win: result of find_recent_win(user_id). If None, the claim is marked as under review.
    amount: fallback amount, used only when there is no win.
    """
    mention = f"<@{user_id}>"
    if win is not None:
        won_on = int(datetime.fromisoformat(win["created_at"]).timestamp())
        link = (
            f"https://discord.com/channels/{win['guild_id']}/"
            f"{win['channel_id']}/{win['message_id']}"
        )
        embed = discord.Embed(
            title="Giveaway Win Confirmed",
            description=(
                f"**Opened By:** {mention}\n\n"
                f"**Prize:** {win['prize']}\n"
                f"**IGN:** {ign}\n"
                f"**Giveaway:** [Open giveaway]({link})\n"
                f"**Date:** <t:{won_on}:D>\n\n"
                "**Result**\n"
                f"Verified. The user won a giveaway in the last {RECENT_LIMIT}."
            ),
            color=style.SUCCESS,
        )
        embed.set_footer(text="Verification successful.")
    else:
        embed = discord.Embed(
            title="Under Review",
            description=(
                f"**Opened By:** {mention}\n\n"
                f"**Claimed:** {amount}\n"
                f"**IGN:** {ign}\n\n"
                "**Result**\n"
                f"No win found in the last {RECENT_LIMIT} giveaways. A staff member will review this."
            ),
            color=style.WARNING,
        )
        embed.set_footer(text="Verification pending.")
    return embed
