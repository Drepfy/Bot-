"""Server events for Catalyst SMP."""

import logging

import discord
from discord.ext import commands

import config

log = logging.getLogger("catalyst.events")


class Events(commands.Cog):
    """Automatic server events."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member) -> None:
        channel = self._welcome_channel(member.guild)
        if channel is None:
            return

        embed = discord.Embed(
            title=f"Welcome to {member.guild.name}!",
            description=f"Glad to have you here, {member.mention} :wave:",
            color=discord.Color.green(),
        )
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.set_footer(text=f"Member #{member.guild.member_count}")
        await channel.send(embed=embed)

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member) -> None:
        channel = self._welcome_channel(member.guild)
        if channel is None:
            return
        await channel.send(f":wave: **{member}** left the server.")

    def _welcome_channel(self, guild: discord.Guild) -> discord.TextChannel | None:
        if config.WELCOME_CHANNEL_ID:
            return guild.get_channel(config.WELCOME_CHANNEL_ID)
        return guild.system_channel


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Events(bot))
