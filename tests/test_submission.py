import io
import os
import smtplib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.config import MAX_EPUB_BYTES
from backend.delivery import send_to_kindle, submission_settings
from backend.errors import ArticleError
from backend.models import Article


class SubmissionTest(unittest.TestCase):
    def setUp(self):
        environment = patch.dict(os.environ, {
            "SMTP_HOST": "smtp.example.com", "SMTP_PORT": "587",
            "SMTP_USERNAME": "sender@example.com", "SMTP_PASSWORD": "secret",
            "SMTP_FROM": "sender@example.com", "KINDLE_EMAIL": "reader@kindle.com",
        }, clear=True)
        environment.start()
        self.addCleanup(environment.stop)

    def test_invalid_configuration(self):
        for name, value in (("SMTP_HOST", "https://smtp.example.com"), ("SMTP_HOST", "bad\nhost"),
                            ("SMTP_FROM", "invalid"), ("SMTP_PORT", "0"), ("SMTP_PORT", "65536"),
                            ("SMTP_PASSWORD", ""), ("KINDLE_EMAIL", "invalid")):
            with self.subTest(name=name, value=value), patch.dict(os.environ, {name: value}):
                with self.assertRaises(ArticleError):
                    submission_settings()

    def test_explicit_recipient_overrides_default(self):
        self.assertEqual("other@kindle.com", submission_settings(" other@kindle.com ")[2])
        with self.assertRaises(ArticleError):
            submission_settings("")

    def test_large_epub_rejected_before_smtp_or_reading_attachment(self):
        with tempfile.TemporaryDirectory() as directory:
            epub = Path(directory) / "large.epub"
            with epub.open("wb") as handle:
                handle.truncate(MAX_EPUB_BYTES + 1)
            with patch("backend.delivery.smtplib.SMTP") as smtp, patch.object(Path, "read_bytes") as read:
                with self.assertRaisesRegex(ArticleError, "50 MiB"):
                    send_to_kindle(Article("Title", "Ada", "", "", [], []), epub)
            smtp.assert_not_called()
            read.assert_not_called()

    def test_smtp_error_does_not_disclose_response_or_retry(self):
        with tempfile.TemporaryDirectory() as directory:
            epub = Path(directory) / "article.epub"
            epub.write_bytes(b"epub")
            with patch("backend.delivery.smtplib.SMTP", side_effect=smtplib.SMTPAuthenticationError(535, b"secret")) as smtp:
                with self.assertRaisesRegex(ArticleError, "SMTP status 535") as raised:
                    send_to_kindle(Article("Title", "Ada", "", "", [], []), epub)
            self.assertNotIn("secret", str(raised.exception))
            smtp.assert_called_once()


if __name__ == "__main__":
    unittest.main()
