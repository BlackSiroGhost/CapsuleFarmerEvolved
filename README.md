# Capsule Farmer Evolved

Farm LoL Esports capsule drops by simulating watch events on lolesports.com. No browser required at runtime -- the bot sends lightweight API heartbeats to trick the server into thinking you're watching.

> **Fork note:** This is a maintained fork of [LeagueOfPoro/CapsuleFarmerEvolved](https://github.com/LeagueOfPoro/CapsuleFarmerEvolved) which stopped working in 2023. Key fixes: replaced `cloudscraper` with `httpx` (HTTP/2), fixed the broken Riot OAuth2 auth flow, added browser-cookie authentication to bypass hCaptcha, and added retry logic with exponential backoff.

## How It Works

The bot authenticates with your Riot account session cookies, then sends periodic "watch" heartbeats to Riot's rewards API. Riot thinks you're watching live LoL Esports streams and awards drops accordingly.

**Important:** Riot added hCaptcha to their login page, so the bot can no longer log in via API alone. You must log into [lolesports.com](https://lolesports.com) in a browser first, then extract your session cookies for the bot to use.

## Requirements

- Python 3.10+
- [pipenv](https://pipenv.pypa.io/) (recommended) or pip + venv
- A browser (Firefox, LibreWolf, or Chrome) where you're logged into lolesports.com

---

## Installation

### Windows

```bash
git clone https://github.com/BlackSiroGhost/CapsuleFarmerEvolved.git
cd CapsuleFarmerEvolved
pip install pipenv
pipenv install
```

### Linux (Debian/Ubuntu)

```bash
git clone https://github.com/BlackSiroGhost/CapsuleFarmerEvolved.git
cd CapsuleFarmerEvolved

# Option A: pipenv
pip install pipenv
pipenv install

# Option B: venv (better for servers)
python3 -m venv venv
source venv/bin/activate
pip install httpx[http2] requests beautifulsoup4 pyyaml rich pyjwt imaplib2
```

---

## Configuration

Copy the example config and add your Riot account:

```bash
cp config/config.yaml.example config/config.yaml
```

Edit `config/config.yaml`:

```yaml
accounts:
  MyAccount:
    username: "YourRiotUsername"
    password: "YourRiotPassword"

# Optional
# debug: true
# connectorDropsUrl: "https://discord.com/api/webhooks/..."
```

You can add multiple accounts:

```yaml
accounts:
  Account1:
    username: "user1"
    password: "pass1"
  Account2:
    username: "user2"
    password: "pass2"
```

### Optional: 2FA via IMAP

If your account has 2FA enabled, the bot can automatically fetch the code via IMAP:

```yaml
accounts:
  MyAccount:
    username: "YourRiotUsername"
    password: "YourRiotPassword"
    imapUsername: "your@email.com"
    imapPassword: "email-password"
    imapServer: "imap.gmail.com"
```

---

## Authentication

Since Riot now requires hCaptcha on login, the bot uses **browser session cookies** instead of API login. You have two options:

### Option A: Extract Cookies from LibreWolf/Firefox (Recommended)

1. Open LibreWolf or Firefox
2. Go to [https://lolesports.com](https://lolesports.com) and log in with your Riot account
3. **Close the browser** (it locks the cookie database)
4. Run the extraction script:

```bash
# From the project root
pipenv run python src/extract_browser_cookies.py -c config/config.yaml
```

The script reads your browser's `cookies.sqlite` and saves session cookies for each configured account.

**Custom browser profile path:**

```bash
pipenv run python src/extract_browser_cookies.py -c config/config.yaml --db "C:\path\to\cookies.sqlite"
```

Default path (LibreWolf on Windows):
```
%APPDATA%\librewolf\Profiles\<profile-name>\cookies.sqlite
```

For Firefox:
```
%APPDATA%\Mozilla\Firefox\Profiles\<profile-name>\cookies.sqlite
```

### Option B: Playwright Browser Login

If you prefer an automated browser flow:

```bash
pipenv run python src/browser_login.py -c config/config.yaml
```

This opens a Chromium window where you log in manually (solving hCaptcha yourself). Once logged in, the script saves the cookies automatically.

> **Note:** Cookies expire periodically. When the bot starts failing with `auth_failure` or `401` errors, re-run the cookie extraction.

---

## Usage

### Run locally

```bash
cd CapsuleFarmerEvolved
pipenv run python src/main.py -c config/config.yaml
```

Or with venv:

```bash
source venv/bin/activate
cd src
python main.py -c ../config/config.yaml
```

The bot will show a live TUI with the status of each account:

- **SESSION RESTORED** -- loaded saved cookies successfully
- **LIVE** -- watching matches and sending heartbeats
- **LOGIN FAILED** -- cookies expired, re-extract them

### Run on a headless server

The typical workflow is: authenticate on your local machine (where you have a browser), then deploy cookies to the server.

#### 1. Set up the server

```bash
ssh root@your-server

# Clone and install
git clone https://github.com/BlackSiroGhost/CapsuleFarmerEvolved.git /home/capsulefarmer
cd /home/capsulefarmer
python3 -m venv venv
source venv/bin/activate
pip install httpx[http2] requests beautifulsoup4 pyyaml rich pyjwt imaplib2

# Create config
cp config/config.yaml.example config/config.yaml
nano config/config.yaml  # Add your account(s)

# Create sessions directory
mkdir -p src/sessions
```

#### 2. Extract cookies locally and upload

On your local machine (where you have a browser):

```bash
# Extract cookies
pipenv run python src/extract_browser_cookies.py -c config/config.yaml

# Upload to server
scp src/sessions/YourAccount.saved root@your-server:/home/capsulefarmer/src/sessions/
```

#### 3. Start the bot in a screen session

```bash
ssh root@your-server
cd /home/capsulefarmer/src
screen -dmS capsule-farmer bash -c "source ../venv/bin/activate && python3 main.py -c ../config/config.yaml"
```

#### 4. Check status

```bash
# Attach to the screen session (Ctrl+A, D to detach)
screen -r capsule-farmer

# Or just check the log
tail -f /home/capsulefarmer/src/logs/capsulefarmer.log
```

#### 5. Refresh cookies when they expire

When the log shows `auth_failure` errors:

1. Log into lolesports.com in your local browser
2. Close the browser
3. Re-extract and upload:

```bash
# Local machine
pipenv run python src/extract_browser_cookies.py -c config/config.yaml
scp src/sessions/YourAccount.saved root@your-server:/home/capsulefarmer/src/sessions/

# Restart on server
ssh root@your-server "screen -S capsule-farmer -X quit; sleep 1; cd /home/capsulefarmer/src && screen -dmS capsule-farmer bash -c 'source ../venv/bin/activate && python3 main.py -c ../config/config.yaml'"
```

---

## Changes from Upstream

| Change | Details |
|---|---|
| Replaced `cloudscraper` with `httpx` | `cloudscraper` is abandoned and can't bypass modern Cloudflare. `httpx` with HTTP/2 works. |
| Fixed Riot OAuth2 auth flow | Added the required POST init step before PUT credentials. |
| Browser cookie authentication | Bypasses hCaptcha by using cookies from a real browser session. |
| Retry with exponential backoff | All API calls retry on 429 (rate limit) and 5xx errors with jitter. |
| Safe JSON parsing | All `.json()` calls are wrapped with status/content-type checks to prevent crashes. |
| Fixed Config.py comparison bug | `"username" != value` was always true; fixed to `value != "username"`. |
| Watch interval increased | 60s to 120s to reduce rate limiting. |

---

## Disclaimer

This tool is **not endorsed by Riot Games** and does not reflect the views or opinions of Riot Games or anyone officially involved in producing or managing Riot Games properties. Riot Games and all associated properties are trademarks or registered trademarks of Riot Games, Inc.

**Use at your own risk.** No bans have been reported but there is no guarantee. Riot has previously shadow-banned accounts using similar tools.

## License

[CC BY-NC-SA 4.0](LICENSE) (inherited from upstream)
