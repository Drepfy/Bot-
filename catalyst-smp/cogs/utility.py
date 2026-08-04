"""Utility commands for Catalyst SMP."""

import asyncio
import logging
from datetime import datetime, timedelta

import discord
from discord import app_commands
from discord.ext import commands

log = logging.getLogger("catalyst.utility")

EMOJI_NUMBERS = {
    1: "1️⃣", 2: "2️⃣", 3: "3️⃣", 4: "4️⃣",
    5: "5️⃣", 6: "6️⃣", 7: "7️⃣", 8: "8️⃣", 9: "9️⃣", 10: "🔟",
}


@app_commands.guild_only()
class Utility(commands.GroupCog, name="util"):
    """Useful server tools."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self._reminders: dict[int, asyncio.Task] = {}

    # ------------------------------------------------------------------
    # Ping
    # ------------------------------------------------------------------
    @app_commands.command(name="ping", description="Check the bot's latency.")
    async def ping(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_message(
            f":ping_pong: Pong! `{round(self.bot.latency * 1000)}ms`"
        )

    # ------------------------------------------------------------------
    # Poll
    # ------------------------------------------------------------------
    @app_commands.command(name="poll", description="Create a poll with up to 10 options.")
    @app_commands.describe(question="The question to ask", options="Comma-separated options")
    async def poll(
        self, interaction: discord.Interaction, question: str, options: str
    ) -> None:
        choices = [o.strip() for o in options.split(",") if o.strip()]
        if not choices:
            await interaction.response.send_message(
                ":x: Please provide at least one option.", ephemeral=True
            )
            return
        if len(choices) > 10:
            choices = choices[:10]

        lines = [
            f"{EMOJI_NUMBERS[i + 1]} {choice}"
            for i, choice in enumerate(choices)
        ]
        embed = discord.Embed(
            title=f":bar_chart: {question}",
            description="\n".join(lines),
            color=discord.Color.blue(),
        )
        embed.set_footer(text=f"Poll by {interaction.user}")

        await interaction.response.send_message(embed=embed)
        message = await interaction.original_response()
        for i in range(len(choices)):
            await message.add_reaction(EMOJI_NUMBERS[i + 1])

    # ------------------------------------------------------------------
    # Reminder
    # ------------------------------------------------------------------
    @app_commands.command(name="remind", description="Set a reminder for yourself.")
    @app_commands.describe(
        minutes="In how many minutes to remind you",
        note="What to remind you about",
    )
    async def remind(
        self,
        interaction: discord.Interaction,
        minutes: float,
        note: str = "Reminder!",
    ) -> None:
        if minutes <= 0 or minutes > 10080:
            await interaction.response.send_message(
                ":x: Minutes must be between 1 and 10080 (1 week).", ephemeral=True
            )
            return

        delta = timedelta(minutes=minutes)
        when = discord.utils.utcnow() + delta
        await interaction.response.send_message(
            f":alarm_clock: Reminder set for <t:{int(when.timestamp())}:R>."
        )

        task = asyncio.create_task(self._fire_reminder(interaction, note, delta))
        self._reminders[interaction.id] = task

    async def _fire_reminder(
        self,
        interaction: discord.Interaction,
        note: str,
        delta: timedelta,
    ) -> None:
        await asyncio.sleep(delta.total_seconds())
        try:
            await interaction.user.send(
                f":alarm_clock: Reminder: **{note}**"
            )
        except discord.Forbidden:
            if interaction.channel:
                await interaction.channel.send(
                    f"{interaction.user.mention} :alarm_clock: Reminder: **{note}**"
                )

    # ------------------------------------------------------------------
    # Server info
    # ------------------------------------------------------------------
    @app_commands.command(name="serverinfo", description="Show server information.")
    async def serverinfo(self, interaction: discord.Interaction) -> None:
        guild = interaction.guild
        embed = discord.Embed(
            title=guild.name,
            description=guild.description,
            color=discord.Color.green(),
        )
        embed.set_thumbnail(url=guild.icon.url if guild.icon else None)
        embed.add_field(name="Owner", value=guild.owner.mention, inline=True)
        embed.add_field(name="Members", value=guild.member_count, inline=True)
        embed.add_field(
            name="Boosts", value=guild.premium_subscription_count, inline=True
        )
        embed.add_field(name="Channels", value=len(guild.channels), inline=True)
        embed.add_field(name="Roles", value=len(guild.roles), inline=True)
        embed.set_footer(text=f"ID: {guild.id} • Created {guild.created_at:%b %d, %Y}")
        await interaction.response.send_message(embed=embed)

    # ------------------------------------------------------------------
    # User info
    # ------------------------------------------------------------------
    @app_commands.command(name="userinfo", description="Show information about a user.")
    @app_commands.describe(member="The member to inspect (defaults to you)")
    async def userinfo(
        self, interaction: discord.Interaction, member: discord.Member = None
    ) -> None:
        member = member or interaction.user
        embed = discord.Embed(
            title=f"{member}",
            description=member.activity,
            color=discord.Color.green(),
        )
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.add_field(
            name="Joined server", value=f"<t:{int(member.joined_at.timestamp())}:D>"
        )
        embed.add_field(
            name="Joined Discord",
            value=f"<t:{int(member.created_at.timestamp())}:D>",
        )
        embed.add_field(name="Roles", value=", ".join(r.mention for r in member.roles[1:]) or "None")
        embed.set_footer(text=f"ID: {member.id}")
        await interaction.response.send_message(embed=embed)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Utility(bot))
