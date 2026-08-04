"""Catalyst SMP Discord bot."""

import logging
import os
from pathlib import Path

import discord
from discord.ext import commands

import config

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
log = logging.getLogger("catalyst")

PID_FILE = Path(__file__).resolve().parent / "data" / "bot.pid"


def _write_pid() -> None:
    try:
        PID_FILE.parent.mkdir(exist_ok=True, parents=True)
        PID_FILE.write_text(str(os.getpid()), encoding="utf-8")
    except OSError:
        pass


def _clear_pid() -> None:
    try:
        if PID_FILE.exists():
            PID_FILE.unlink()
    except OSError:
        pass


class CatalystSMP(commands.Bot):
    def __init__(self) -> None:
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True

        super().__init__(
            command_prefix=commands.when_mentioned_or(config.PREFIX),
            intents=intents,
            activity=discord.Activity(
                type=discord.ActivityType.watching, name="over Catalyst SMP"
            ),
        )

        self.initial_extensions = (
            "cogs.moderation",
            "cogs.utility",
            "cogs.tickets",
            "cogs.partner",
        )

    async def setup_hook(self) -> None:
        for extension in self.initial_extensions:
            await self.load_extension(extension)
            log.info("Loaded extension: %s", extension)

    async def on_ready(self) -> None:
        log.info("Logged in as %s (ID: %s)", self.user, self.user.id)
        log.info("Serving %s guilds", len(self.guilds))
        try:
            synced = await self.tree.sync()
            log.info("Synced %s global commands", len(synced))
        except Exception as exc:
            log.warning("Failed to sync global commands: %s", exc)

    async def on_command_error(
        self, ctx: commands.Context, error: commands.CommandError
    ) -> None:
        if isinstance(error, commands.MissingPermissions):
            await ctx.send(
                ":x: **drepfy** — you are not authorized to use this command."
            )
            return
        log.warning("Command error: %s", error)


def main() -> None:
    _write_pid()
    log.info("Wrote PID file: %s", PID_FILE)
    bot = CatalystSMP()
    try:
        bot.run(config.TOKEN)
    finally:
        _clear_pid()
        log.info("Removed PID file")


if __name__ == "__main__":
    main()
