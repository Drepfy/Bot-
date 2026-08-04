"""Ticket system for Catalyst SMP.

TicketTool v2 / Ticky-style: a dropdown opens a form, tickets are created
in a private staff-only category, and staff get Claim / Close / Transcript
buttons inside every ticket.
"""

import asyncio
import io
import logging
from pathlib import Path

import discord
from discord import app_commands
from discord.ext import commands

import config

log = logging.getLogger("catalyst.tickets")

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
TRANS_DIR = DATA_DIR / "transcripts"

TICKET_TYPES = {
    "report": (
        "Report a player",
        "🔎",
        discord.Color.red(),
        "Report cheaters, bug abusers and rule breakers.",
    ),
    "restore": (
        "Request a restore",
        "♻️",
        discord.Color.orange(),
        "Get your items restored after a death.",
    ),
    "other": (
        "Other",
        "❓",
        discord.Color.blurple(),
        "Everything else - questions, appeals, media applications.",
    ),
}

OTHER_REASONS = [
    ("General Question", "Ask us anything about the server."),
    ("Media Application", "Apply to be a media partner (YouTube, Twitch, etc.)."),
    ("Ban Appeals", "Appeal a ban or punishment."),
    ("Partnership", "Apply for a partnership with Catalyst SMP."),
    ("Other", "Something else not listed above."),
]


# --------------------------------------------------------------------------
# Report a player
# --------------------------------------------------------------------------
class ReportModal(discord.ui.Modal, title="Report a player"):
    player_name = discord.ui.TextInput(
        label="Player name",
        placeholder="e.g. Drepfy (leave empty to skip)",
        required=False,
        max_length=100,
    )
    reason = discord.ui.TextInput(
        label="Reason for report",
        style=discord.TextStyle.paragraph,
        placeholder="e.g. keeps pearl abusing (cheats, bug abuse, etc.)",
        required=True,
        max_length=1000,
    )
    clip = discord.ui.TextInput(
        label="Clip (without this chances are low)",
        style=discord.TextStyle.paragraph,
        placeholder="Paste a Medal, YouTube, Streamable or other video link. Higher chance of punishment.",
        required=True,
        max_length=1000,
    )
    anonymous = discord.ui.TextInput(
        label="Anonymous",
        placeholder="Yes/No - hides your name from the reported player",
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
        placeholder="e.g. Drepfy (must be exact or no refund)",
        required=True,
        max_length=100,
    )
    situation = discord.ui.TextInput(
        label="Please describe the situation",
        style=discord.TextStyle.paragraph,
        placeholder="e.g. 2pm, Void, Server lagged. State time of death, cause, why you need a restore",
        required=True,
        max_length=1000,
    )
    clip = discord.ui.TextInput(
        label="Please enter a link to a clip",
        style=discord.TextStyle.paragraph,
        placeholder="A clip significantly increases your odds of a restore.",
        required=True,
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
        placeholder="Your exact Minecraft username",
        required=True,
        max_length=100,
    )
    extra = discord.ui.TextInput(
        label="If you have anything else to send",
        style=discord.TextStyle.paragraph,
        placeholder="Anything else we should know?",
        required=True,
        max_length=1000,
    )

    def __init__(self, tickets: "Tickets", reason: str = "") -> None:
        super().__init__()
        self.tickets = tickets
        self.reason = reason

    async def on_submit(self, interaction: discord.Interaction) -> None:
        fields = {
            "Issue": self.issue.value,
            "Minecraft username": self.username.value,
            "Extra": self.extra.value or "Not provided",
        }
        if self.reason:
            fields = {"Reason for ticket": self.reason, **fields}
        await self.tickets.create_ticket(interaction, "other", fields)


# --------------------------------------------------------------------------
# Close ticket modal
# --------------------------------------------------------------------------
class CloseModal(discord.ui.Modal, title="Close ticket with reason"):
    reason = discord.ui.TextInput(
        label="Closing reason",
        style=discord.TextStyle.paragraph,
        placeholder="Why is this ticket being closed?",
        required=False,
        max_length=500,
    )

    def __init__(self, tickets: "Tickets") -> None:
        super().__init__()
        self.tickets = tickets

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await self.tickets.close_ticket(interaction, self.reason.value or "")


