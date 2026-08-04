"""Ticket system for Catalyst SMP."""

import asyncio
import logging

import discord
from discord import app_commands
from discord.ext import commands

import config

log = logging.getLogger("catalyst.tickets")

TICKET_TYPES = {
    "report": ("Report a player", "⚠️"),
    "restore": ("Request a restore", "🔁"),
    "other": ("Other", "📩"),
}


class TicketSelect(discord.ui.Select):
    def __init__(self, tickets: "Tickets") -> None:
        self.tickets = tickets
        options = [
            discord.SelectOption(label=label, value=value, emoji=emoji)
            for value, (label, emoji) in TICKET_TYPES.items()
        ]
        super().__init__(
            placeholder="Open a ticket...",
            min_values=1,
            max_values=1,
            options=options,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        await self.tickets.create_ticket(interaction, self.values[0])


class MoreSelect(discord.ui.Select):
    def __init__(self, tickets: "Tickets") -> None:
        self.tickets = tickets
        super().__init__(
            placeholder="More options...",
            min_values=1,
            max_values=1,
            options=[
                discord.SelectOption(
                    label="Partnership request", value="partner", emoji="🤝"
                )
            ],
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        partner_cog = self.tickets.bot.get_cog("Partner")
        if partner_cog is None:
            await interaction.response.send_message(
                ":x: Partnership system is not loaded.", ephemeral=True
            )
            return
        await partner_cog.apply(interaction)


class TicketPanel(discord.ui.View):
    def __init__(self, tickets: "Tickets") -> None:
        super().__init__(timeout=None)
        self.add_item(TicketSelect(tickets))
        self.add_item(MoreSelect(tickets))


@app_commands.guild_only()
class Tickets(commands.GroupCog, name="ticket"):
    """Support tickets."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="open", description="Post the ticket panel.")
    async def open_panel(self, interaction: discord.Interaction) -> None:
        embed = discord.Embed(
            title="Catalyst SMP Support",
            description="Select an option below to get started.",
            color=discord.Color.blue(),
        )
        await interaction.response.send_message(embed=embed, view=TicketPanel(self))

    @app_commands.command(name="close", description="Close the current ticket channel.")
    async def close(self, interaction: discord.Interaction) -> None:
        channel = interaction.channel
        if not channel.name.startswith("ticket-"):
            await interaction.response.send_message(
                ":x: This is not a ticket channel.", ephemeral=True
            )
            return

        await interaction.response.send_message(":lock: Closing ticket in 5 seconds...")
        await asyncio.sleep(5)
        await channel.delete(reason=f"Ticket closed by {interaction.user}")

    async def create_ticket(
        self, interaction: discord.Interaction, ticket_type: str
    ) -> None:
        label, emoji = TICKET_TYPES[ticket_type]

        for channel in interaction.guild.text_channels:
            if channel.name.startswith("ticket-") and channel.topic == str(
                interaction.user.id
            ):
                await interaction.response.send_message(
                    f":x: You already have an open ticket in {channel.mention}.",
                    ephemeral=True,
                )
                return

        overwrites = {
            interaction.guild.default_role: discord.PermissionOverwrite(
                view_channel=False
            ),
            interaction.guild.me: discord.PermissionOverwrite(
                view_channel=True, send_messages=True, manage_channels=True
            ),
            interaction.user: discord.PermissionOverwrite(
                view_channel=True, send_messages=True, read_messages=True
            ),
        }
        staff_role = discord.utils.get(
            interaction.guild.roles, name=config.STAFF_ROLE_NAME
        )
        if staff_role:
            overwrites[staff_role] = discord.PermissionOverwrite(
                view_channel=True, send_messages=True, read_messages=True
            )

        category = discord.utils.get(
            interaction.guild.categories, name=config.TICKET_CATEGORY_NAME
        )
        name = f"ticket-{ticket_type}-{interaction.user.display_name[:20].lower()}"
        channel = await interaction.guild.create_text_channel(
            name,
            category=category,
            overwrites=overwrites,
            topic=str(interaction.user.id),
            reason=f"Ticket opened by {interaction.user}",
        )

        await channel.send(
            f"{interaction.user.mention} **{emoji} {label}** ticket created!\n"
            "A staff member will be with you shortly. Use `/ticket close` when done."
        )
        await interaction.response.send_message(
            f":white_check_mark: Ticket created: {channel.mention}", ephemeral=True
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Tickets(bot))
