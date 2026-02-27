# Capsule Farmer Evolved

Farm LoL Esports capsule drops by sending watch heartbeats to Riot's rewards API. No browser required at runtime.

> **Fork note:** Maintained fork of [LeagueOfPoro/CapsuleFarmerEvolved](https://github.com/LeagueOfPoro/CapsuleFarmerEvolved) which stopped working in 2023. See [Changes from upstream](#changes-from-upstream) for details.

---

## Table of Contents

- [Prerequisites](#prerequisites)
- [Installation](#installation)
  - [Windows](#windows)
  - [Linux (Debian/Ubuntu)](#linux-debianubuntu)
  - [Docker](#docker)
- [Configuration](#configuration)
  - [Basic config](#basic-config)
  - [Multiple accounts](#multiple-accounts)
  - [2FA via IMAP (optional)](#2fa-via-imap-optional)
  - [Email and push notifications (optional)](#email-and-push-notifications-optional)
  - [Discord webhook (optional)](#discord-webhook-optional)
  - [All config options](#all-config-options)
- [Authentication](#authentication)
  - [Option A: Extract cookies from LibreWolf/Firefox](#option-a-extract-cookies-from-librewolffirefox-recommended)
  - [Option B: Playwright browser login](#option-b-playwright-browser-login)
  - [When to re-authenticate](#when-to-re-authenticate)
- [Usage](#usage)
  - [Run locally](#run-locally)
  - [Run on a headless server](#run-on-a-headless-server)
- [Notifications](#notifications)
  - [ntfy.sh push notifications](#ntfysh-push-notifications)
  - [Email notifications (SMTP)](#email-notifications-smtp)
  - [What triggers a notification](#what-triggers-a-notification)
- [Troubleshooting](#troubleshooting)
- [Changes from upstream](#changes-from-upstream)
- [Architecture](#architecture)
- [Disclaimer](#disclaimer)
- [License](#license)

---

## Prerequisites

Install these before proceeding:

| Software | Version | Why | Download |
|---|---|---|---|
| **Python** | 3.10 or newer | Runs the bot | [python.org/downloads](https://www.python.org/downloads/) |
| **pip** | (bundled with Python) | Installs Python packages | Included with Python |
| **Git** | any | Clones this repo | [git-scm.com](https://git-scm.com/downloads) |
| **LibreWolf** or **Firefox** | any | Log into lolesports.com to get session cookies | [librewolf.net](https://librewolf.net/) or [firefox.com](https://www.mozilla.org/firefox/) |

**Optional:**

| Software | Why | Download |
|---|---|---|
| **pipenv** | Manages a virtual environment + dependencies automatically | `pip install pipenv` |
| **screen** or **tmux** | Keeps the bot running on a headless server | `apt install screen` |

### Windows-specific notes

- During Python installation, check **"Add Python to PATH"**.
- Use PowerShell or Git Bash for all commands below.
- If `python` doesn't work, try `python3` or `py`.

### Linux-specific notes

- On Debian/Ubuntu: `sudo apt install python3 python3-pip python3-venv git`
- On servers without a desktop, you won't have a browser. Authenticate on your local machine and upload the session cookies (see [Run on a headless server](#run-on-a-headless-server)).

---

## Installation

### Windows

```bash
git clone https://github.com/BlackSiroGhost/CapsuleFarmerEvolved.git
cd CapsuleFarmerEvolved

# Option A: Using pipenv (recommended)
pip install pipenv
pipenv install

# Option B: Using venv
python -m venv venv
venv\Scripts\activate
pip install httpx[http2] requests beautifulsoup4 pyyaml rich pyjwt imaplib2
```

### Linux (Debian/Ubuntu)

```bash
git clone https://github.com/BlackSiroGhost/CapsuleFarmerEvolved.git
cd CapsuleFarmerEvolved

# Option A: Using pipenv
pip install pipenv
pipenv install

# Option B: Using venv (better for servers)
python3 -m venv venv
source venv/bin/activate
pip install httpx[http2] requests beautifulsoup4 pyyaml rich pyjwt imaplib2
```

### Docker

```bash
docker build -t capsulefarmer .
docker run -v /path/to/config:/config -v /path/to/sessions:/sessions capsulefarmer
```

---

## Configuration

### Basic config

```bash
cp config/config.yaml.example config/config.yaml
```

Edit `config/config.yaml`:

```yaml
accounts:
  MyAccount:
    username: "YourRiotUsername"
    password: "YourRiotPassword"
```

The account name (`MyAccount`) is a display label. It can be anything, but it's also used as the session filename (`sessions/MyAccount.saved`).

### Multiple accounts

Each account needs its own Riot credentials and its own session cookies. You cannot share cookies between accounts.

```yaml
accounts:
  Account1:
    username: "user1"
    password: "pass1"
  Account2:
    username: "user2"
    password: "pass2"
```

### 2FA via IMAP (optional)

If your Riot account has two-factor authentication enabled, the bot can automatically fetch the verification code from your email via IMAP:

```yaml
accounts:
  MyAccount:
    username: "YourRiotUsername"
    password: "YourRiotPassword"
    imapUsername: "your@gmail.com"
    imapPassword: "your-app-password"
    imapServer: "imap.gmail.com"
```

For Gmail, you need an [App Password](https://myaccount.google.com/apppasswords) (not your regular password).

### Email and push notifications (optional)

Get notified when the bot fails to login, crashes, or has IMAP issues. See [Notifications](#notifications) for full setup.

```yaml
# Push notifications via ntfy.sh (recommended — works everywhere)
ntfyTopic: "my-capsulefarmer-topic"

# Email notifications via SMTP (optional — requires outbound port 587)
smtpServer: "smtp.gmail.com"
smtpPort: 587
smtpUser: "you@gmail.com"
smtpPassword: "xxxx xxxx xxxx xxxx"
notifyEmail: "you@gmail.com"
```

### Discord webhook (optional)

Get a message in Discord when you receive a drop:

```yaml
connectorDropsUrl: "https://discord.com/api/webhooks/..."
```

### All config options

| Key | Type | Default | Description |
|---|---|---|---|
| `accounts` | map | *required* | Riot account credentials (see above) |
| `debug` | bool | `false` | Enable verbose debug logging |
| `connectorDropsUrl` | string | `""` | Discord webhook URL for drop notifications |
| `showHistoricalDrops` | bool | `true` | Show lifetime drop count in the terminal UI |
| `smtpServer` | string | `""` | SMTP server for email alerts |
| `smtpPort` | int | `587` | SMTP port (587 for STARTTLS) |
| `smtpUser` | string | `""` | SMTP login username |
| `smtpPassword` | string | `""` | SMTP login password (use an app password) |
| `notifyEmail` | string | `""` | Email address to send alerts to |
| `ntfyTopic` | string | `""` | ntfy.sh topic name for push notifications |

---

## Authentication

Riot added hCaptcha to their login page, so the bot cannot log in via API alone. You need to log into [lolesports.com](https://lolesports.com) in a real browser first, then extract the session cookies.

### Option A: Extract cookies from LibreWolf/Firefox (recommended)

1. Open LibreWolf (or Firefox)
2. Go to [https://lolesports.com](https://lolesports.com) and log in with your Riot account
3. **Close the browser completely** (it locks the cookie database while running)
4. Run the extraction script:

```bash
# With pipenv
pipenv run python src/extract_browser_cookies.py -c config/config.yaml

# With venv
python src/extract_browser_cookies.py -c config/config.yaml
```

The script reads your browser's `cookies.sqlite` and saves session data to `sessions/<AccountName>.saved`.

**Custom browser profile path:**

By default, the script looks for LibreWolf's cookie database on Windows:
```
%APPDATA%\librewolf\Profiles\<profile>\cookies.sqlite
```

For Firefox:
```
%APPDATA%\Mozilla\Firefox\Profiles\<profile>\cookies.sqlite
```

Override with `--db`:
```bash
python src/extract_browser_cookies.py -c config/config.yaml --db "/path/to/cookies.sqlite"
```

### Option B: Playwright browser login

Opens a Chromium window where you log in manually (solving the captcha yourself). Useful when you can't close the browser for Option A.

```bash
# Install Playwright browsers (first time only)
pipenv run playwright install chromium

# Run the login flow
pipenv run python src/browser_login.py -c config/config.yaml
```

The script auto-fills your credentials, waits for you to complete the captcha, then saves cookies automatically.

### When to re-authenticate

Session cookies expire periodically. When the bot log shows `LOGIN FAILED`, `auth_failure`, or `401` errors, you need to re-authenticate:

1. Log into lolesports.com in your browser
2. Close the browser
3. Re-run the cookie extraction script
4. Restart the bot (or upload new cookies to your server)

---

## Usage

### Run locally

```bash
# With pipenv (from project root)
pipenv run python src/main.py -c config/config.yaml

# With venv (from project root)
source venv/bin/activate    # Linux
venv\Scripts\activate       # Windows
python src/main.py -c config/config.yaml
```

The bot shows a live terminal UI with account status:

| Status | Meaning |
|---|---|
| **SESSION RESTORED** | Loaded saved cookies successfully |
| **LIVE** | Watching matches and sending heartbeats |
| **LOGIN** | Attempting to log in |
| **LOGIN FAILED** | Cookies expired — re-authenticate |
| **RIOT SERVERS OVERLOADED** | Heartbeat failed, will retry next cycle |

### Run on a headless server

The workflow: authenticate on your **local machine** (where you have a browser), then deploy the session cookies to the server.

#### 1. Set up the server

```bash
ssh user@your-server

# Clone and install
git clone https://github.com/BlackSiroGhost/CapsuleFarmerEvolved.git /home/capsulefarmer
cd /home/capsulefarmer
python3 -m venv venv
source venv/bin/activate
pip install httpx[http2] requests beautifulsoup4 pyyaml rich pyjwt imaplib2

# Create config
cp config/config.yaml.example config/config.yaml
nano config/config.yaml

# Create directories
mkdir -p sessions logs
```

#### 2. Extract cookies locally and upload

On your local machine:

```bash
# Extract cookies
pipenv run python src/extract_browser_cookies.py -c config/config.yaml

# Upload session file to server
scp src/sessions/MyAccount.saved user@your-server:/home/capsulefarmer/sessions/
```

#### 3. Start the bot

```bash
ssh user@your-server
cd /home/capsulefarmer
screen -dmS capsule-farmer bash -c "source venv/bin/activate && python src/main.py -c config/config.yaml"
```

#### 4. Check status

```bash
# Attach to screen (Ctrl+A, D to detach)
screen -r capsule-farmer

# Or check the log file
tail -f /home/capsulefarmer/logs/capsulefarmer.log
```

#### 5. Refresh cookies when they expire

When the log shows login failures:

```bash
# On your local machine: re-authenticate and upload
pipenv run python src/extract_browser_cookies.py -c config/config.yaml
scp src/sessions/MyAccount.saved user@your-server:/home/capsulefarmer/sessions/

# On the server: restart the bot
screen -S capsule-farmer -X quit
cd /home/capsulefarmer && screen -dmS capsule-farmer bash -c "source venv/bin/activate && python src/main.py -c config/config.yaml"
```

---

## Notifications

The bot can alert you when something goes wrong. Both channels are optional and can be used together.

### ntfy.sh push notifications

[ntfy.sh](https://ntfy.sh) sends push notifications over HTTPS (port 443). Works even on servers where SMTP ports are blocked.

**Setup:**

1. Pick a unique topic name (e.g., `capsulefarmer-myname`)
2. Add it to your config:
   ```yaml
   ntfyTopic: "capsulefarmer-myname"
   ```
3. Subscribe on your phone or desktop:
   - **Android/iOS:** Install the [ntfy app](https://ntfy.sh/#subscribe-phone), subscribe to your topic
   - **Desktop:** Open `https://ntfy.sh/capsulefarmer-myname` in a browser
   - **CLI:** `curl -s ntfy.sh/capsulefarmer-myname/json`

No account or API key needed. Anyone who knows the topic name can read it, so pick something hard to guess.

### Email notifications (SMTP)

Sends email via SMTP with STARTTLS. Requires outbound port 587 to be open (some VPS providers block this).

**Setup for Gmail:**

1. Go to [https://myaccount.google.com/apppasswords](https://myaccount.google.com/apppasswords)
2. Generate an app password for "Mail"
3. Add to your config:
   ```yaml
   smtpServer: "smtp.gmail.com"
   smtpPort: 587
   smtpUser: "you@gmail.com"
   smtpPassword: "xxxx xxxx xxxx xxxx"
   notifyEmail: "you@gmail.com"
   ```

### What triggers a notification

| Event | Condition | Message |
|---|---|---|
| Login failure | 3+ consecutive failed logins | Account name + failure count + suggestion to refresh cookies |
| IMAP failure | IMAP credentials are invalid | Account name + "2FA code cannot be fetched" |
| Thread crash | Unhandled exception in a farm thread | Account name + "crashed and will try to recover" |

Notifications are rate-limited to **1 per event type per hour** to avoid spam. The bot will recover and retry automatically, so a single alert is enough.

---

## Troubleshooting

| Problem | Cause | Fix |
|---|---|---|
| `checkNewDrops: unexpected status 401` | Access token expired for the drops API. This is cosmetic — capsules are still earned via heartbeats. | Re-authenticate if you want accurate drop counts. |
| `LOGIN FAILED` | Session cookies expired. | Re-extract cookies from your browser (see [Authentication](#authentication)). |
| `Rate limited` / `429` | Too many API requests. The bot backs off automatically. | Wait. Reduce number of accounts if persistent. |
| `IMAP LOGIN FAILED` | Wrong email credentials for 2FA. | Check `imapUsername`, `imapPassword`, `imapServer` in config. For Gmail, use an app password. |
| `cookies.sqlite` locked | Browser is still running. | Close LibreWolf/Firefox completely before extracting cookies. |
| Bot starts but no heartbeats | No live matches right now. | The bot shows "Up next: ..." with the next scheduled match time. |
| Email notification not sending | SMTP port 587 blocked by VPS provider. | Use ntfy.sh instead (works over HTTPS port 443). |

---

## Changes from upstream

| Change | Details |
|---|---|
| Replaced `cloudscraper` with `httpx` | `cloudscraper` is abandoned and can't bypass modern Cloudflare. `httpx` with HTTP/2 works. |
| Fixed Riot OAuth2 auth flow | Added the required POST initialization step before PUT credentials. |
| Browser cookie authentication | Bypasses hCaptcha by extracting cookies from a real browser session. |
| Retry with exponential backoff | All API calls retry on 429 and 5xx with jitter. Handles `httpx.TimeoutException`. |
| Safe JSON parsing | All `.json()` calls check status code and content-type before parsing. |
| Graceful session refresh | `maintainSession()` catches all exceptions so heartbeats continue even when refresh fails. |
| Email and push notifications | Optional alerts via SMTP email and ntfy.sh when the bot encounters problems. |
| Watch interval increased | 60s to 120s to reduce rate limiting. |

---

## Architecture

See [ARCHITECTURE.md](ARCHITECTURE.md) for a detailed explanation of how the bot works internally and how the code is structured.

---

## Disclaimer

This tool is **not endorsed by Riot Games** and does not reflect the views or opinions of Riot Games or anyone officially involved in producing or managing Riot Games properties. Riot Games and all associated properties are trademarks or registered trademarks of Riot Games, Inc.

**Use at your own risk.** No bans have been reported but there is no guarantee.

## License

[CC BY-NC-SA 4.0](LICENSE) (inherited from upstream)
