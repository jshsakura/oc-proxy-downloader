
import os
import sys
from pathlib import Path
import json
import secrets

# Environment-specific config directory setup
# 1. OC_CONFIG_DIR environment variable (set when running standalone)
# 2. CONFIG_PATH environment variable (set in Docker environment)
# 3. Default: backend/config (local development)
if os.environ.get("OC_CONFIG_DIR"):
    CONFIG_DIR = Path(os.environ["OC_CONFIG_DIR"])
    IS_STANDALONE = True
    print(f"[DEBUG] Standalone CONFIG_DIR: {CONFIG_DIR}")
elif os.environ.get("CONFIG_PATH"):
    CONFIG_DIR = Path(os.environ["CONFIG_PATH"])
    IS_STANDALONE = False
    print(f"[DEBUG] Docker CONFIG_DIR: {CONFIG_DIR}")
else:
    CONFIG_DIR = Path(__file__).parent.parent / "config"
    IS_STANDALONE = False
    print(f"[DEBUG] Local CONFIG_DIR: {CONFIG_DIR}")

# Ensure CONFIG_DIR is created
CONFIG_DIR.mkdir(parents=True, exist_ok=True)
CONFIG_FILE = CONFIG_DIR / "config.json"
print(f"[DEBUG] CONFIG_FILE path: {CONFIG_FILE}")

def get_default_download_path():
    """Return default download path by environment"""
    if IS_STANDALONE:
        # Standalone: User downloads folder
        # Use standard downloads folder path
        try:
            if sys.platform.startswith('win'):
                # Windows user downloads folder
                home_downloads = str(Path.home() / "Downloads")
                print(f"[DEBUG] Windows download path: {home_downloads}")

                # Create folder if it doesn't exist
                downloads_path = Path(home_downloads)
                downloads_path.mkdir(exist_ok=True)

                return home_downloads
            else:
                # Linux/Mac downloads folder
                home_downloads = str(Path.home() / "Downloads")
                print(f"[DEBUG] Linux/Mac download path: {home_downloads}")

                # Create folder if it doesn't exist
                downloads_path = Path(home_downloads)
                downloads_path.mkdir(exist_ok=True)

                return home_downloads
        except Exception as e:
            # Final fallback: downloads folder in current directory
            fallback_path = str(Path.cwd() / "downloads")
            print(f"[ERROR] Download path setup failed, using fallback: {fallback_path}, error: {e}")
            Path(fallback_path).mkdir(exist_ok=True)
            return fallback_path
    elif os.environ.get("CONFIG_PATH"):
        # Docker environment: /downloads
        return "/downloads"
    else:
        # Local development: downloads folder in project
        project_root = Path(__file__).parent.parent.parent
        return str(project_root / "downloads")

DEFAULT_CONFIG = {
    "download_path": get_default_download_path(),
    "theme": "light",
    "language": "ko",
    # FlareSolverr endpoint for Cloudflare-protected hosts (MegaUp/GoFile/etc.).
    # Empty → fall back to the FLARESOLVERR_URL env var, then http://localhost:8191.
    "flaresolverr_url": "",
    # Smart-download concurrency. The global ceiling bounds total simultaneous
    # downloads; the per-host cap keeps a few big files on one host from starving
    # small files on another host (each host gets its own queue). See download_core.
    "max_concurrent_downloads": 8,
    "max_per_host_downloads": 3,
    # Below this size (MB), the Telegram start notification is suppressed so a
    # small file sends only one (completion) message instead of a near-
    # simultaneous start+complete pair. 0 disables the suppression.
    "telegram_small_file_threshold_mb": 100,
    # Max hoster pages parsed at once (cloudscraper/FlareSolverr are CPU-heavy).
    # Bulk-adding many links queues their parses instead of thrashing the CPU and
    # stalling the API. Applied as the asyncio default thread-pool size at startup.
    "parse_concurrency": 3,
    # Which egress a download leaves through. Host limits (1fichier's max-1, the
    # per-site caps) are enforced per IP by the hoster, so a second egress is a
    # second set of slots rather than a share of the same one.
    #   "direct"  - always the host's own connection (previous behaviour)
    #   "vpn"     - always through the configured single proxy
    #   "auto"    - start direct; on a non-definitive failure retry via the proxy
    #   "balance" - take whichever egress has a free slot, preferring direct
    # "vpn"/"auto"/"balance" need at least one active proxy or they fall back to
    # direct, so turning this on without a proxy configured changes nothing.
    "download_route": "direct"
}

