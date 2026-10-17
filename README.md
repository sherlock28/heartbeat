# 💓 Heartbeat

**English** · [Español](README.es.md)

Lightweight VM uptime monitoring organised by **Client → Product → VM**, with **Telegram** and **Google Chat** alerts sent **only when a machine goes down and when it recovers** — no periodic noise.

Built with FastAPI, SQLite and HTMX, and shipped as a **single Docker container**.

---

## Table of contents

- [Features](#features)
- [How it works](#how-it-works)
- [Quick start](#quick-start)
- [Configuration](#configuration)
- [Using the panel](#using-the-panel)
- [Notification channels](#notification-channels)
- [When does it alert?](#when-does-it-alert)
- [Networking](#networking)
- [Running in production](#running-in-production)
- [Backup, restore and updates](#backup-restore-and-updates)
- [Health check](#health-check)
- [Troubleshooting](#troubleshooting)
- [Development](#development)
- [Adding a new integration](#adding-a-new-integration)
- [Project structure](#project-structure)
- [Roadmap](#roadmap)

---

## Features

- **Hierarchy Client → Product → VM.** Each client has its own notification channels.
- **Two check types per VM:**
  - **Ping (ICMP)** for machines that answer ping.
  - **TCP port** for machines whose firewall blocks ICMP (common on Windows and in the cloud). This also confirms that the service is listening (22 SSH, 3389 RDP, 443 HTTPS, 5432 PostgreSQL…).
- **Transition-only alerts:** one message when a VM goes down and one when it recovers, including how long it was down.
- **Configurable thresholds.** By default a VM is declared down after 3 consecutive failures, with checks every 30 s (≈ 90 s).
- **Integrations:**
  - **Telegram**, with automatic chat detection: no need to look up the Chat ID by hand.
  - **Google Chat**, through incoming webhooks. A VM's down and recovery messages are grouped in the same thread.
- **Web panel** with login:
  - **Live dashboard:**
    - counters for up, down, pending and paused VMs;
    - collapsible clients and products that remember their state;
    - VMs sorted with failures first.
  - **Live-updating tables:** they refresh every 10 s without reloading the page.
  - **Search:** live search of VMs by name or IP, highlighting the matches.
  - **Pagination:** on every table (VMs, products, channels and events).
  - **Event history per VM:**
    - date-range filter (*from*, *to*, or both);
    - whether each event was notified.
  - **Test messages:** a "send test" button for every channel.
- **Persistent state:** restarting the container doesn't resend alerts.
- **Retries:** each notification is retried up to 3 times.
- **Pluggable notifiers:** adding Slack, Teams, etc. means writing one class.

## How it works

```
                 ┌──────────────────────── Docker container ────────────────────────┐
                 │                                                                   │
  Browser ──────▶│  FastAPI + Jinja + HTMX (panel, login)                            │
                 │        │                                                          │
                 │        ▼                                                          │
                 │  SQLite (/data/monitor.db) ◀──── Monitor (async loop, every 30 s) │
                 │                                     │  ping / TCP connect         │
                 └─────────────────────────────────────┼─────────────────────────────┘
                                                       ▼
                                         VMs ──▶ state change? ──▶ Telegram / Google Chat
```

The monitor runs **inside the web process**, which is why the app always runs with a **single uvicorn worker**: more workers would duplicate checks and alerts.

## Quick start

Requirements: **Docker** with **Docker Compose**.

```bash
git clone <your-repo-url> heartbeat
cd heartbeat
cp .env.example .env
```

Edit `.env` and set at least these two values:

```ini
ADMIN_PASSWORD=a-strong-password
SECRET_KEY=<output of: python -c "import secrets; print(secrets.token_urlsafe(32))">
```

Start it:

```bash
docker compose up -d --build
```

Open **http://localhost:8000** and log in with `ADMIN_USER` / `ADMIN_PASSWORD`. Data is stored in `./data/monitor.db`.

Useful commands:

```bash
docker compose logs -f        # follow logs
docker compose restart        # restart
docker compose down           # stop (data in ./data is kept)
```

## Configuration

All settings come from environment variables, loaded from `.env`.

| Variable | Default | Description |
|---|---|---|
| `ADMIN_USER` | `admin` | Panel username |
| `ADMIN_PASSWORD` | `admin` | Panel password. **Change it**: a warning is logged while it's the default |
| `SECRET_KEY` | random | Signs the session cookie. If it's not set, a temporary one is generated and sessions are lost on every restart |
| `CHECK_INTERVAL` | `30` | Seconds between check rounds |
| `CHECK_TIMEOUT` | `2` | Seconds to wait for each check |
| `FAIL_THRESHOLD` | `3` | Consecutive failures before declaring a VM **down** |
| `RECOVER_THRESHOLD` | `1` | Consecutive successes before declaring it **recovered** |
| `NOTIFY_INITIAL_DOWN` | `true` | Alert if a VM is already down when it's added |
| `MAX_CONCURRENT_CHECKS` | `100` | Maximum checks running in parallel |
| `ICMP_PRIVILEGED` | `true` | Use raw ICMP sockets. Inside Docker (root) leave it at `true`; when running as a non-root user on Linux, use `false` |
| `DATA_DIR` | `/data` (Docker) · `./data` (local) | Folder that holds the SQLite database |
| `TZ` | `America/Argentina/Buenos_Aires` | Time zone used by the panel and the messages |

After changing `.env`, run `docker compose up -d` to apply it.

## Using the panel

1. **+ Client**: create the client, for example "ACME Corp".
2. Inside the client, **+ Channel**: choose Telegram or Google Chat (see [Notification channels](#notification-channels)), save, and press **Send test**.
3. **+ Product**, for example "Customer portal".
4. Inside the product, **+ VM**: enter the name, IP or hostname, an optional description and the check type:
   - **Ping (ICMP)**: the simplest option.
   - **TCP port**: pick a port the VM always has open.

The **dashboard** shows every client with its products and VMs:

- you can collapse each client or product, and the panel remembers it;
- a collapsed section still shows its live status counts;
- VMs that are down are always listed first.

Each **VM page** shows:

- its current status, latency, last check and last change;
- its event history, with a date-range filter to investigate incidents.

> **Latency** is the value from the most recent successful check: one ping packet, or the time to open the TCP connection. It's updated every `CHECK_INTERVAL` seconds and shows "—" when the last check failed.

## Notification channels

### Telegram

1. In Telegram, talk to **@BotFather**, send `/newbot` and copy the **token**.
2. Open a chat with your new bot and send `/start`. For a group, add the bot to it and write any message.
3. In Heartbeat, paste the token and press **🔍 Detect**: choose the chat and the Chat ID is filled in for you.

### Google Chat

1. Open the space that should receive the alerts.
2. Go to **Apps & integrations → Webhooks → Add webhook** and copy the URL.
3. Paste it in Heartbeat.

A VM's down and recovery messages are grouped in the same thread.

## When does it alert?

| Situation | Alert? |
|---|---|
| New VM, or service restart, and the VM responds | No (initial state) |
| New VM that's already down | Yes, if `NOTIFY_INITIAL_DOWN=true` |
| `FAIL_THRESHOLD` consecutive failures | 🔴 Yes, once |
| Still down | No |
| Responds again | 🟢 Yes, once, with the downtime duration |
| Isolated failures below the threshold | No |
| Paused VM | It isn't checked |

State is stored in the database, so restarting the container doesn't resend alerts. If a notification fails it's retried 3 times, and the result shows in the VM's history (*Notified* column).

## Networking

The container must be able to reach the VMs' IPs.

- **Routable networks** (LAN, public IPs): the default `ports: "8000:8000"` setup works.
- **VMs reachable only from the host** (VPN, custom routes): in `docker-compose.yml`, remove `ports` and uncomment `network_mode: host`. On Linux the container then uses the host's network directly.

## Running in production

- **Credentials:** set a strong `ADMIN_PASSWORD` and a fixed `SECRET_KEY`.
- **HTTPS:** put the panel behind a reverse proxy (Nginx, Caddy, Traefik) instead of exposing port 8000 directly. The app already trusts `X-Forwarded-*` headers (`--proxy-headers`).
- **Restrict access:** limit the panel to your network or VPN if possible.
- **Sensitive data:** the database contains bot tokens and webhook URLs. Protect `./data`, and never commit it or `.env` to git (both are already in `.gitignore`).

## Backup, restore and updates

**Backup:** everything lives in `data/monitor.db`.

```bash
docker compose stop
cp data/monitor.db backups/monitor-$(date +%F).db
docker compose start
```

**Restore:** stop the container, replace `data/monitor.db` with the backup, and start it again.

**Update:**

```bash
git pull
docker compose up -d --build
```

Schema migrations run automatically on startup. Even so, back up the database before updating.

## Health check

`GET /health` (no login required) returns:

```json
{ "status": "ok", "monitor_running": true, "last_run_at": "2026-10-17T05:00:00Z" }
```

Docker uses it as the container's `HEALTHCHECK`, and you can also point an external monitor at it.

## Troubleshooting

| Problem | Likely cause / fix |
|---|---|
| A VM shows **down** but it's up | The firewall blocks ICMP: switch the VM to a **TCP port** check |
| Every VM is down | The container can't reach that network: see [Networking](#networking) |
| A phone or laptop flips between up and down | Normal: devices put their Wi-Fi to sleep when idle |
| Telegram's **Detect** finds no chats | Send `/start` to the bot (or write in the group) first, then try again |
| I'm logged out after every restart | `SECRET_KEY` isn't set in `.env` |
| A notification wasn't delivered | Check the *Notified* column in the VM's history, then `docker compose logs` |

## Development

```bash
python -m venv .venv
.venv/Scripts/pip install -r requirements.txt pytest     # Linux/macOS: .venv/bin/pip
.venv/Scripts/python -m pytest -q                        # run the tests
.venv/Scripts/uvicorn app.main:app --reload              # dev server at :8000
```

Outside Docker, ICMP ping may need privileges. On Linux without root, set `ICMP_PRIVILEGED=false`.

**Stack:** FastAPI · SQLModel/SQLite · Jinja2 · HTMX · Pico CSS · icmplib · httpx.

## Adding a new integration

Create a class in `app/notifiers/` that inherits from `Notifier`:

```python
from app.notifiers.base import ConfigField, Notifier, register, event_rows

class SlackNotifier(Notifier):
    type = "slack"
    label = "Slack"
    fields = [ConfigField("webhook_url", "Webhook URL", placeholder="https://hooks.slack.com/…", secret=True)]
    help_html = "<ol><li>Create an Incoming Webhook in Slack…</li></ol>"

    async def send(self, config: dict, event) -> None:
        ...  # build the message with event_rows(event) and post it

register(SlackNotifier())
```

Then import the new module in `app/notifiers/__init__.py`. The channel form picks up its fields and help text automatically:

- fields marked `secret=True` are shown as password inputs;
- `validate(config)` lets you add extra validation;
- each channel's configuration is stored as JSON in `notificationchannel.config`.

## Project structure

```
app/
├── main.py            # FastAPI app, lifespan (starts the monitor), /health
├── config.py          # settings from environment / .env
├── db.py              # SQLite engine and migrations
├── models.py          # Client, Product, VM, NotificationChannel, Event
├── monitor/
│   ├── checks.py      # ICMP and TCP checks
│   └── engine.py      # state machine (up/down transitions) and loop
├── notifiers/         # Notifier base class, Telegram, Google Chat
├── routes/            # dashboard, clients, products, VMs, channels
├── pagination.py      # shared pagination helper
└── templates/         # Jinja + HTMX views and partials
tests/                 # pytest suite
```

## Roadmap

- [ ] **Services** under each VM: HTTP or TCP checks per service, using the same engine and notifiers.
- [ ] More integrations (Slack, Microsoft Teams, e-mail).
- [ ] Latency history and charts per VM.
