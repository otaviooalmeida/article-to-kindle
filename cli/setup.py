"""Interactive local configuration; secrets stay outside the Chrome extension."""

import getpass
import os
import re
import secrets
import tempfile
from pathlib import Path

from backend.config import ALLOWED_ORIGIN, API_TOKEN, KINDLE_EMAIL, SMTP_FROM, SMTP_HOST, SMTP_PASSWORD, SMTP_PORT, SMTP_USERNAME, read_dotenv, valid_api_token
from backend.delivery import is_valid_email_address
from backend.errors import ArticleError


def save_config(path: Path, values: dict[str, str], *, force: bool) -> None:
    if path.is_symlink():
        raise ArticleError("Refusing to write configuration through a symbolic link.")
    if path.exists() and not force:
        raise ArticleError(f"Configuration already exists: {path}. Use --force explicitly to update it.")
    if any("\n" in value or "\r" in value for value in values.values()):
        raise ArticleError("Configuration values must be single-line.")
    # Preserve comments, unknown settings, and their formatting when updating.
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    remaining = dict(values)
    updated = []
    for line in lines:
        name = line.split("=", 1)[0].strip()
        if "=" in line and name in values:
            updated.append(f'{name}="{values[name]}"')
            remaining.pop(name, None)
        else:
            updated.append(line)
    updated.extend(f'{name}="{value}"' for name, value in remaining.items())
    content = "\n".join(updated) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as handle:
            temporary = Path(handle.name)  # tempfile creates it with mode 0600.
            handle.write(content)
        if force:
            temporary.replace(path)
        else:
            os.link(temporary, path)  # Atomic no-clobber publication.
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def setup(path: Path, *, force=False) -> None:
    if path.is_symlink():
        raise ArticleError("Refusing to write configuration through a symbolic link.")
    if path.exists() and not force:
        raise ArticleError(f"Configuration already exists: {path}. Use --force explicitly to update it.")
    existing = read_dotenv(path) if path.exists() else {}
    values = {}

    def prompt(label, key, default=""):
        fallback = existing.get(key, default)
        answer = input(f"{label}{f' [{fallback}]' if fallback else ''}: ").strip()
        return answer or fallback

    print("Copy the chrome-extension://… origin shown in the extension's Settings page.")
    origin = prompt("Extension origin", ALLOWED_ORIGIN)
    if not re.fullmatch(r"chrome-extension://[a-p]{32}", origin):
        raise ArticleError("Enter the exact chrome-extension:// origin with its 32-character ID and no trailing slash.")
    values[ALLOWED_ORIGIN] = origin
    token = existing.get(API_TOKEN, "")
    values[API_TOKEN] = token if valid_api_token(token) else secrets.token_urlsafe(32)
    if input("Configure SMTP for Kindle Submission now? [y/N]: ").strip().lower() in {"y", "yes"}:
        values[SMTP_HOST] = prompt("SMTP hostname", SMTP_HOST)
        values[SMTP_PORT] = prompt("SMTP port", SMTP_PORT, "587")
        values[SMTP_USERNAME] = prompt("SMTP username", SMTP_USERNAME)
        values[SMTP_PASSWORD] = getpass.getpass("SMTP password (hidden; blank keeps existing): ") or existing.get(SMTP_PASSWORD, "")
        values[SMTP_FROM] = prompt("Sender email to approve in Amazon", SMTP_FROM)
        values[KINDLE_EMAIL] = prompt("Default Kindle email (optional)", KINDLE_EMAIL)
        if not values[SMTP_HOST] or any(char.isspace() for char in values[SMTP_HOST]) or "://" in values[SMTP_HOST]:
            raise ArticleError("SMTP hostname must not be a URL or contain whitespace.")
        if not values[SMTP_PORT].isdigit() or not 1 <= int(values[SMTP_PORT]) <= 65535:
            raise ArticleError("SMTP port must be between 1 and 65535.")
        if not values[SMTP_USERNAME] or not values[SMTP_PASSWORD]:
            raise ArticleError("SMTP username and password are required.")
        if not is_valid_email_address(values[SMTP_FROM]):
            raise ArticleError("Enter a valid sender email address.")
        if values[KINDLE_EMAIL] and not is_valid_email_address(values[KINDLE_EMAIL]):
            raise ArticleError("Enter a valid Kindle email address or leave the default blank.")
    save_config(path, values, force=force)
    print(f"Configuration saved: {path}\nCopy ARTICLE_TO_KINDLE_TOKEN from this file into the extension's bearer-token field.")
    print("Local server URL: http://127.0.0.1:8765. Shell variables override this file.")
    if SMTP_FROM in values:
        print(f"Approve {values[SMTP_FROM]} in Amazon Personal Document Settings: https://www.amazon.com/hz/mycd/myx#/home/settings")
    import shlex
    print(f"Start the companion with {shlex.join(['article-to-kindle', 'serve', '--config', str(path)])}")
