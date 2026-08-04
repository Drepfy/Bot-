"""Auto-partnership for Catalyst SMP.

Servers apply with an AD + proof image in a private thread. Approved-looking
ads are forwarded to staff in the partnership channel for manual review.
"""

import asyncio
import json
import logging
from pathlib import Path

import discord
from discord import app_commands
from discord.ext import commands

import config

log = logging.getLogger("catalyst.partner")

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
PARTNER_FILE = DATA_DIR / "partners.json"

TIMEOUT = 300


def _save_partner(entry: dict) -> None:
    DATA_DIR.mkdir(exist_ok=True)
    data = {}
    if PARTNER_FILE.exists():
        try:
            data = json.loads(PARTNER_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            data = {}
    data.setdefault("partners", []).append(entry)
    PARTNER_FILE.write_text(
        json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
    )


@app_commands.guild_only()
class Partner(commands.GroupCog, name="partner"):
    """Partnership requests."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(
        name="apply", description="Apply for a partnership with Catalyst SMP."
    )
    async def apply(self, interaction: discord.Interaction) -> None:
        channel = interaction.channel
        try:
            thread = await channel.create_thread(
                name=f"partner-{interaction.user.display_name[:20]}",
                type=discord.ChannelType.private_thread,
                auto_archive_duration=1440,
            )
        except Exception:
            await interaction.response.send_message(
                ":x: Could not create a partnership thread here.", ephemeral=True
            )
            return

        await interaction.response.send_message(
            f"Started! Continue in {thread.mention}", ephemeral=True
        )
        await thread.send(
            "🤝 **Partnership application**\n"
            "Step 1: Send your server **AD** (a short advertisement for your server)."
        )

        try:
            ad_msg = await self._wait(thread, interaction.user)
        except asyncio.TimeoutError:
            await thread.send(f":x: Timed out. Run `/partner apply` again, {interaction.user.mention}.")
            return

        await thread.send(
            "Step 2: Send **proof** — a screenshot showing your server "
            "(e.g. member count or channel list)."
        )
        try:
            proof_msg = await self._wait(thread, interaction.user)
        except asyncio.TimeoutError:
            await thread.send(f":x: Timed out. Run `/partner apply` again, {interaction.user.mention}.")
            return

        if not proof_msg.attachments:
            await thread.send(":x: You need to attach a proof **image**.")
            return

        await thread.send(
            ":hourglass: Sending your application to staff for review."
        )

        embed = discord.Embed(
            title="Partnership request",
            description=ad_msg.content[:1024],
            color=discord.Color.purple(),
        )
        embed.set_image(url=proof_msg.attachments[0].url)
        embed.set_footer(
            text=f"From {proof_msg.author} ({proof_msg.guild})"
        )

        await thread.send(
            f":white_check_mark: **Submitted!** {interaction.user.mention} "
            "Your application was sent to staff for review."
        )
        self._announce(interaction.guild, embed)
        _save_partner(
            {
                "server": f"{proof_msg.guild}",
                "ad": ad_msg.content,
                "proof": proof_msg.attachments[0].url,
                "date": discord.utils.utcnow().isoformat(),
            }
        )

    def _announce(self, guild: discord.Guild, embed: discord.Embed) -> None:
        channel_id = config.PARTNER_CHANNEL_ID or (
            guild.system_channel.id if guild.system_channel else None
        )
        if channel_id is None:
            return
        channel = guild.get_channel(channel_id)
        if channel is None:
            return
        embed.description = (
            ":hourglass: **Pending review**\n" + (embed.description or "")
        )
        self.bot.loop.create_task(channel.send(embed=embed))

    async def _wait(
        self, channel: discord.Thread, user: discord.User, timeout: int = TIMEOUT
    ):
        def check(message: discord.Message) -> bool:
            return message.author == user and message.channel == channel

        return await self.bot.wait_for("message", check=check, timeout=timeout)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Partner(bot))
