# Architecture

How the Capsule Farmer bot works and how the code is structured.

---

## Overview

The bot pretends to watch LoL Esports streams by sending periodic HTTP heartbeats to Riot's rewards API. Riot's system counts watch time based on these heartbeats and awards capsule drops when thresholds are met. No actual video stream is loaded -- the bot only sends lightweight JSON POST requests.

### High-level flow

```
1. Load config (accounts, settings)
2. Fetch list of currently live matches from Riot's public API
3. For each account:
   a. Authenticate (load saved cookies or do full OAuth2 login)
   b. Every 2 minutes: send a "watch" heartbeat for each live match
   c. Periodically refresh the session token before it expires
4. Display live status in a terminal UI
```

---

## Project Structure

```
CapsuleFarmerEvolved/
├── config/
│   ├── config.yaml              # Your config (gitignored)
│   ├── config.yaml.example      # Template
│   ├── bestStreams.txt           # Preferred stream channels (fetched from GitHub at startup)
│   └── confighelper.html        # Browser-based config generator
├── src/
│   ├── main.py                  # Entry point, thread orchestration
│   ├── Browser.py               # HTTP client: auth, heartbeats, drops, session management
│   ├── Config.py                # YAML config loader
│   ├── DataProviderThread.py    # Polls Riot API for live matches
│   ├── FarmThread.py            # Per-account farming loop
│   ├── GuiThread.py             # Terminal UI (rich library)
│   ├── IMAP.py                  # 2FA code fetcher via IMAP IDLE
│   ├── Logger.py                # Rotating file logger setup
│   ├── Match.py                 # Match dataclass
│   ├── Notifier.py              # Email + push notification sender
│   ├── Restarter.py             # Backoff delays for failed accounts
│   ├── SharedData.py            # Inter-thread shared state
│   ├── Stats.py                 # Per-account status and metrics
│   ├── VersionManager.py        # Checks GitHub for newer versions
│   ├── AssertCondition.py       # HTTP status assertion helper
│   ├── extract_browser_cookies.py  # Reads cookies from LibreWolf/Firefox
│   ├── browser_login.py         # Playwright-based manual login
│   ├── sessions/                # Saved session cookies (pickle files)
│   ├── logs/                    # Log files
│   └── Exceptions/
│       ├── CapsuleFarmerEvolvedException.py  # Base exception
│       ├── StatusCodeAssertException.py      # Unexpected HTTP status
│       ├── RateLimitException.py             # HTTP 429
│       ├── NoAccessTokenException.py         # Missing auth token
│       ├── InvalidCredentialsException.py    # Bad config credentials
│       ├── InvalidIMAPCredentialsException.py # Bad IMAP login
│       ├── Fail2FAException.py               # 2FA code rejected
│       └── FailFind2FAException.py           # 2FA email not found
├── Dockerfile
├── Pipfile / Pipfile.lock
└── README.md
```

---

## Threading Model

The bot uses Python's `threading` module. All threads are daemons (they die when the main thread exits).

```
Main thread (main.py)
│
├── GuiThread              # Renders terminal status table every 1s
├── DataProviderThread     # Fetches live matches every 60s
├── FarmThread [Account1]  # Login + heartbeat loop for account 1
├── FarmThread [Account2]  # Login + heartbeat loop for account 2
└── ...                    # One FarmThread per configured account
```

### Main thread (`main.py`)

The main thread is a supervisor. Every 5 seconds it:
1. Checks if any account needs a new FarmThread (not running, restarter allows it)
2. Detects dead FarmThreads and schedules restarts with backoff delays
3. Removes dead threads from the pool

It never does any network I/O itself.

### DataProviderThread

Runs independently. Every 60 seconds:
1. Calls `GET /persisted/gw/getLive` to get currently live matches
2. Calls `GET /persisted/gw/getSchedule` to find the next upcoming match
3. Writes results to `SharedData` (read by all FarmThreads)

Uses the public Riot esports API with a hardcoded API key (no account auth needed).

### FarmThread (one per account)

The core farming loop:

```python
while True:
    maintainSession()          # Refresh token if <10 min until expiry
    sendWatchToLive()          # POST heartbeat for each live match
    checkNewDrops()            # GET earned drops (for display only)
    sleep(120)                 # Wait 2 minutes
```

If the thread crashes, the main thread detects it and creates a new one after a backoff delay.

### GuiThread

Renders a `rich.Live` table to the terminal every second showing:
- Account status (LIVE, LOGIN FAILED, etc.)
- Current live matches
- Session drops / total drops
- Last check timestamp

### Synchronization

There is one shared lock: `refreshLock`. It prevents concurrent login attempts (which would race on shared auth cookies) and is also used by the GUI thread to avoid display tearing during login output.

`SharedData` is read/written without locks. This is safe enough because the data (live match list, next match time) is non-critical and eventually consistent.

---

## Authentication

### Why cookies?

