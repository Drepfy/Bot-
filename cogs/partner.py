"""Auto-partnership for Catalyst SMP.

One click opens a short application form; submitted applications are posted
to the partnership channel for staff review and saved to partners.json.
Staff can approve or deny from the channel; the applicant is DMed the result.
"""

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


def _load_partners() -> list[dict]:
    if not PARTNER_FILE.exists():
        return []
    try:
        data = json.loads(PARTNER_FILE.read_text(encoding="utf-8"))
        return list(data.get("partners", []))
    except (json.JSONDecodeError, OSError):
        return []


def _save_partner(entry: dict) -> None:
    DATA_DIR.mkdir(exist_ok=True)
    data = {"partners": _load_partners()}
    data["partners"].append(entry)
    PARTNER_FILE.write_text(
        json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def _update_partner(message_id: int, **changes) -> dict | None:
    partners = _load_partners()
    for entry in partners:
        if entry.get("message_id") == message_id:
            entry.update(changes)
            DATA_DIR.mkdir(exist_ok=True)
            PARTNER_FILE.write_text(
                json.dumps({"partners": partners}, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            return entry
    return None


class DenyModal(discord.ui.Modal, title="Deny partnership"):
    reason = discord.ui.TextInput(
        label="Reason (optional)",
        style=discord.TextStyle.paragraph,
        placeholder="Why was the application denied? This is shown to the applicant.",
        required=False,
        max_length=500,
    )

    def __init__(self, partner: "Partner") -> None:
        super().__init__()
        self.partner = partner

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await self.partner.review(
            interaction, approved=False, reason=self.reason.value.strip() or None
        )


class ApprovalView(discord.ui.View):
    def __init__(self, partner: "Partner") -> None:
        super().__init__(timeout=None)
        self.partner = partner
        self.add_item(
            discord.ui.Button(
                label="Approve",
                style=discord.ButtonStyle.success,
                emoji="✅",
                custom_id="partner_approve",
            )
        )
        self.add_item(
            discord.ui.Button(
                label="Deny",
                style=discord.ButtonStyle.danger,
                emoji="⛔",
                custom_id="partner_deny",
            )
        )

    def _is_staff(self, interaction: discord.Interaction) -> bool:
        return any(
            role.name == config.STAFF_ROLE_NAME for role in interaction.user.roles
        )

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if self._is_staff(interaction):
            return True
        await interaction.response.send_message(
            ":x: Only staff can review partnership applications.", ephemeral=True
        )
        return False

    async def approve(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer()
        await self.partner.review(
            interaction, approved=True, reason="Approved by staff."
        )

    async def deny(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_modal(DenyModal(self.partner))


class PartnerModal(discord.ui.Modal, title="Partnership application"):
    server_name = discord.ui.TextInput(
        label="Server name",
        placeholder="The name of your server (e.g. Drepfy's SMP)",
        required=True,
        max_length=100,
    )
    invite = discord.ui.TextInput(
        label="Server invite link",
        placeholder="discord.gg/your-invite - must not expire",
        required=False,
        max_length=100,
    )
    ad = discord.ui.TextInput(
        label="Server AD / description",
        style=discord.TextStyle.paragraph,
        placeholder="A short ad for your server. Include what makes it special.",
        required=True,
        max_length=1000,
    )
    proof = discord.ui.TextInput(
        label="Proof image link",
        style=discord.TextStyle.paragraph,
        placeholder="Link to a screenshot proving your server size (e.g. member list).",
        required=True,
        max_length=500,
    )
    extra = discord.ui.TextInput(
        label="Anything else",
        style=discord.TextStyle.paragraph,
        placeholder="Additional info - member count, staff team, activity, etc.",
        required=False,
        max_length=1000,
    )

    def __init__(self, partner: "Partner") -> None:
        super().__init__()
        self.partner = partner

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await self.partner.submit_application(
            interaction,
            {
                "server_name": self.server_name.value,
                "invite": self.invite.value or "Not provided",
                "ad": self.ad.value,
                "proof": self.proof.value,
                "extra": self.extra.value or "Not provided",
            },
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
        await interaction.response.send_modal(PartnerModal(self))

    async def _build_embed(
        self, interaction: discord.Interaction, fields: dict[str, str]
    ) -> discord.Embed:
        embed = discord.Embed(
            title=f"🤝 Partnership request — {fields['server_name']}",
            description=fields["ad"][:1024],
            color=discord.Color.purple(),
        )
        embed.add_field(name="Server", value=fields["server_name"], inline=True)
        embed.add_field(name="Invite", value=fields["invite"], inline=True)
        embed.add_field(
            name="Proof", value=f"[View image]({fields['proof']})", inline=False
        )
        if fields["extra"] != "Not provided":
            embed.add_field(name="Additional info", value=fields["extra"], inline=False)
        embed.set_image(url=fields["proof"])
        embed.set_footer(
            text=f"Submitted by {interaction.user} (ID {interaction.user.id})"
        )
        return embed

    async def submit_application(
        self, interaction: discord.Interaction, fields: dict[str, str]
    ) -> None:
        await interaction.response.defer(ephemeral=True)

        embed = await self._build_embed(interaction, fields)

        staff_role = discord.utils.get(
            interaction.guild.roles, name=config.STAFF_ROLE_NAME
        )
        content = (
            ":hourglass: **Pending review**"
            + (f" {staff_role.mention}" if staff_role else "")
        )

        message = None
        channel_id = config.PARTNER_CHANNEL_ID or (
            interaction.guild.system_channel.id
            if interaction.guild.system_channel
            else None
        )
        if channel_id is not None:
            channel = interaction.guild.get_channel(channel_id)
            if channel is not None:
                try:
                    message = await channel.send(
                        content=content, embed=embed, view=ApprovalView(self)
                    )
                except discord.HTTPException as exc:
                    log.warning("Could not post partnership application: %s", exc)

        _save_partner(
            {
                "server": fields["server_name"],
                "ad": fields["ad"],
                "proof": fields["proof"],
                "date": discord.utils.utcnow().isoformat(),
                "user": f"{interaction.user}",
                "user_id": interaction.user.id,
                "channel_id": message.channel.id if message else None,
                "message_id": message.id if message else None,
                "status": "pending",
            }
        )

        await interaction.followup.send(
            f":white_check_mark: **Application submitted!** Staff will review it "
            "shortly. If approved, your ad will be announced in the partnership channel.",
            ephemeral=True,
        )

    async def review(
        self,
        interaction: discord.Interaction,
        approved: bool,
        reason: str | None,
    ) -> None:
        if interaction.message is None:
            return
        message = interaction.message
        entry = _update_partner(
            message.id,
            status="approved" if approved else "denied",
            reviewer=f"{interaction.user}",
            reviewed_at=discord.utils.utcnow().isoformat(),
            reason=reason,
        )

        embed = message.embeds[0] if message.embeds else None
        if embed is not None:
            embed.color = (
                discord.Color.green() if approved else discord.Color.red()
            )
            embed.add_field(
                name=("✅ Approved" if approved else "⛔ Denied"),
                value=reason or "No reason given.",
                inline=False,
            )
            embed.set_footer(text=embed.footer.text + f" • Reviewed by {interaction.user}")

        content = (
            ":white_check_mark: **Approved** 🎉" if approved else ":x: **Denied**"
        )
        view = ApprovalView(self) if not approved else discord.ui.View(timeout=None)
        await message.edit(content=content, embed=embed, view=view)

        if entry and entry.get("user_id"):
            member = interaction.guild.get_member(entry["user_id"])
            if member is None:
                try:
                    member = await interaction.guild.fetch_member(entry["user_id"])
                except discord.NotFound:
                    member = None
            if member is not None:
                dm = discord.Embed(
                    title=(
                        f"✅ Your partnership application for **{entry['server']}** was approved!"
                        if approved
                        else f"⛔ Your partnership application for **{entry['server']}** was denied."
                    ),
                    description=reason or (
                        "We've chosen to partner with another server this time, but keep us in mind for the future!"
                    ),
                    color=discord.Color.green() if approved else discord.Color.red(),
                )
                try:
                    await member.send(embed=dm)
                except (discord.Forbidden, discord.HTTPException) as exc:
                    log.warning("Could not DM applicant: %s", exc)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Partner(bot))
