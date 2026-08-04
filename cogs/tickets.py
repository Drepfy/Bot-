"""Ticket system for Catalyst SMP."""

import asyncio
import logging

import discord
from discord import app_commands
from discord.ext import commands

import config

log = logging.getLogger("catalyst.tickets")

TICKET_TYPES = {
    "report": ("Report a player", "🔎"),
    "restore": ("Request a restore", "♻️"),
    "other": ("Other", "❓"),
}


# --------------------------------------------------------------------------
# Report a player
# --------------------------------------------------------------------------
class ReportModal(discord.ui.Modal, title="Report a player"):
    player_name = discord.ui.TextInput(
        label="Player name",
        placeholder="e.g. Drepfy",
        required=False,
        max_length=100,
    )
    reason = discord.ui.TextInput(
        label="Reason for report",
        style=discord.TextStyle.paragraph,
        placeholder="e.g. keeps pearl abusing",
        required=True,
        max_length=1000,
    )
    clip = discord.ui.TextInput(
        label="Clip (without this chances are low)",
        style=discord.TextStyle.paragraph,
        placeholder="Paste a Medal, YouTube, Streamable or other video link.",
        required=False,
        max_length=1000,
    )
    anonymous = discord.ui.TextInput(
        label="Anonymous",
        placeholder="Yes/No",
        required=True,
        max_length=100,
    )

    def __init__(self, tickets: "Tickets") -> None:
        super().__init__()
        self.tickets = tickets

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await self.tickets.create_ticket(
            interaction,
            "report",
            {
                "Player name": self.player_name.value or "Not provided",
                "Reason for report": self.reason.value,
                "Clip": self.clip.value or "Not provided",
                "Anonymous": self.anonymous.value,
            },
        )


# --------------------------------------------------------------------------
# Request a restore
# --------------------------------------------------------------------------
class RestoreModal(discord.ui.Modal, title="Request a restore"):
    username = discord.ui.TextInput(
        label="Please enter your Minecraft username",
        placeholder="e.g. Drepfy",
        required=True,
        max_length=100,
    )
    situation = discord.ui.TextInput(
        label="Please describe the situation",
        style=discord.TextStyle.paragraph,
        placeholder="e.g. 2mp, Void, Server lagged",
        required=True,
        max_length=1000,
    )
    clip = discord.ui.TextInput(
        label="Please enter a link to a clip",
        style=discord.TextStyle.paragraph,
        placeholder="Placeholder text for the field, just like this text",
        required=False,
        max_length=1000,
    )

    def __init__(self, tickets: "Tickets") -> None:
        super().__init__()
        self.tickets = tickets

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await self.tickets.create_ticket(
            interaction,
            "restore",
            {
                "Minecraft username": self.username.value,
                "Situation": self.situation.value,
                "Clip": self.clip.value or "Not provided",
            },
        )


# --------------------------------------------------------------------------
# Other
# --------------------------------------------------------------------------
class OtherModal(discord.ui.Modal, title="Other"):
    issue = discord.ui.TextInput(
        label="Please describe your issue.",
        placeholder="Please clarify the issue you are facing.",
        required=True,
        max_length=1000,
    )
    username = discord.ui.TextInput(
        label="What is your Minecraft username",
        placeholder="Placeholder text for the field, just like this text",
        required=True,
        max_length=100,
    )
    extra = discord.ui.TextInput(
        label="If you have anything else to send",
        style=discord.TextStyle.paragraph,
        placeholder="Placeholder text for the field, just like this text",
        required=False,
        max_length=1000,
    )

    def __init__(self, tickets: "Tickets") -> None:
        super().__init__()
        self.tickets = tickets

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await self.tickets.create_ticket(
            interaction,
            "other",
            {
                "Issue": self.issue.value,
                "Minecraft username": self.username.value,
                "Extra": self.extra.value or "Not provided",
            },
        )


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
            custom_id="ticket_select",
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        if self.values[0] == "report":
            await interaction.response.send_modal(ReportModal(self.tickets))
        elif self.values[0] == "restore":
            await interaction.response.send_modal(RestoreModal(self.tickets))
        else:
            await interaction.response.send_modal(OtherModal(self.tickets))


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
            custom_id="ticket_more",
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


def _panel_embed() -> discord.Embed:
    return discord.Embed(
        title="Open a ticket!",
        description="Please pick from the options below depending on what help you need.",
        color=discord.Color.blue(),
    )


@app_commands.guild_only()
class Tickets(commands.GroupCog, name="ticket"):
    """Support tickets."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    async def cog_load(self) -> None:
        self.bot.add_view(TicketPanel(self))

    @commands.Cog.listener()
    async def on_ready(self) -> None:
        if not config.TICKET_PANEL_CHANNEL_ID:
            return
        channel = self.bot.get_channel(config.TICKET_PANEL_CHANNEL_ID)
        if channel is None:
            log.warning(
                "Ticket panel channel %s not found", config.TICKET_PANEL_CHANNEL_ID
            )
            return
        async for message in channel.history(limit=50):
            if (
                message.author.id == self.bot.user.id
                and message.embeds
                and message.embeds[0].title == "Open a ticket!"
            ):
                log.info("Ticket panel already posted in %s", channel)
                return
        await channel.send(embed=_panel_embed(), view=TicketPanel(self))
        log.info("Posted ticket panel in %s", channel)

    @app_commands.command(name="open", description="Post the ticket panel.")
    async def open_panel(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_message(
            embed=_panel_embed(), view=TicketPanel(self)
        )

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
        self,
        interaction: discord.Interaction,
        ticket_type: str,
        fields: dict[str, str],
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

        description = "\n".join(f"**{k}:** {v}" for k, v in fields.items())
        embed = discord.Embed(
            title=f"{emoji} {label}",
            description=description,
            color=discord.Color.blurple(),
        )
        embed.set_footer(text=f"Opened by {interaction.user}")
        await channel.send(f"{interaction.user.mention}", embed=embed)
        await channel.send(
            "A staff member will be with you shortly. Use `/ticket close` when done."
        )
        await interaction.response.send_message(
            f":white_check_mark: Ticket created: {channel.mention}", ephemeral=True
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Tickets(bot))
