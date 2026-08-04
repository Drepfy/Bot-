"""AI chat for Catalyst SMP.

Answers via a private thread so channels don't get spammed.
"""

import logging

import discord
from discord import app_commands
from discord.ext import commands

import config

log = logging.getLogger("catalyst.ai")

SYSTEM_PROMPT = (
    "You are Catalyst, a friendly and helpful assistant for the Catalyst SMP "
    "Discord server. Be concise, helpful, and match the user's language."
)


@app_commands.guild_only()
class AIChat(commands.GroupCog, name="ai"):
    """Chat with Catalyst's AI."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self._client = None
        if config.AI_ENABLED and config.OPENAI_API_KEY:
            self._client = self._build_client()

    def _build_client(self):
        try:
            from openai import AsyncOpenAI
        except ImportError:
            log.warning("openai package not installed; AI chat disabled")
            return None
        return AsyncOpenAI(api_key=config.OPENAI_API_KEY, base_url=config.OPENAI_BASE_URL)

    @app_commands.command(name="ask", description="Ask Catalyst AI a question.")
    @app_commands.describe(prompt="What you want to ask")
    async def ask(
        self, interaction: discord.Interaction, prompt: str
    ) -> None:
        if self._client is None:
            await interaction.response.send_message(
                ":x: AI is not configured. Add an `OPENAI_API_KEY` to the `.env` file.",
                ephemeral=True,
            )
            return

        await interaction.response.defer(thinking=True)

        try:
            thread = await interaction.channel.create_thread(
                name=f"Catalyst • {interaction.user.display_name}",
                message=interaction.message if interaction.message else None,
                auto_archive_duration=60,
            )
        except discord.Forbidden:
            await interaction.followup.send(
                ":x: I need the *Create Public Threads* permission in this channel.",
                ephemeral=True,
            )
            return
        except Exception:
            await interaction.followup.send(
                ":x: Could not create a thread here.", ephemeral=True
            )
            return

        await interaction.followup.send(
            f"Answering in {thread.mention}. Ask follow-ups in the thread."
        )

        async with thread.typing():
            answer = await self._generate(prompt)

        await thread.send(f"{interaction.user.mention} {answer}")

    async def _generate(self, prompt: str) -> str:
        try:
            response = await self._client.chat.completions.create(
                model=config.AI_MODEL,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                max_tokens=800,
            )
            return response.choices[0].message.content.strip() or "_No response._"
        except Exception as exc:
            log.warning("AI request failed: %s", exc)
            return f":warning: The AI call failed. ({exc})"


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(AIChat(bot))
