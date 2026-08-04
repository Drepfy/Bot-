# Catalyst SMP Discord Bot

A neat Discord bot for the Catalyst SMP server with **moderation**, **utility tools**, **tickets**, and **auto-partnership**.

## Features

**Moderation** (admin only, all under `/mod`):
- `/mod purge` — bulk-delete messages
- `/mod slowmode` — set slowmode on a channel
- `/mod slowmode-all` — set slowmode on **every** text channel
- `/mod warn` / `/mod warnings` / `/mod clearwarn` — warning system

**Utility** (everyone):
- `/util ping` — check latency
- `/util poll` — reaction-based polls
- `/util remind` — personal reminders
- `/util serverinfo` — server stats
- `/util userinfo` — member profile

**Tickets**:
- The ticket panel is auto-posted to the configured channel (`TICKET_PANEL_CHANNEL_ID`) on startup:
  - Report a player
  - Request a restore
  - Other
  - Plus a "More options" dropdown → **Partnership request**
- `/ticket open` — posts the panel manually (any channel)
- `/ticket close` — closes the current ticket channel
- Tickets open as private channels only visible to the member + staff role

**Auto-partnership**:
- `/partner apply` — creates a private thread, asks for your server **AD**, then **proof** (image)
- Applications are forwarded to the partnership channel for staff review and saved to `data/partners.json`

**Events**:
- N/A (welcome/goodbye removed)

## Setup (local)

1. **Install Python 3.10+**
2. **Create a bot** at <https://discord.com/developers/applications>:
   - New Application → Bot → Reset Token → copy the token
   - Enable **Message Content Intent** and **Server Members Intent**
   - Invite with the `bot` and `applications.commands` scopes (Administrator permission recommended)
3. **Configure**:
   ```bash
   cd catalyst-smp
   python -m venv .venv
   .venv\Scripts\activate        # Windows
   # source .venv/bin/activate  # macOS / Linux
   pip install -r requirements.txt
   copy .env.example .env        # Windows
   # cp .env.example .env        # macOS / Linux
   ```
4. Fill in `.env` — at minimum `DISCORD_TOKEN`.
5. **Run**:
   ```bash
   python bot.py
   ```

## Deploy to Railway

1. **Push to GitHub**:
   ```bash
   cd catalyst-smp
   git init
   git add .
   git commit -m "Initial commit"
   git branch -M main
   git remote add origin https://github.com/<your-user>/<repo>.git
   git push -u origin main
   ```
2. **On Railway** (<https://railway.app>): New Project → Deploy from GitHub → pick the repo. Railway auto-detects the included `Dockerfile`/`railway.json`.
3. **Add environment variables** in the Railway dashboard (same keys as `.env`, at minimum `DISCORD_TOKEN`):
   `DISCORD_TOKEN`, `STAFF_ROLE_NAME`, `TICKET_CATEGORY_NAME`, `TICKET_PANEL_CHANNEL_ID`, `PARTNER_CHANNEL_ID`.
4. Deploy.

**Persisting warnings/partners on Railway:** the filesystem is reset on redeploys.
Mount a **Volume** at `/app/data` to keep `warnings.json` and `partners.json`.

## Project layout

```
catalyst-smp/
├── bot.py              # entry point
├── config.py           # reads settings from .env
├── requirements.txt
├── Dockerfile          # Railway deployment
├── railway.json
├── cogs/
│   ├── moderation.py   # /mod commands
│   ├── utility.py      # /util commands
│   ├── tickets.py      # /ticket system
│   └── partner.py      # /partner system
├── data/               # persistent data (warnings.json, partners.json)
└── .env.example        # template for .env
```