Riot added hCaptcha to `auth.riotgames.com` in 2023. The bot can't solve captchas, so it needs session cookies from a real browser where the user already logged in.

### Cookie sources

1. **`extract_browser_cookies.py`** -- reads `cookies.sqlite` from LibreWolf/Firefox directly using SQLite. Requires the browser to be closed (it locks the DB).

2. **`browser_login.py`** -- opens a real Chromium window via Playwright. The user solves the captcha manually; the script captures the resulting cookies.

Both scripts save cookies as a Python pickle dict to `sessions/<AccountName>.saved`.

### Full OAuth2 login flow (Browser.login)

When saved cookies are missing or expired, the bot attempts a full login:

```
Step 1: GET  login.leagueoflegends.com         → seed cookies
Step 2: POST auth.riotgames.com/authorization   → initialize auth session
Step 3: PUT  auth.riotgames.com/authorization   → submit username + password
Step 4: (if 2FA) PUT with verification code
Step 5: GET  redirect URI from OAuth response    → follow OAuth redirect
Step 6: Parse HTML for token + state hidden inputs
Step 7: POST to 4 SSO endpoints                 → establish cross-domain sessions
Step 8: GET  auth.riotgames.com/authorize?prompt=none → silent OAuth code grant
Step 9: GET  account.rewards.lolesports.com/session/token → get access_token
Step 10: Save cookies to disk
```

**Important:** Step 2 (POST to initialize) is critical. The original upstream code skipped this and went straight to PUT, which broke when Riot started requiring session initialization first.

### Session management

- The `access_token` is a JWT with a 1-hour expiry
- `maintainSession()` decodes the JWT and calls `refreshSession()` when <10 minutes remain
- `refreshSession()` hits `GET /v1/session/refresh` which returns a new token
- If refresh fails (e.g., session fully expired), the bot logs a warning but continues sending heartbeats -- they may still work with the old token

### Saved session fast path

On startup, each FarmThread tries `hasValidSavedSession()`:
1. Load pickle from `sessions/<account>.saved`
2. Decode the JWT, check expiry
3. If valid: skip login entirely (status: SESSION RESTORED)
4. If expired: try `refreshSession()`. If that works, skip login. If not, fall through to full login.

---

## Watch Heartbeats

This is the core mechanism that earns capsules.

### What gets sent

```
POST https://rex.rewards.lolesports.com/v1/events/watch

{
    "stream_id": "riotgames",           # Twitch channel name
    "source": "twitch",                 # Stream platform
    "stream_position_time": "2026-...", # Current UTC timestamp (ISO 8601)
    "geolocation": {"code": "CZ", "area": "EU"},
    "tournament_id": "1234567890"       # From the live matches API
}
```

The bot sends one heartbeat per live match, every 120 seconds. Riot expects a heartbeat roughly every 60-120s to count as "watching".

### Stream selection

When a match has multiple streams (e.g., riotgames, riotgames2, lck), the bot picks the one listed in `bestStreams.txt` (fetched from GitHub at startup). If none match, it uses the first available stream.

### What the server responds

- **201 Created** -- heartbeat accepted (capsule watch time incremented)
- **429 Too Many Requests** -- rate limited (bot retries with backoff)
- **5xx** -- server error (bot retries with backoff)

---

## Drop Checking

Separate from heartbeats. The bot calls:

```
GET https://account.service.lolesports.com/fandom-account/v1/earnedDrops?locale=en_GB&site=LOLESPORTS
Authorization: Bearer <access_token>
```

This returns all drops the account has ever earned. The bot compares timestamps to find new ones and updates the terminal display.

