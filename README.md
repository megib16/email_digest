# Email Digest

A personal Gmail triage tool for macOS. Several times a day it reads your recent mail (read-only), asks Claude to sort it into what needs a reply, what needs action, and what is noise, and then shows you a short digest as a Mac notification, in a local dashboard, and optionally on Telegram. It also remembers open threads, so it can remind you about emails you still owe a reply to and nudge you when someone hasn't answered yours.

## Features

- **Smart triage.** Each email is classified as `personal`, `important_automated` (bills, deadlines, security alerts) or `noise`. Noise is dropped, and automated mail is grouped by sender.
- **Three digest modes.** `morning` covers everything since the last run (up to 3 days back), `evening` covers the whole day, and `update` covers everything new since the last check.
- **Follow-up tracking.** Emails that need your reply, and emails of yours that expect an answer, are tracked per Gmail thread. Items clear themselves when the reply happens, and expire after 14 days. Unanswered sent mail is raised after 3 days, at most about once a day.
- **Local dashboard** at <http://localhost:8765> with open items, digest history, "Done" buttons and a "Check now" button.
- **Notifications.** A macOS notification with the headline, and optionally the full digest via a Telegram bot.
- **Runs by itself.** Three launchd agents handle the 8:00 and 19:00 digests, a check each time you return to your Mac, and the dashboard server.
- **Read-only Gmail access.** It only requests the `gmail.readonly` scope, so it can never send, delete or modify mail.

## How it works

```
Gmail API ──> gmail_client.py ──> summarize.py (Claude) ──> digest.py ──> notify.py (Mac / Telegram)
                                                               │
                              tracker.py + state.py <──────────┤
                                (state.json)                   └──> history/ ──> app.py (dashboard)
```

| File | Purpose |
| --- | --- |
| `digest.py` | Entry point and CLI. Fetches, analyzes, renders and records a digest. |
| `gmail_client.py` | Gmail OAuth and read-only fetching of incoming mail, sent mail and thread metadata. |
| `summarize.py` | Sends emails to Claude (`claude-haiku-5-5`) and parses its JSON classification. |
| `tracker.py` | Decides which threads to track, remind about or drop. |
| `state.py` | Atomic load and save of `state.json`. |
| `notify.py` | macOS notifications and optional Telegram messages. |
| `app.py`, `static/index.html` | FastAPI dashboard and its single-page UI. |
| `install.sh`, `launchd/` | Installs and removes the launchd agents. |
| `tests/` | pytest suite. |

## Requirements

- macOS (uses `osascript`, `ioreg` and `launchd`)
- Python 3
- An [Anthropic API key](https://console.anthropic.com/)
- A Google Cloud project with the Gmail API enabled and an OAuth client of type "Desktop app"
- Optional: a Telegram bot token and chat id

## Setup

1. **Create a virtualenv and install dependencies**

   ```sh
   python3 -m venv .venv
   .venv/bin/pip install -r requirements.txt
   ```

2. **Add your API keys.** Copy `.env.example` to `.env` and fill it in:

   ```sh
   cp .env.example .env
   ```

   ```
   ANTHROPIC_API_KEY=...
   # Optional, for the full digest on your phone:
   TELEGRAM_BOT_TOKEN=
   TELEGRAM_CHAT_ID=
   ```

3. **Add Gmail credentials.** In Google Cloud Console, enable the Gmail API, create an OAuth client ID (Desktop app), download the JSON, and save it as `credentials.json` in the project folder.

4. **Authorize once.** Run a dry run. A browser window opens for you to approve read-only access, and the token is saved to `token.json`.

   ```sh
   .venv/bin/python digest.py --print-only
   ```

## Usage

```sh
.venv/bin/python digest.py                      # auto: morning before noon, evening after
.venv/bin/python digest.py --mode morning       # or evening / update
.venv/bin/python digest.py --print-only         # dry run: nothing saved, no notifications
.venv/bin/python digest.py --done <ID>          # stop tracking an item (id prefix from the digest)
```

Scheduler flags (used by the launchd agents):

| Flag | Behavior |
| --- | --- |
| `--when-active HOURS` | Runs an `update` only if you used the keyboard or mouse in the last 2 minutes and no digest ran within `HOURS`. Silent otherwise. |
| `--if-stale HOURS` | Skips if a digest ran within `HOURS`, and retries up to 5 times while the network comes up. |

### Dashboard

```sh
.venv/bin/uvicorn app:app --port 8765
```

| Endpoint | Description |
| --- | --- |
| `GET /` | The dashboard page |
| `GET /api/overview` | Open items, last run time and recent digest history |
| `POST /api/items/{thread_id}/done` | Stop tracking an item |
| `POST /api/run?mode=update\|morning\|evening` | Run a check now (no notification) |

## Running automatically

```sh
./install.sh            # install and start the three launchd agents
./install.sh uninstall  # stop and remove them
```

| Agent | What it does |
| --- | --- |
| `com.megibida.emaildigest.schedule` | Runs a digest at 8:00 and 19:00. If the Mac is asleep, launchd runs it on wake. |
| `com.megibida.emaildigest.active` | Every 2 minutes, a cheap check that runs a digest when you are at the Mac and none ran in the last 2 hours. |
| `com.megibida.emaildigest.dashboard` | Keeps the dashboard running on `127.0.0.1:8765`. |

**Note:** the plist files hard-code absolute paths (`/Users/megibida/email_digest/...`) for the Python interpreter, the scripts and the log files. If you clone the project elsewhere or use a different user, edit the three files in `launchd/` before running `install.sh`. The installer also refuses to start if port 8765 is already in use.

Logs are written to `digest.log` and `dashboard.log`.

## Data and privacy

Everything stays on your machine except two things: email text is sent to the Anthropic API for classification (each body is truncated to 1500 characters for received mail and 800 for sent mail), and the digest is sent to Telegram if you configure it.

These local files are created at runtime and are git-ignored: `.env`, `credentials.json`, `token.json`, `state.json`, `history/`, `latest_digest.txt` and the log files.

## Tests

```sh
.venv/bin/pytest
```