# --------------------------------------------------------------------------
# Panel components
# --------------------------------------------------------------------------
class TicketSelect(discord.ui.Select):
    def __init__(self, tickets: "Tickets") -> None:
        self.tickets = tickets
        options = [
            discord.SelectOption(
                label=label, value=value, emoji=emoji, description=description
            )
            for value, (label, emoji, _color, description) in TICKET_TYPES.items()
        ]
        options.append(
            discord.SelectOption(
                label="Partnership",
                value="partner",
                emoji="🤝",
                description="Apply to partner with Catalyst SMP.",
            )
        )
        super().__init__(
            placeholder="Select what you need help with...",
            min_values=1,
            max_values=1,
            options=options,
            custom_id="ticket_select",
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        choice = self.values[0]
        if choice == "partner":
            partner_cog = self.tickets.bot.get_cog("partner")
            if partner_cog is None:
                await interaction.response.send_message(
                    ":x: Partnership is currently unavailable.", ephemeral=True
                )
                return
            await partner_cog.apply(interaction)
            return
        if choice == "other":
            await interaction.response.edit_message(view=OtherPanel(self.tickets))
            return
        modals = {"report": ReportModal, "restore": RestoreModal}
        await interaction.response.send_modal(modals[choice](self.tickets))


class ReasonSelect(discord.ui.Select):
    def __init__(self, tickets: "Tickets") -> None:
        self.tickets = tickets
        super().__init__(
            placeholder="Reason for ticket",
            min_values=1,
            max_values=1,
            options=[
                discord.SelectOption(
                    label=label, value=label, description=description
                )
                for label, description in OTHER_REASONS
            ],
            custom_id="ticket_other_reason",
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        reason = self.values[0]
        if reason == "Partnership":
            partner_cog = self.tickets.bot.get_cog("partner")
            if partner_cog is None:
                await interaction.response.send_message(
                    ":x: Partnership is currently unavailable.", ephemeral=True
                )
                return
            await partner_cog.apply(interaction)
            return
        await interaction.response.send_modal(
            OtherModal(self.tickets, reason=reason)
        )


class BackButton(discord.ui.Button):
    def __init__(self, tickets: "Tickets") -> None:
        self.tickets = tickets
        super().__init__(
            label="Back",
            style=discord.ButtonStyle.secondary,
            custom_id="ticket_back",
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        await interaction.response.edit_message(view=TicketPanel(self.tickets))


class TicketPanel(discord.ui.View):
    def __init__(self, tickets: "Tickets") -> None:
        super().__init__(timeout=None)
        self.add_item(TicketSelect(tickets))


class OtherPanel(discord.ui.View):
    def __init__(self, tickets: "Tickets") -> None:
        super().__init__(timeout=None)
        self.add_item(ReasonSelect(tickets))
        self.add_item(BackButton(tickets))


# --------------------------------------------------------------------------
# Ticket action buttons (inside every ticket)
# --------------------------------------------------------------------------
class TicketActions(discord.ui.View):
    def __init__(self, tickets: "Tickets") -> None:
        super().__init__(timeout=None)
        self.tickets = tickets
        self.add_item(
            discord.ui.Button(
                label="Claim", style=discord.ButtonStyle.success, custom_id="ticket_claim"
            )
        )
        self.add_item(
            discord.ui.Button(
                label="Close", style=discord.ButtonStyle.danger, custom_id="ticket_close"
            )
        )
        self.add_item(
            discord.ui.Button(
                label="Close with reason",
                style=discord.ButtonStyle.danger,
                custom_id="ticket_close_reason",
            )
        )
        self.add_item(
            discord.ui.Button(
                label="Transcript",
                style=discord.ButtonStyle.secondary,
                custom_id="ticket_transcript",
            )
        )

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if self._is_staff(interaction.user):
            return True
        await interaction.response.send_message(
            ":x: Only staff can use ticket actions.", ephemeral=True
        )
        return False

    def _is_staff(self, user: discord.Member) -> bool:
        return self.tickets._is_staff(user)

    @discord.ui.button(
        label="Claim", style=discord.ButtonStyle.success, custom_id="ticket_claim"
    )
    async def claim(self, interaction: discord.Interaction, _button) -> None:
        channel = interaction.channel
        if not channel.name.endswith("claimed"):
            await channel.edit(name=f"{channel.name}-claimed")
        await interaction.response.send_message(
            f"**Claimed by {interaction.user.mention}** — this ticket now has an assigned staff member."
        )

    @discord.ui.button(
        label="Close", style=discord.ButtonStyle.danger, custom_id="ticket_close"
    )
    async def close(self, interaction: discord.Interaction, _button) -> None:
        await self.tickets.close_ticket(interaction, "No reason provided")

    @discord.ui.button(
        label="Close with reason",
        style=discord.ButtonStyle.danger,
        custom_id="ticket_close_reason",
    )
    async def close_with_reason(
        self, interaction: discord.Interaction, _button
    ) -> None:
        await interaction.response.send_modal(CloseModal(self.tickets))

    @discord.ui.button(
        label="Transcript",
        style=discord.ButtonStyle.secondary,
        custom_id="ticket_transcript",
    )
    async def transcript(self, interaction: discord.Interaction, _button) -> None:
        await self.tickets.send_transcript(interaction)


# --------------------------------------------------------------------------
# Cog
# --------------------------------------------------------------------------
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
        self.panel_message: discord.Message | None = None

    async def cog_load(self) -> None:
        self.bot.add_view(TicketPanel(self))
        self.bot.add_view(OtherPanel(self))
        self.bot.add_view(TicketActions(self))

    def _is_staff(self, user: discord.Member) -> bool:
        if user.guild_permissions.administrator:
            return True
        return (
            discord.utils.get(user.roles, name=config.STAFF_ROLE_NAME) is not None
        )

    @commands.Cog.listener()
    async def on_ready(self) -> None:
        if not config.TICKET_PANEL_CHANNEL_ID:
            return
        channel = self.bot.get_channel(config.TICKET_PANEL_CHANNEL_ID)
        if channel is None or not isinstance(channel, discord.TextChannel):
            log.warning(
                "Ticket panel channel %s not found", config.TICKET_PANEL_CHANNEL_ID
            )
            return
        guild = channel.guild

        # Staff role
        role = discord.utils.get(guild.roles, name=config.STAFF_ROLE_NAME)
        if role is None:
            role = await guild.create_role(name=config.STAFF_ROLE_NAME)
            log.info("Created missing staff role: %s", role.name)

        # Ticket category (private, staff-only)
        category = discord.utils.get(
            guild.categories, name=config.TICKET_CATEGORY_NAME
        )
        if category is None:
            category = await guild.create_category(config.TICKET_CATEGORY_NAME)
            log.info("Created category: %s", category.name)
        await category.set_permissions(guild.default_role, view_channel=False)
        await category.set_permissions(role, view_channel=True)
        log.info("Category %s is private (staff only)", category.name)

        # Professional channel name
        if channel.name != "tickets":
            await channel.edit(name="tickets")
            log.info("Renamed panel channel to 'tickets'")

        # Panel (dedupe)
        async for message in channel.history(limit=50):
            if (
                message.author.id == self.bot.user.id
                and message.embeds
                and message.embeds[0].title == "Open a ticket!"
            ):
                self.panel_message = message
                log.info("Ticket panel already posted in %s", channel)
                return
        self.panel_message = await channel.send(
            embed=_panel_embed(), view=TicketPanel(self)
        )
        log.info("Posted ticket panel in %s", channel)

    @app_commands.command(name="open", description="Post the ticket panel.")
    async def open_panel(self, interaction: discord.Interaction) -> None:
        self.panel_message = await interaction.channel.send(
            embed=_panel_embed(), view=TicketPanel(self)
        )
        await interaction.response.send_message(
            ":white_check_mark: Panel posted.", ephemeral=True
        )

    @app_commands.command(name="close", description="Close the current ticket channel.")
    async def close(self, interaction: discord.Interaction) -> None:
        channel = interaction.channel
        if not channel.name.startswith("ticket-"):
            await interaction.response.send_message(
                ":x: This is not a ticket channel.", ephemeral=True
            )
            return
        await self.close_ticket(interaction, "Closed via /ticket close")

    @app_commands.command(name="add", description="Add a member to this ticket.")
    @app_commands.describe(member="The member to add")
    async def add_member(
        self, interaction: discord.Interaction, member: discord.Member
    ) -> None:
        channel = interaction.channel
        if not channel.name.startswith("ticket-"):
            await interaction.response.send_message(
                ":x: This is not a ticket channel.", ephemeral=True
            )
            return
        if not self._is_staff(interaction.user):
            await interaction.response.send_message(
                ":x: Only staff can add members.", ephemeral=True
            )
            return
        await channel.set_permissions(
            member, view_channel=True, send_messages=True, read_messages=True
        )
        await interaction.response.send_message(
            f":white_check_mark: Added {member.mention} to the ticket."
        )

    @app_commands.command(name="remove", description="Remove a member from this ticket.")
    @app_commands.describe(member="The member to remove")
    async def remove_member(
        self, interaction: discord.Interaction, member: discord.Member
    ) -> None:
        channel = interaction.channel
        if not channel.name.startswith("ticket-"):
            await interaction.response.send_message(
                ":x: This is not a ticket channel.", ephemeral=True
            )
            return
        if not self._is_staff(interaction.user):
            await interaction.response.send_message(
                ":x: Only staff can remove members.", ephemeral=True
            )
            return
        if member.id == interaction.user.id:
            await interaction.response.send_message(
                ":x: You cannot remove yourself.", ephemeral=True
            )
            return
        await channel.set_permissions(member, overwrite=None)
        await interaction.response.send_message(
            f":white_check_mark: Removed {member.mention} from the ticket."
        )

    async def create_ticket(
        self,
        interaction: discord.Interaction,
        ticket_type: str,
        fields: dict[str, str],
    ) -> None:
        label, emoji, color, _desc = TICKET_TYPES[ticket_type]

        for channel in interaction.guild.text_channels:
            if channel.name.startswith("ticket-") and channel.topic and str(
                interaction.user.id
            ) in channel.topic.split("|"):
                await interaction.response.send_message(
                    f":x: You already have an open ticket in {channel.mention}.",
                    ephemeral=True,
                )
                return

        await interaction.response.defer(ephemeral=True)

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
        anonymous = (
            ticket_type == "report"
            and fields.get("Anonymous", "").strip().lower().startswith("y")
        )
        name_part = (
            "anonymous" if anonymous else interaction.user.display_name[:20].lower()
        )
        name = f"ticket-{ticket_type}-{name_part}"
        channel = await interaction.guild.create_text_channel(
            name,
            category=category,
            overwrites=overwrites,
            topic=f"{interaction.user.id}",
            reason=f"Ticket opened by {interaction.user}",
        )

        welcome = discord.Embed(
            title=f"{emoji} {label}",
            description=(
                "Your ticket is open. A staff member will be with you shortly."
                if anonymous
                else f"{interaction.user.mention} your ticket is open. A staff member will be with you shortly."
            ),
            color=color,
        )
        welcome.add_field(
            name="Member", value="Anonymous" if anonymous else interaction.user.mention, inline=True
        )
        welcome.add_field(name="Ticket type", value=f"{emoji} {label}", inline=True)
        if not anonymous:
            welcome.set_footer(text=f"User ID: {interaction.user.id}")
        await channel.send(embed=welcome)

        details = discord.Embed(title="Ticket details", color=color)
        for key, value in fields.items():
            details.add_field(name=key, value=value or "Not provided", inline=False)
        await channel.send(embed=details)

        actions = discord.Embed(
            description="**Staff:** Claim the ticket to assign yourself, or close it when resolved.",
            color=discord.Color.blurple(),
        )
        await channel.send(embed=actions, view=TicketActions(self))

        alert_channel_id = config.TICKET_LOG_CHANNELS.get(ticket_type)
        if alert_channel_id:
            alert_channel = self.bot.get_channel(alert_channel_id)
            if alert_channel is not None:
                alert = discord.Embed(
                    title=f"{emoji} New {label.lower()} ticket",
                    description=(
                        "An anonymous member opened a ticket."
                        if anonymous
                        else f"{interaction.user.mention} opened a ticket."
                    ),
                    color=color,
                )
                alert.add_field(name="Channel", value=channel.mention, inline=True)
                alert_view = discord.ui.View(timeout=None)
                alert_view.add_item(
                    discord.ui.Button(
                        label="Open ticket",
                        style=discord.ButtonStyle.link,
                        url=channel.jump_url,
                    )
                )
                await alert_channel.send(embed=alert, view=alert_view)

        if self.panel_message is not None:
            try:
                await self.panel_message.edit(view=TicketPanel(self))
            except (discord.NotFound, discord.HTTPException):
                self.panel_message = None

        view = discord.ui.View(timeout=None)
        view.add_item(
            discord.ui.Button(
                label="Open ticket",
                style=discord.ButtonStyle.link,
                url=channel.jump_url,
            )
        )
        await interaction.followup.send(
            f":white_check_mark: Ticket created: {channel.mention}",
            view=view,
            ephemeral=True,
        )

    async def close_ticket(
        self, interaction: discord.Interaction, reason: str
    ) -> None:
        channel = interaction.channel
        if not channel.name.startswith("ticket-"):
            await interaction.response.send_message(
                ":x: This is not a ticket channel.", ephemeral=True
            )
            return

        await interaction.response.send_message(":lock: Closing ticket...")
        try:
            await self._save_transcript(channel, interaction.user, reason)
        except Exception as exc:
            log.warning("Transcript failed: %s", exc)

        await asyncio.sleep(3)
        try:
            await channel.delete(
                reason=f"Ticket closed by {interaction.user}: {reason or 'No reason'}"
            )
        except discord.NotFound:
            pass

    async def send_transcript(self, interaction: discord.Interaction) -> None:
        channel = interaction.channel
        if not channel.name.startswith("ticket-"):
            await interaction.response.send_message(
                ":x: This is not a ticket channel.", ephemeral=True
            )
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        text = await self._build_transcript(channel)
        fp = discord.File(
            io.BytesIO(text.encode("utf-8")),
            filename=f"{channel.name}-transcript.txt",
        )
        await interaction.followup.send(
            f"Transcript of {channel.mention}:", file=fp, ephemeral=True
        )

    async def _build_transcript(self, channel: discord.TextChannel) -> str:
        lines = []
        async for msg in channel.history(limit=1000, oldest_first=True):
            if msg.author.bot and not msg.content and not msg.attachments:
                continue
            content = msg.clean_content or ""
            embeds = " [embed]" if msg.embeds else ""
            att = (
                f" [attachment: {msg.attachments[0].filename}]"
                if msg.attachments
                else ""
            )
            lines.append(
                f"[{msg.created_at:%Y-%m-%d %H:%M UTC}] {msg.author}: {content}{embeds}{att}"
            )
        return "\n".join(lines)

    async def _save_transcript(
        self, channel: discord.TextChannel, closer: discord.User, reason: str
    ) -> None:
        text = await self._build_transcript(channel)
        header = (
            f"Ticket transcript: {channel.name}\n"
            f"Closed by: {closer}\n"
            f"Reason: {reason or 'Not provided'}\n\n"
        )
        payload = header + text

        TRANS_DIR.mkdir(exist_ok=True, parents=True)
        (TRANS_DIR / f"{channel.name}.txt").write_text(payload, encoding="utf-8")

        fp = discord.File(
            io.BytesIO(payload.encode("utf-8")),
            filename=f"{channel.name}-transcript.txt",
        )

        ticket_type = "other"
        for key in TICKET_TYPES:
            if channel.name.startswith(f"ticket-{key}-"):
                ticket_type = key
                break

        target = None
        type_channel_id = config.TICKET_LOG_CHANNELS.get(ticket_type)
        if type_channel_id:
            target = self.bot.get_channel(type_channel_id)
        if target is None and config.TRANSCRIPT_CHANNEL_ID:
            target = self.bot.get_channel(config.TRANSCRIPT_CHANNEL_ID)

        if target is not None:
            await target.send(content=f"Ticket closed: `{channel.name}`", file=fp)
            return

        opener_id = None
        if channel.topic:
            try:
                opener_id = int(channel.topic.strip())
            except ValueError:
                opener_id = None
        if opener_id:
            opener = self.bot.get_user(opener_id)
            if opener is not None:
                try:
                    await opener.send(
                        content=f"Your ticket `{channel.name}` was closed by {closer}.", file=fp
                    )
                    return
                except discord.Forbidden:
                    pass
        try:
            await closer.send(content=f"Ticket closed: `{channel.name}`", file=fp)
        except discord.Forbidden:
            pass


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Tickets(bot))
