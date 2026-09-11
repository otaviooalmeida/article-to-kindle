"""SMTP delivery adapter."""

from __future__ import annotations

import smtplib
import ssl
from email.message import EmailMessage
from pathlib import Path

from .config import KINDLE_EMAIL, SMTP_FROM, SMTP_HOST, SMTP_PASSWORD, SMTP_PORT, SMTP_USERNAME, smtp_settings
from .errors import ArticleError


def send_to_kindle(article, epub: Path) -> None:
    try:
        settings = smtp_settings()
        port = int(settings[SMTP_PORT])
    except (ValueError, TypeError) as error:
        raise ArticleError(str(error)) from error
    message = EmailMessage()
    message["From"], message["To"], message["Subject"] = settings[SMTP_FROM], settings[KINDLE_EMAIL], article.title
    message.set_content(f"{article.title}\n\nSource: {article.source_url}")
    message.add_attachment(epub.read_bytes(), maintype="application", subtype="epub+zip", filename=epub.name)
    client = None
    try:
        context = ssl.create_default_context()
        if port == 465:
            client = smtplib.SMTP_SSL(settings[SMTP_HOST], port, context=context, timeout=30)
            client.login(settings[SMTP_USERNAME], settings[SMTP_PASSWORD])
        else:
            client = smtplib.SMTP(settings[SMTP_HOST], port, timeout=30)
            client.starttls(context=context)
            client.login(settings[SMTP_USERNAME], settings[SMTP_PASSWORD])
        client.send_message(message)
    except (OSError, smtplib.SMTPException) as error:
        raise ArticleError(f"EPUB was created but email delivery failed: {error}") from error
    finally:
        if client is not None:
            try:
                client.close()
            except OSError:
                pass
