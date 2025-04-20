import time
import logging
import argparse
from datetime import datetime, timezone
from pathlib import Path
import toml
import requests
from mastodon import Mastodon
from plurk_oauth import PlurkAPI

# --- Setup paths ---
CONFIG_DIR = Path.home() / ".masto2plurk"
CONFIG_FILE = CONFIG_DIR / "config.toml"
SECRETS_FILE = CONFIG_DIR / "secrets.toml"
CACHE_FILE = CONFIG_DIR / "cache.toml"
LOG_FILE = CONFIG_DIR / "bridge.log"

# --- Setup logging ---
CONFIG_DIR.mkdir(exist_ok=True)
logging.basicConfig(
    filename=LOG_FILE,
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)

# --- Load configs ---
config = toml.load(CONFIG_FILE)
secrets = toml.load(SECRETS_FILE)
cache = toml.load(CACHE_FILE) if CACHE_FILE.exists() else {}
if not "last_toot_time" in cache:
    cache["last_toot_time"] = datetime.now(timezone.utc).isoformat()

# --- Argument parsing ---
parser = argparse.ArgumentParser()
parser.add_argument("-p", type=int, default=config.get("poll_minutes", 5), help="Polling interval in minutes")
parser.add_argument("-0", dest="since", help="Start time in ISO format")
args = parser.parse_args()

# --- Setup Mastodon client ---
mastodon = Mastodon(
    access_token=secrets["mastodon"]["access_token"],
    api_base_url=config["mastodon"]["instance"]
)

# --- Setup Plurk client ---
plurk = PlurkAPI(
    secrets["plurk"]["app_key"],
    secrets["plurk"]["client_secret"]
)
plurk.authorize(
    secrets["plurk"]["resource_owner_key"],
    secrets["plurk"]["resource_owner_secret"]
)

# --- Format toot content to Plurk ---
def format_toot(toot):
    content = toot.get("content", {}).get("text", "")
    return content.replace("<br>", "\n").replace("<p>", "\n").replace("</p>", "").strip()

# --- Main polling loop ---
last_time = args.since or cache["last_toot_time"]
logging.info(f"Starting loop with since={last_time}")

while True:
    try:
        toots = mastodon.account_statuses(mastodon.me()["id"], since_id=None, min_id=None)
        toots = [t for t in toots if t["created_at"].isoformat() > last_time and not t["reblog"]]
        toots.sort(key=lambda x: x["created_at"])  # Oldest to newest

        for toot in toots:
            text = format_toot(toot)
            if len(text.strip()) < config.get("filter", {}).get("min_length", 0):
                continue
            
            plurk.add_plurk(
                qualifier=config["plurk"].get("qualifier", ":"),
                content=text,
                lang=config["plurk"].get("lang", "en")
            )

            last_time = toot["created_at"].isoformat()
            logging.info(f"Posted toot {toot['id']} to Plurk")

        # Save cache
        CACHE_FILE.write_text(toml.dumps({"last_toot_time": last_time}))

    except Exception as e:
        logging.error(f"Error: {e}")

    time.sleep(args.p * 60)
