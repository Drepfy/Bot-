"""Moderation commands for Catalyst SMP."""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

import discord
from discord import app_commands
from discord.ext import commands

log = logging.getLogger("catalyst.moderation")

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
WARN_FILE = DATA_DIR / "warnings.json"


def _load_warnings() -> dict:
    if not WARN_FILE.exists():
        return {}
    try:
        return json.loads(WARN_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _save_warnings(data: dict) -> None:
    DATA_DIR.mkdir(exist_ok=True)
    WARN_FILE.write_text(
        json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
    )


@app_commands.guild_only()
@app_commands.default_permissions(administrator=True)
class Moderation(commands.GroupCog, name="mod"):
    """Moderation tools. Admin only."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    # ------------------------------------------------------------------
    # Purge
    # ------------------------------------------------------------------
    @app_commands.command(name="purge", description="Delete a number of messages.")
    @app_commands.checks.has_permissions(manage_messages=True)
    @app_commands.describe(count="How many messages to delete (1-100)")
    async def purge(
        self, interaction: discord.Interaction, count: int = 10
    ) -> None:
        count = max(1, min(count, 100))
        deleted = await interaction.channel.purge(limit=count)
        await interaction.response.send_message(
            f":broom: Deleted **{len(deleted)}** messages.", delete_after=5
        )

    # ------------------------------------------------------------------
    # Slowmode (single channel)
    # ------------------------------------------------------------------
    @app_commands.command(name="slowmode", description="Set slowmode on a channel.")
    @app_commands.checks.has_permissions(manage_channels=True)
    @app_commands.describe(seconds="Slowmode in seconds (0 disables it)")
    async def slowmode(
        self, interaction: discord.Interaction, seconds: int = 0
    ) -> None:
        seconds = max(0, min(seconds, 21600))
        await interaction.channel.edit(slowmode_delay=seconds)
        if seconds:
            await interaction.response.send_message(
                f":hourglass_flowing_sand: Slowmode set to **{seconds}s**."
            )
        else:
            await interaction.response.send_message(":hourglass: Slowmode disabled.")

    # ------------------------------------------------------------------
    # Slowmode (every channel)
    # ------------------------------------------------------------------
    @app_commands.command(
        name="slowmode-all",
        description="Set slowmode on every text channel in the server.",
    )
    @app_commands.checks.has_permissions(manage_channels=True)
    @app_commands.describe(seconds="Slowmode in seconds (0 disables it)")
    async def slowmode_all(
        self, interaction: discord.Interaction, seconds: int = 0
    ) -> None:
        seconds = max(0, min(seconds, 21600))
        count = 0
        for channel in interaction.guild.text_channels:
            try:
                await channel.edit(slowmode_delay=seconds)
                count += 1
            except discord.Forbidden:
                continue
        await interaction.response.send_message(
            f":hourglass_flowing_sand: Slowmode set to **{seconds}s** "
            f"in **{count}** channels."
        )

    # ------------------------------------------------------------------
    # Warns
    # ------------------------------------------------------------------
    @app_commands.command(name="warn", description="Warn a member.")
    @app_commands.checks.has_permissions(moderate_members=True)
    @app_commands.describe(member="The member to warn", reason="Reason for the warning")
    async def warn(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
        reason: str,
    ) -> None:
        warnings = _load_warnings()
        key = str(member.id)
        entry = warnings.setdefault(
            key,
            {"user": f"{member}", "warnings": []},
        )
        entry["warnings"].append(
            {
                "reason": reason,
                "mod": f"{interaction.user}",
                "date": datetime.now(timezone.utc).isoformat(),
            }
        )
        _save_warnings(warnings)

        await interaction.response.send_message(
            f":warning: **{member}** was warned ({len(entry['warnings'])} total).\n> {reason}"
        )

    @app_commands.command(name="warnings", description="Show a member's warnings.")
    @app_commands.checks.has_permissions(moderate_members=True)
    @app_commands.describe(member="The member to check")
    async def warnings(
        self, interaction: discord.Interaction, member: discord.Member
    ) -> None:
        entry = _load_warnings().get(str(member.id))
        if not entry or not entry["warnings"]:
            await interaction.response.send_message(
                f":white_check_mark: **{member}** has no warnings."
            )
            return

        lines = [
            f"**{i + 1}.** {w['reason']} — {w['mod']} ({w['date'][:10]})"
            for i, w in enumerate(entry["warnings"])
        ]
        embed = discord.Embed(
            title=f"Warnings for {member}",
            description="\n".join(lines),
            color=discord.Color.orange(),
        )
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="clearwarn", description="Clear a member's warnings.")
    @app_commands.checks.has_permissions(moderate_members=True)
    @app_commands.describe(member="The member to clear warnings for")
    async def clearwarn(
        self, interaction: discord.Interaction, member: discord.Member
    ) -> None:
        warnings = _load_warnings()
        if warnings.pop(str(member.id), None):
            _save_warnings(warnings)
            await interaction.response.send_message(
                f":sponge: Cleared all warnings for **{member}**."
            )
        else:
            await interaction.response.send_message(
                f":white_check_mark: **{member}** had no warnings."
            )

    # ------------------------------------------------------------------
    # Errors
    # ------------------------------------------------------------------
    @purge.error
    @slowmode.error
    @slowmode_all.error
    @warn.error
    @warnings.error
    @clearwarn.error
    async def _on_error(
        self,
        interaction: discord.Interaction,
        error: app_commands.AppCommandError,
    ) -> None:
        if isinstance(error, app_commands.MissingPermissions):
            await interaction.response.send_message(
                ":x: **drepfy** — you are not authorized to use this command.",
                ephemeral=True,
            )
        else:
            log.warning("Moderation error: %s", error)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Moderation(bot))
