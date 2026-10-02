"""SMTP delivery adapter."""

from __future__ import annotations

import smtplib
import ssl
from contextlib import contextmanager
from email.errors import HeaderParseError
from email.headerregistry import Address
from email.message import EmailMessage
from pathlib import Path

from .config import KINDLE_EMAIL, MAX_EPUB_BYTES, SMTP_FROM, SMTP_HOST, SMTP_PASSWORD, SMTP_PORT, SMTP_USERNAME, smtp_settings
from .errors import ArticleError


def is_valid_email_address(value: str) -> bool:
    if not isinstance(value, str) or len(value) > 254:
        return False
    try:
        address = Address(addr_spec=value)
    except (HeaderParseError, ValueError):
        return False
    return address.addr_spec == value and "." in address.domain


def submission_settings(recipient: str | None = None) -> tuple[dict[str, str], int, str]:
    """Validate submission configuration without opening a network connection."""
    try:
        settings = smtp_settings()
        port = int(settings[SMTP_PORT])
    except (ValueError, TypeError) as error:
        raise ArticleError(str(error)) from error
    if not 1 <= port <= 65535:
        raise ArticleError("SMTP_PORT must be between 1 and 65535.")
    host = settings[SMTP_HOST]
    if not host or any(character.isspace() for character in host) or "://" in host:
        raise ArticleError("SMTP_HOST must be a hostname, not a URL.")
    if not is_valid_email_address(settings[SMTP_FROM]):
        raise ArticleError("SMTP_FROM must be a valid sender email address.")
    recipient = (settings[KINDLE_EMAIL] if recipient is None else recipient).strip()
    if not recipient:
        raise ArticleError(f"Set {KINDLE_EMAIL} or use --to with a Kindle email address.")
    if not is_valid_email_address(recipient):
        raise ArticleError("Kindle recipient email address is invalid.")
    return settings, port, recipient


def send_to_kindle(article, epub: Path, recipient: str | None = None) -> None:
    settings, port, recipient = submission_settings(recipient)
    if epub.stat().st_size > MAX_EPUB_BYTES:
        raise ArticleError("EPUB exceeds the 50 MiB Kindle submission limit.")
    message = EmailMessage()
    message["From"], message["To"], message["Subject"] = settings[SMTP_FROM], recipient, article.title
    message.set_content(f"{article.title}\n\nSource: {article.source_url}")
    message.add_attachment(epub.read_bytes(), maintype="application", subtype="epub+zip", filename=epub.name)
    with smtp_connection(settings, port) as client:
        client.send_message(message)


@contextmanager
def smtp_connection(settings: dict[str, str], port: int):
    """Connect and authenticate once, always closing even when login fails."""
    client = None
    try:
        context = ssl.create_default_context()
        if port == 465:
            client = smtplib.SMTP_SSL(settings[SMTP_HOST], port, context=context, timeout=30)
        else:
            client = smtplib.SMTP(settings[SMTP_HOST], port, timeout=30)
            client.starttls(context=context)
        client.login(settings[SMTP_USERNAME], settings[SMTP_PASSWORD])
        yield client
    except (OSError, smtplib.SMTPException) as error:
        code = getattr(error, "smtp_code", None)
        detail = f"SMTP status {code}" if code else type(error).__name__
        raise ArticleError(f"Kindle submission failed ({detail}); Amazon delivery is unconfirmed.") from error
    finally:
        if client is not None:
            try:
                client.close()
            except OSError:
                pass
