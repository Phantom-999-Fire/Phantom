import logging
import os
import time

import discord
from discord import app_commands
from discord.ext import commands
from cogs import _style as style

try:
    from anthropic import AsyncAnthropic
except ImportError:  # only needed when the assistant is enabled
    AsyncAnthropic = None

from pathlib import Path

log = logging.getLogger("bot.ai")

API_KEY = os.getenv("ANTHROPIC_API_KEY", "").strip()
MODEL = os.getenv("AI_MODEL", "claude-haiku-5-5").strip()
KNOWLEDGE_FILE = Path(__file__).resolve().parent.parent / "knowledge.md"
COOLDOWN_SECONDS = 20          # per user, so one person cannot run up the API costs
MAX_QUESTION_LENGTH = 500
MAX_ANSWER_LENGTH = 3500


def _env_ids(*names: str) -> set[int]:
    ids = set()
    for name in names:
        value = os.getenv(name, "").strip()
        if value.isdigit():
            ids.add(int(value))
    return ids


# Messages in these categories get an automatic answer.
TICKET_CATEGORY_IDS = _env_ids(
    "TICKET_CATEGORY_SPAWNER_SELL_ID",
    "TICKET_CATEGORY_SPAWNER_BUY_ID",
    "TICKET_CATEGORY_SUPPORT_ID",
    "TICKET_CATEGORY_MOD_PURCHASE_ID",
    "TICKET_CATEGORY_GIVEAWAY_CLAIM_ID",
    "TICKET_CATEGORY_GIVEAWAY_SPONSOR_ID",
    "TICKET_CATEGORY_ID",
)


def build_system_prompt() -> str:
    try:
        knowledge = KNOWLEDGE_FILE.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        knowledge = ""
    return (
        "You are the support assistant of a Minecraft server's Discord. "
        "Answer briefly and friendly, in English. "
        "Use only the information in the knowledge below. "
        "If the answer is not in the knowledge, say that a staff member will answer and do not guess. "
        "Never promise prices, payments, refunds or giveaway wins. "
        "Never ask for passwords, tokens or payment details.\n\n"
        f"KNOWLEDGE:\n{knowledge}"
    )


class AI(commands.Cog):
    """Answers questions in ticket channels automatically and via /ask."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.client = AsyncAnthropic(api_key=API_KEY)
        self.last_used: dict[int, float] = {}

    def _cooldown_left(self, user_id: int) -> float:
        """Returns the seconds the user still has to wait, or 0 if they may ask now."""
        now = time.monotonic()
        last = self.last_used.get(user_id)
        if last is not None and now - last < COOLDOWN_SECONDS:
            return COOLDOWN_SECONDS - (now - last)
        self.last_used[user_id] = now
        return 0

    async def _answer(self, question: str) -> str:
        try:
            response = await self.client.messages.create(
                model=MODEL,
                max_tokens=400,
                system=build_system_prompt(),
                messages=[{"role": "user", "content": question}],
            )
            text = "\n".join(block.text for block in response.content if block.type == "text").strip()
            return text[:MAX_ANSWER_LENGTH] or "Sorry, I could not write an answer. A staff member will help you."
        except Exception:
            log.exception("AI request failed")
            return "I could not answer right now. A staff member will help you soon."

    @staticmethod
    def _embed(answer: str) -> discord.Embed:
        embed = discord.Embed(description=answer, color=style.INFO)
        embed.set_footer(text="Automatic answer. Staff will follow up if needed.")
        return embed

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if message.author.bot or message.guild is None:
            return
        if not isinstance(message.channel, discord.TextChannel):
            return
        if message.channel.category_id not in TICKET_CATEGORY_IDS:
            return
        # Staff answer themselves, so the assistant stays out of their conversations.
        if message.author.guild_permissions.manage_channels:
            return

        question = message.content.strip()
        if not question or question.startswith("/"):
            return
        if self._cooldown_left(message.author.id):
            return  # skip silently, so the ticket does not fill with cooldown messages

        async with message.channel.typing():
            answer = await self._answer(question[:MAX_QUESTION_LENGTH])
        await message.reply(embed=self._embed(answer), mention_author=False)

    @app_commands.command(name="ask", description="Ask the support assistant a question.")
    @app_commands.describe(question="Your question")
    @app_commands.guild_only()
    async def ask(
        self, interaction: discord.Interaction, question: app_commands.Range[str, 1, MAX_QUESTION_LENGTH]
    ) -> None:
        left = self._cooldown_left(interaction.user.id)
        if left:
            await interaction.response.send_message(
                f"Please wait {int(left) + 1} seconds before asking again.", ephemeral=True
            )
            return

        await interaction.response.defer()
        answer = await self._answer(question)
        await interaction.followup.send(embed=self._embed(answer))


async def setup(bot: commands.Bot) -> None:
    if not API_KEY or AsyncAnthropic is None:
        log.warning("AI assistant is off. Set ANTHROPIC_API_KEY and install the 'anthropic' package.")
        return
    await bot.add_cog(AI(bot))