# Credentials that must never leave the server in readable form. They grant
# control of a Telegram bot and a 1fichier account, so the settings API returns a
# placeholder and the stored value is kept when that placeholder comes back.
SECRET_CONFIG_KEYS = frozenset({
    "telegram_bot_token",
    "fichier_password",
    # The API token is revealed only through its own dedicated endpoint, never in
    # the general settings payload.
    "api_token",
})
SECRET_PLACEHOLDER = "********"


def mask_secrets(config: dict) -> dict:
    """A copy of ``config`` with stored credentials replaced by the placeholder."""
    return {
        key: SECRET_PLACEHOLDER if key in SECRET_CONFIG_KEYS and value else value
        for key, value in config.items()
    }


def restore_masked_secrets(incoming: dict, stored: dict) -> dict:
    """Put back any credential the client echoed as the placeholder.

    The settings form round-trips whatever it was shown, so without this a save
    from an unchanged form would overwrite the real credential with asterisks.
    """
    return {
        key: stored.get(key, "") if key in SECRET_CONFIG_KEYS and value == SECRET_PLACEHOLDER else value
        for key, value in incoming.items()
    }


def get_config():
    # Create CONFIG_DIR
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                stored = json.load(f)
            # Defaults first, stored on top: a config.json written by an older
            # version is missing keys added since, and reading those as None makes
            # new settings look unset in the UI and unusable in code.
            return {**DEFAULT_CONFIG, **stored}
        except json.JSONDecodeError:
            print(f"[ERROR] config.json is corrupted or empty. Using default config.")
            # If the file is corrupted or empty, overwrite it with the defaults
            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(DEFAULT_CONFIG, f, indent=4, ensure_ascii=False)
            return DEFAULT_CONFIG.copy()
    # If the file is missing, create it with the defaults
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(DEFAULT_CONFIG, f, indent=4, ensure_ascii=False)
    return DEFAULT_CONFIG.copy()

def save_config(config, *, merge: bool = True):
    """Persist settings, merging into what is already stored by default.

    A partial payload used to replace the whole file: POSTing one key wiped the
    Telegram token, the 1fichier credentials and the paths along with it. The web
    form always sends every field so it never showed there, but any other caller
    (the API token exists precisely so there are others) could destroy the config
    with a single well-formed request. Merging makes a partial write mean
    "change these keys", which is what every caller already assumed.

    Pass merge=False to replace wholesale — only for callers that genuinely hold
    the complete config.
    """
    try:
        payload = config
        if merge:
            try:
                with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                    payload = {**json.load(f), **config}
            except (FileNotFoundError, json.JSONDecodeError):
                payload = config
        with open(CONFIG_FILE, 'w', encoding="utf-8") as f:
            json.dump(payload, f, indent=4, ensure_ascii=False)
    except PermissionError:
        print(f"[WARN] Cannot write to config file: {CONFIG_FILE}")
        print("[WARN] Config changes will not be persisted")

API_TOKEN_KEY = "api_token"
_API_TOKEN_BYTES = 32  # 256-bit, urlsafe → ~43 chars


def _generate_api_token() -> str:
    return secrets.token_urlsafe(_API_TOKEN_BYTES)


def get_or_create_api_token() -> str:
    """The stored server-to-server API token, generated and persisted on first use.

    Lives in config.json (not an env var), so it can be shown and rotated from the
    app itself. Returns the same value until regenerated.
    """
    config = get_config()
    token = (config.get(API_TOKEN_KEY) or "").strip()
    if not token:
        token = _generate_api_token()
        config[API_TOKEN_KEY] = token
        save_config(config)
    return token


def regenerate_api_token() -> str:
    """Mint a fresh token and persist it, revoking the previous one."""
    config = get_config()
    token = _generate_api_token()
    config[API_TOKEN_KEY] = token
    save_config(config)
    return token


def get_download_path():
    env_path = os.environ.get("DOWNLOAD_PATH")
    if env_path:
        path = Path(env_path)
    else:
        config = get_config()
        raw_path = config.get("download_path", "./downloads")
        path = Path(raw_path)
        if not path.is_absolute():
            path = Path(__file__).parent.parent / path
    path.mkdir(parents=True, exist_ok=True)
    return path
