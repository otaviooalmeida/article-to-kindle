"""CLI contract tests: no real article fetches or SMTP submissions."""

import io
import os
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from backend.errors import ArticleError
from backend.models import Article
from cli.main import main


class CliTest(unittest.TestCase):
    def setUp(self):
        environment = patch.dict(os.environ, {
            "SMTP_HOST": "smtp.example.com", "SMTP_PORT": "587",
            "SMTP_USERNAME": "sender@example.com", "SMTP_PASSWORD": "secret",
            "SMTP_FROM": "sender@example.com", "KINDLE_EMAIL": "reader@kindle.com",
        })
        environment.start()
        self.addCleanup(environment.stop)

    def invoke(self, *args):
        stdout, stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = main(list(args))
        return code, stdout.getvalue(), stderr.getvalue()

    def article(self):
        return Article("Title", "Ada", "https://openai.com/article", "<p>content</p>", [], [],
                       ["1 formula(s) retained as text", "1 image(s) omitted"])

    def test_conversion_summary_and_warnings(self):
        with tempfile.TemporaryDirectory() as directory, \
                patch("cli.main.fetch_html", return_value=("html", "https://openai.com/article")), \
                patch("cli.main.extract_article", return_value=self.article()):
            output = Path(directory) / "article.epub"
            code, stdout, stderr = self.invoke("https://openai.com/article", "--output", str(output))
            self.assertTrue(output.is_file())
        self.assertEqual(0, code)
        self.assertIn("Title: Title", stdout)
        self.assertIn("Author: Ada", stdout)
        self.assertIn("Images: 0", stdout)
        self.assertIn("warning: 1 image(s) omitted", stderr)
        self.assertIn("Fetching article", stderr)

    def test_expected_error_is_concise_and_debug_shows_traceback(self):
        with patch("cli.main.fetch_html", side_effect=OSError("network unavailable")):
            code, _, stderr = self.invoke("https://openai.com/article")
            self.assertEqual(1, code)
            self.assertIn("error: network unavailable", stderr)
            self.assertNotIn("Traceback", stderr)
            _, _, stderr = self.invoke("https://openai.com/article", "--debug")
            self.assertIn("Traceback", stderr)

    def test_submission_failure_preserves_output(self):
        with tempfile.TemporaryDirectory() as directory, \
                patch("cli.main.fetch_html", return_value=("html", "https://openai.com/article")), \
                patch("cli.main.extract_article", return_value=self.article()), \
                patch("cli.main.send_to_kindle", side_effect=ArticleError("SMTP unavailable")):
            output = Path(directory) / "article.epub"
            code, _, stderr = self.invoke("https://openai.com/article", "--output", str(output), "--send")
            self.assertTrue(output.is_file())
        self.assertEqual(1, code)
        self.assertIn(f"EPUB retained at {output}", stderr)

    def test_submission_reports_acceptance_not_delivery(self):
        with tempfile.TemporaryDirectory() as directory, \
                patch("cli.main.fetch_html", return_value=("html", "https://openai.com/article")), \
                patch("cli.main.extract_article", return_value=self.article()), \
                patch("cli.main.send_to_kindle") as send, \
                patch.dict(os.environ, {"KINDLE_EMAIL": "reader@kindle.com"}):
            code, stdout, _ = self.invoke("https://openai.com/article", "--output",
                                          str(Path(directory) / "article.epub"), "--send")
        self.assertEqual(0, code)
        send.assert_called_once()
        self.assertIn("SMTP accepted", stdout)
        self.assertIn("Amazon delivery pending", stdout)

    def test_explicit_recipient_and_preflight(self):
        with tempfile.TemporaryDirectory() as directory, \
                patch("cli.main.fetch_html", return_value=("html", "https://openai.com/article")), \
                patch("cli.main.extract_article", return_value=self.article()), \
                patch("cli.main.send_to_kindle") as send:
            code, _, _ = self.invoke("https://openai.com/article", "--output",
                                      str(Path(directory) / "article.epub"), "--send", "--to", "other@kindle.com")
        self.assertEqual(0, code)
        self.assertEqual("other@kindle.com", send.call_args.args[2])
        with patch.dict(os.environ, {"SMTP_PORT": "invalid"}), patch("cli.main.fetch_html") as fetch:
            code, _, stderr = self.invoke("https://openai.com/article", "--send")
        self.assertEqual(1, code)
        fetch.assert_not_called()
        self.assertIn("error:", stderr)

    def test_subcommands_and_legacy_modes(self):
        with patch("cli.main.self_test") as check:
            self.assertEqual(0, self.invoke("self-test")[0])
            self.assertEqual(0, self.invoke("--self-test")[0])
            self.assertEqual(2, check.call_count)
        for args in (("--serve", "--self-test"), ("serve", "--send"),
                     ("--self-test", "https://openai.com/article"),
                     ("convert", "https://openai.com/article", "--to", "reader@kindle.com")):
            with self.subTest(args=args):
                self.assertEqual(2, self.invoke(*args)[0])

    def test_send_existing_epub_never_fetches(self):
        from backend.epub import write_epub
        with tempfile.TemporaryDirectory() as directory, patch("cli.main.fetch_html") as fetch, \
                patch("cli.main.send_to_kindle") as send:
            output = Path(directory) / "existing.epub"
            write_epub(self.article(), output)
            original = output.read_bytes()
            code, stdout, _ = self.invoke("send", str(output), "--to", "other@kindle.com")
            self.assertEqual(original, output.read_bytes())
        self.assertEqual(0, code)
        fetch.assert_not_called()
        self.assertEqual("Title", send.call_args.args[0].title)
        self.assertEqual("other@kindle.com", send.call_args.args[2])
        self.assertIn("SMTP accepted", stdout)

    def test_invalid_epub_is_not_submitted(self):
        with tempfile.TemporaryDirectory() as directory, patch("cli.main.send_to_kindle") as send:
            output = Path(directory) / "invalid.epub"
            output.write_bytes(b"not an EPUB")
            code, _, stderr = self.invoke("send", str(output))
        self.assertEqual(1, code)
        self.assertIn("EPUB", stderr)
        send.assert_not_called()

    def test_existing_output_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as directory, \
                patch("cli.main.fetch_html", return_value=("html", "https://openai.com/article")), \
                patch("cli.main.extract_article", return_value=self.article()):
            output = Path(directory) / "article.epub"
            output.write_bytes(b"keep me")
            code, _, stderr = self.invoke("https://openai.com/article", "--output", str(output))
            self.assertEqual(b"keep me", output.read_bytes())
        self.assertEqual(1, code)
        self.assertIn("already exists", stderr)


if __name__ == "__main__":
    unittest.main()
