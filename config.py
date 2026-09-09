"""Names and defaults for process environment configuration."""

import os


KINDLE_EMAIL = "KINDLE_EMAIL"
SMTP_HOST = "SMTP_HOST"
SMTP_PORT = "SMTP_PORT"
SMTP_USERNAME = "SMTP_USERNAME"
SMTP_PASSWORD = "SMTP_PASSWORD"
SMTP_FROM = "SMTP_FROM"
SMTP_DEFAULT_PORT = 587
SMTP_REQUIRED = (KINDLE_EMAIL, SMTP_HOST, SMTP_USERNAME, SMTP_PASSWORD, SMTP_FROM)


def smtp_settings() -> dict[str, str]:
    values = {name: os.environ.get(name, "") for name in SMTP_REQUIRED}
    missing = [name for name, value in values.items() if not value]
    if missing:
        raise ValueError(f"Missing environment variables for --send: {', '.join(missing)}")
    values[SMTP_PORT] = os.environ.get(SMTP_PORT, str(SMTP_DEFAULT_PORT))
    return values
