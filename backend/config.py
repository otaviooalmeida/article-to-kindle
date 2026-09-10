"""Names, defaults, and local .env loading for configuration."""

import os
from pathlib import Path


def load_dotenv(path: Path | None = None) -> None:
    """Load simple KEY=VALUE entries without overriding shell variables."""
    path = path or Path(__file__).resolve().parent.parent / ".env"
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        name, value = name.strip(), value.strip()
        if name and name.isidentifier() and name not in os.environ:
            os.environ[name] = value.strip("\"'")


load_dotenv()


KINDLE_EMAIL = "KINDLE_EMAIL"
API_TOKEN = "ARTICLE_TO_KINDLE_TOKEN"
ALLOWED_ORIGIN = "ARTICLE_TO_KINDLE_ALLOWED_ORIGIN"
SMTP_HOST = "SMTP_HOST"
SMTP_PORT = "SMTP_PORT"
SMTP_USERNAME = "SMTP_USERNAME"
SMTP_PASSWORD = "SMTP_PASSWORD"
SMTP_FROM = "SMTP_FROM"
SMTP_DEFAULT_PORT = 587
MAX_CAPTURE_BYTES = 10 * 1024 * 1024
MAX_EPUB_BYTES = 50 * 1024 * 1024
SMTP_REQUIRED = (KINDLE_EMAIL, SMTP_HOST, SMTP_USERNAME, SMTP_PASSWORD, SMTP_FROM)


def smtp_settings() -> dict[str, str]:
    values = {name: os.environ.get(name, "") for name in SMTP_REQUIRED}
    missing = [name for name, value in values.items() if not value]
    if missing:
        raise ValueError(f"Missing environment variables for --send: {', '.join(missing)}")
    values[SMTP_PORT] = os.environ.get(SMTP_PORT, str(SMTP_DEFAULT_PORT))
    return values
