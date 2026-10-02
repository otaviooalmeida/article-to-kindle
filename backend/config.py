"""Configuration paths, .env loading, and limits shared by both entry points."""

import os
import re
import sys
from pathlib import Path

from .errors import ArticleError

KINDLE_EMAIL = "KINDLE_EMAIL"
API_TOKEN = "ARTICLE_TO_KINDLE_TOKEN"
ALLOWED_ORIGIN = "ARTICLE_TO_KINDLE_ALLOWED_ORIGIN"
CONFIG_FILE = "ARTICLE_TO_KINDLE_CONFIG"
SMTP_HOST = "SMTP_HOST"
SMTP_PORT = "SMTP_PORT"
SMTP_USERNAME = "SMTP_USERNAME"
SMTP_PASSWORD = "SMTP_PASSWORD"
SMTP_FROM = "SMTP_FROM"
SMTP_DEFAULT_PORT = 587
MAX_CAPTURE_BYTES = 10 * 1024 * 1024
MAX_EPUB_BYTES = 50 * 1024 * 1024
SMTP_REQUIRED = (SMTP_HOST, SMTP_USERNAME, SMTP_PASSWORD, SMTP_FROM)


def default_config_path() -> Path:
    if os.environ.get(CONFIG_FILE):
        return Path(os.environ[CONFIG_FILE]).expanduser()
    project = Path(__file__).resolve().parent.parent
    if (project / "article_to_kindle.py").is_file() and (project / "cli").is_dir():
        return project / ".env"
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", str(Path.home() / "AppData" / "Roaming")))
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config")))
    return base / "article-to-kindle" / ".env"


def read_dotenv(path: Path) -> dict[str, str]:
    values = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        name, value = name.strip(), value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        if name and name.isidentifier():
            values[name] = value
    return values


def load_dotenv(path: Path | None = None) -> None:
    """Load simple KEY=VALUE entries without overriding shell variables."""
    path = default_config_path() if path is None else path
    if path.is_file():
        for name, value in read_dotenv(path).items():
            os.environ.setdefault(name, value)


def companion_settings() -> tuple[str, str]:
    token, origin = os.environ.get(API_TOKEN, ""), os.environ.get(ALLOWED_ORIGIN, "")
    if len(token) < 32 or any(character.isspace() for character in token):
        raise ArticleError(f"{API_TOKEN} must contain at least 32 non-whitespace characters. Run setup to generate one.")
    if not re.fullmatch(r"chrome-extension://[a-p]{32}", origin):
        raise ArticleError(f"{ALLOWED_ORIGIN} must be chrome-extension:// followed by the 32-character extension ID (no trailing slash).")
    return token, origin


def smtp_settings() -> dict[str, str]:
    values = {name: os.environ.get(name, "") for name in SMTP_REQUIRED}
    missing = [name for name, value in values.items() if not value]
    if missing:
        raise ValueError(f"Missing SMTP settings: {', '.join(missing)}")
    values[KINDLE_EMAIL] = os.environ.get(KINDLE_EMAIL, "")
    values[SMTP_PORT] = os.environ.get(SMTP_PORT, str(SMTP_DEFAULT_PORT))
    return values
