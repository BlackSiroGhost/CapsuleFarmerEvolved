"""
Browser-based login for CapsuleFarmerEvolved.

Run this on a machine with a display (not headless) to log in via
Riot's web auth (which requires hCaptcha). The resulting cookies are
saved to ./sessions/<account>.saved and can be copied to a headless
server where the bot runs using API-only session refresh.

Usage:
    pipenv run python src/browser_login.py -c config/config.yaml
"""

import argparse
import pickle
import sys
from pathlib import Path
from time import sleep

# Add src to path so Config import works when run from repo root
sys.path.insert(0, str(Path(__file__).parent))

from Config import Config


def extract_cookies_for_domain(context, domains):
    """Extract cookies from Playwright context as a flat dict, filtered by domains."""
    cookies = context.cookies()
    result = {}
    for c in cookies:
        if any(d in c["domain"] for d in domains):
            result[c["name"]] = c["value"]
    return result


def login_account(account_name, username, password):
    """Open a browser, navigate to lolesports login, wait for user to complete login."""
    from playwright.sync_api import sync_playwright

    sessions_dir = Path("./sessions")
    sessions_dir.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        )
        page = context.new_page()

        print(f"\n[{account_name}] Opening Riot login page...")
        page.goto("https://auth.riotgames.com/authorize"
                   "?client_id=esports-rna-prod"
                   "&redirect_uri=https://account.rewards.lolesports.com/v1/session/oauth-callback"
                   "&response_type=code&scope=openid",
                   wait_until="networkidle")

        # Try to auto-fill credentials
        try:
            page.wait_for_selector('input[name="username"]', timeout=10000)
            page.fill('input[name="username"]', username)
            page.fill('input[name="password"]', password)
            print(f"[{account_name}] Credentials filled automatically.")
            print(f"[{account_name}] >>> Solve the captcha (if shown), then click Sign In.")
            print(f"[{account_name}] >>> Complete any extra steps Riot asks for (2FA, account update, etc).")
        except Exception:
            print(f"[{account_name}] Could not auto-fill. Please log in manually in the browser window.")

        # Wait for the user to complete login + any Riot account steps
        # We detect completion by leaving the authenticate.riotgames.com domain
        print(f"[{account_name}] Waiting for login to complete (you have 5 minutes)...")
        try:
            # Wait until we're no longer on authenticate.riotgames.com
            page.wait_for_function(
                """() => !window.location.hostname.includes('authenticate.riotgames.com')""",
                timeout=300000  # 5 minutes
            )
            print(f"[{account_name}] Login redirect detected! Current URL: {page.url[:80]}...")
        except Exception:
            print(f"[{account_name}] Still on auth page after timeout. Current URL: {page.url[:80]}...")
            print(f"[{account_name}] Will try to extract cookies anyway...")

        # Small delay for redirects to settle
        sleep(3)

        # Navigate to lolesports to ensure we have all the right cookies
        print(f"[{account_name}] Navigating to lolesports.com to establish session...")
        try:
            page.goto("https://lolesports.com", wait_until="networkidle", timeout=30000)
            sleep(2)
        except Exception:
            print(f"[{account_name}] Could not load lolesports.com, continuing with current cookies...")

        # Now try the authorize flow with prompt=none to get the rewards session
        print(f"[{account_name}] Establishing rewards session...")
        try:
            page.goto("https://auth.riotgames.com/authorize"
                       "?client_id=esports-rna-prod"
                       "&redirect_uri=https://account.rewards.lolesports.com/v1/session/oauth-callback"
                       "&response_type=code&scope=openid&prompt=none"
                       "&state=https://lolesports.com",
                       wait_until="commit", timeout=15000)
            sleep(2)
        except Exception as e:
            # This can fail with a non-200 status but still set cookies — that's OK
            print(f"[{account_name}] Authorize redirect returned an error (this can be normal)")

        # Try to fetch the session token
        try:
            token_resp = page.request.get(
                "https://account.rewards.lolesports.com/v1/session/token",
                headers={"Origin": "https://lolesports.com", "Referer": "https://lolesports.com"})
            if token_resp.status == 200:
                print(f"[{account_name}] Session token obtained!")
            else:
                print(f"[{account_name}] Session token request returned {token_resp.status}")
        except Exception:
            print(f"[{account_name}] Could not fetch session token (may still work via cookies)")

        # Extract all relevant cookies
        cookies = extract_cookies_for_domain(context, [
            "riotgames.com", "lolesports.com", "leagueoflegends.com"
        ])

        if not cookies:
            print(f"[{account_name}] ERROR: No cookies captured. Login may have failed.")
            browser.close()
            return False

        # Save cookies
        cookie_path = sessions_dir / f"{account_name}.saved"
        with open(cookie_path, "wb") as f:
            pickle.dump(cookies, f)

        print(f"[{account_name}] Saved {len(cookies)} cookies to {cookie_path}")

        # Check for access_token specifically
        if "access_token" in cookies:
            print(f"[{account_name}] access_token present — session is valid!")
        else:
            print(f"[{account_name}] WARNING: No access_token in cookies.")
            print(f"  Captured cookies: {', '.join(sorted(cookies.keys()))}")

        browser.close()
        return "access_token" in cookies


def main():
    parser = argparse.ArgumentParser(
        description="Browser login for CapsuleFarmerEvolved — run locally, copy cookies to server")
    parser.add_argument("-c", "--config", dest="configPath", default="./config.yaml",
                        help="Path to config file")
    args = parser.parse_args()

    config = Config(args.configPath)

    print("=" * 60)
    print("CapsuleFarmerEvolved — Browser Login")
    print("=" * 60)
    print("A browser window will open for each account.")
    print("Log in, solve any captcha, complete any Riot prompts,")
    print("and wait for the redirect back to lolesports.com.")
    print("=" * 60)

    success = []
    failed = []

    for account in config.accounts:
        acct = config.getAccount(account)
        ok = login_account(account, acct["username"], acct["password"])
        if ok:
            success.append(account)
        else:
            failed.append(account)

    print("\n" + "=" * 60)
    print("Results:")
    for a in success:
        print(f"  {a}: OK — cookies saved")
    for a in failed:
        print(f"  {a}: FAILED — no access_token obtained")

    if success:
        print(f"\nCookie files saved in ./sessions/")
        print("To use on a headless server:")
        print("  1. Copy the ./sessions/*.saved files to the server")
        print("  2. Place them in the same ./sessions/ directory next to main.py")
        print("  3. Run the bot — it will load cookies and skip browser login")


if __name__ == "__main__":
    main()