**Known limitation:** This endpoint returns 401 when the access token is expired or was obtained via browser cookie extraction (the rewards session isn't fully established). Capsules are still earned via heartbeats -- the 401 only affects the drop count display.

---

## Retry Logic

All HTTP requests go through `Browser._request_with_retry()`:

| Condition | Behavior |
|---|---|
| `httpx.TimeoutException` | Retry up to 3 times with exponential backoff (2^n + jitter) |
| HTTP 429 | Read `Retry-After` header, add jitter, retry. Raise `RateLimitException` after max retries. |
| HTTP 5xx | Same backoff as timeout |
| HTTP 2xx/3xx/4xx | Return immediately (no retry) |

JSON responses go through `Browser._safe_json()` which checks the status code and content-type before calling `.json()`, preventing crashes on HTML error pages or empty responses.

---

## Restart Backoff

When a FarmThread dies (crash, login failure), the `Restarter` class determines when to try again:

| Consecutive failures | Delay |
|---|---|
| 0 | Immediate |
| 1 | 10 seconds |
| 2 | 30 seconds |
| 3 | 2.5 minutes |
| 4 | 5 minutes |
| 5 | 10 minutes |
| 6+ | 30 minutes |

A successful login resets the counter to 0.

---

## Notifications

The `Notifier` class sends alerts through two optional channels:

- **SMTP email** -- uses `smtplib` with STARTTLS
- **ntfy.sh push** -- HTTP POST to `https://ntfy.sh/<topic>` (works even when SMTP ports are blocked)

Both channels fire simultaneously if configured. Notifications are rate-limited to 1 per event key per hour (3600s cooldown) to avoid spam. Events:

- `login_failed_<account>` -- triggered after 3+ consecutive login failures
- `imap_failed_<account>` -- triggered on IMAP credential failure
- `crash_<account>` -- triggered on unhandled exception in FarmThread

---

## Cookie Format

Session cookies are stored as Python pickle files at `sessions/<AccountName>.saved`.

The pickle contains a `dict[str, str]` mapping cookie names to values. Key cookies:

| Cookie | Domain | Purpose |
|---|---|---|
| `access_token` | `account.rewards.lolesports.com` | JWT for API auth (1h expiry) |
| `__Secure-access_token` | `.lolesports.com` | Same token, browser-prefixed variant |
| `PVPNET_TOKEN_NA` | `.riotgames.com` | Riot session token |
| Various `_ga`, `_gid`, etc. | various | Analytics (not functionally important) |

When loading browser-extracted cookies, the bot strips `__Secure-` prefixes and creates unprefixed aliases so both cookie naming conventions work.

Old-format cookies (CookieJar objects from the original `cloudscraper` version) are detected and discarded, triggering a re-login.

---

## Key Constants

| Constant | Value | Location | Purpose |
|---|---|---|---|
| `STREAM_WATCH_INTERVAL` | 120s | `Browser.py` | Sleep between heartbeat cycles |
| `SESSION_REFRESH_INTERVAL` | 1800s | `Browser.py` | (Defined but not used directly; JWT expiry check with 600s threshold controls refresh) |
| JWT refresh threshold | 600s | `Browser.__needSessionRefresh()` | Refresh when <10 min until token expiry |
| `DEFAULT_SLEEP_DURATION` | 60s | `DataProviderThread.py` | Polling interval for live matches |
| `COOLDOWN` | 3600s | `Notifier.py` | Rate limit between duplicate notifications |
| `RIOT_API_KEY` | `0TvQn...` | `Config.py` | Public API key for esports endpoints |
| `CURRENT_VERSION` | 1.4 | `main.py` | Displayed in banner, checked against GitHub releases |

---

## Data Flow

```
                    ┌─────────────────────┐
                    │  Riot Esports API   │
                    │ (public, no auth)   │
                    └────────┬────────────┘
                             │ GET /getLive, /getSchedule
                             ▼
                   ┌───────────────────┐
                   │ DataProviderThread │  polls every 60s
                   └────────┬──────────┘
                            │ writes
                            ▼
                      ┌───────────┐
                      │ SharedData │  liveMatches, timeUntilNextMatch
                      └─────┬─────┘
                            │ reads
              ┌─────────────┼─────────────┐
              ▼             ▼             ▼
        ┌───────────┐ ┌───────────┐ ┌───────────┐
        │FarmThread │ │FarmThread │ │FarmThread │  one per account
        │ Account1  │ │ Account2  │ │ Account3  │
        └─────┬─────┘ └─────┬─────┘ └─────┬─────┘
              │             │             │
              │   POST /events/watch (heartbeats)
              │   GET /earnedDrops (drop count)
              │             │             │
              ▼             ▼             ▼
        ┌─────────────────────────────────────┐
        │         Riot Rewards API            │
        │  (requires auth cookies)            │
        └─────────────────────────────────────┘

              │ writes          reads │
              ▼                       ▼
        ┌──────────┐           ┌───────────┐
        │  Stats   │ ────────► │ GuiThread │  renders table every 1s
        └──────────┘           └───────────┘
```

---

## Exception Hierarchy

```
Exception
└── CapsuleFarmerEvolvedException       # Base (caught in main.py for fatal errors)
    ├── StatusCodeAssertException       # Unexpected HTTP status code
    ├── RateLimitException              # HTTP 429 (carries retryAfter value)
    ├── NoAccessTokenException          # No access_token in cookie jar
    ├── InvalidCredentialsException     # Config has only placeholder credentials
    ├── InvalidIMAPCredentialsException # IMAP login failed
    ├── Fail2FAException                # 2FA code was rejected by Riot
    └── FailFind2FAException            # Couldn't find 2FA code in email
```

**Handling strategy:**
- `InvalidIMAPCredentialsException` disables the account thread permanently
- `RateLimitException` and `Fail2FAException` cause login to return `False` (thread restarts with backoff)
- `StatusCodeAssertException` in heartbeats is caught per-match (other matches still get heartbeats)
- `NoAccessTokenException` in `maintainSession` is caught and logged (heartbeats continue)
- Unhandled exceptions in `FarmThread.run()` are caught, logged, and trigger a notification
