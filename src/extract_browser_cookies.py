"""
Extract lolesports session cookies from LibreWolf (or Firefox) browser.

Reads the cookies.sqlite database, filters for Riot/lolesports domains,
and saves them in the format the bot expects.

Usage:
    pipenv run python src/extract_browser_cookies.py -c config/config.yaml

Make sure LibreWolf is CLOSED before running (it locks the DB).
"""

import argparse
import pickle
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from Config import Config

# LibreWolf/Firefox cookies.sqlite location
LIBREWOLF_COOKIES = Path.home() / "AppData/Roaming/librewolf/Profiles/cn95bjk4.default-default/cookies.sqlite"


def extract_cookies(db_path, domains):
    """
    Read cookies from a Firefox/LibreWolf cookies.sqlite file.

    :param db_path: Path to cookies.sqlite
    :param domains: list of domain substrings to filter
    :return: dict of cookie name -> value
    """
    # Copy the DB to avoid lock issues if browser is running
    tmp = tempfile.mktemp(suffix=".sqlite")
    shutil.copy2(db_path, tmp)

    conn = sqlite3.connect(tmp)
    cursor = conn.cursor()

    cookies = {}
    for domain in domains:
        cursor.execute(
            "SELECT name, value FROM moz_cookies WHERE host LIKE ?",
            (f"%{domain}%",)
        )
        for name, value in cursor.fetchall():
            cookies[name] = value

    conn.close()
    Path(tmp).unlink(missing_ok=True)
    return cookies


def main():
    parser = argparse.ArgumentParser(description="Extract lolesports cookies from LibreWolf")
    parser.add_argument("-c", "--config", dest="configPath", default="./config.yaml")
    parser.add_argument("--db", dest="dbPath", default=str(LIBREWOLF_COOKIES),
                        help="Path to cookies.sqlite")
    args = parser.parse_args()

    db_path = Path(args.dbPath)
    if not db_path.exists():
        print(f"ERROR: Cookie database not found at {db_path}")
        print("Make sure LibreWolf is installed and you've logged into lolesports.com")
        sys.exit(1)

    config = Config(args.configPath)
    # Save to both ./sessions/ and ./src/sessions/ (bot runs from src/)
    sessions_dirs = [Path("./sessions"), Path("./src/sessions")]
    for d in sessions_dirs:
        d.mkdir(parents=True, exist_ok=True)

    # Domains we need cookies from
    domains = ["riotgames.com", "lolesports.com", "leagueoflegends.com"]

    print(f"Reading cookies from: {db_path}")
    cookies = extract_cookies(db_path, domains)

    if not cookies:
        print("ERROR: No relevant cookies found. Make sure you're logged into lolesports.com in LibreWolf.")
        sys.exit(1)

    print(f"Found {len(cookies)} cookies from Riot/LoL domains:")
    for name in sorted(cookies.keys()):
        val_preview = cookies[name][:30] + "..." if len(cookies[name]) > 30 else cookies[name]
        print(f"  {name} = {val_preview}")

    has_access_token = "access_token" in cookies or "__Secure-access_token" in cookies
    if has_access_token:
        print("\naccess_token found — session is valid!")
    else:
        print("\nWARNING: No access_token cookie found.")
        print("Make sure you're logged into https://lolesports.com in LibreWolf")
        print("and have visited the site recently.")

    # Save for each configured account in all session directories
    for account in config.accounts:
        for sessions_dir in sessions_dirs:
            cookie_path = sessions_dir / f"{account}.saved"
            with open(cookie_path, "wb") as f:
                pickle.dump(cookies, f)
            print(f"Saved cookies for '{account}' -> {cookie_path}")

    if has_access_token:
        print("\nDone! You can now run the bot:")
        print("  pipenv run python src/main.py -c config/config.yaml")
        print("\nOr copy ./sessions/*.saved to your headless server.")
    else:
        print("\nCookies saved but missing access_token. The bot may fail.")
        print("Try logging into lolesports.com in LibreWolf first, then re-run this.")


if __name__ == "__main__":
    main()
