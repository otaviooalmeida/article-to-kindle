import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from backend.errors import ArticleError
from backend.models import Article
from cli.main import main


class CliJsonTest(unittest.TestCase):
    def invoke(self, args):
        stdout, stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = main(args)
        self.assertEqual(1, len(stdout.getvalue().splitlines()), stdout.getvalue())
        result = json.loads(stdout.getvalue())
        self.assertEqual(code, result["exitCode"])
        return code, result, stderr.getvalue()

    def test_json_conversion_is_one_object_with_warnings(self):
        article = Article("Título", "Ada", "https://openai.com/article", "<p>content</p>", [], [], ["1 image(s) omitted"])
        with tempfile.TemporaryDirectory() as directory, \
                patch("cli.main.fetch_html", return_value=("html", article.source_url)), \
                patch("cli.main.extract_article", return_value=article):
            output = Path(directory) / "article.epub"
            code, result, stderr = self.invoke(["--json", "convert", article.source_url, "-o", str(output)])
        self.assertEqual(0, code)
        self.assertEqual("Título", result["title"])
        self.assertEqual("not_requested", result["submission"])
        self.assertEqual(["1 image(s) omitted"], result["warnings"])
        self.assertIn("warning:", stderr)
        self.assertEqual("ok", result["status"])
        self.assertEqual(1, result["schemaVersion"])

    def test_usage_and_operational_errors_are_structured(self):
        code, result, _ = self.invoke(["convert", "--json"])
        self.assertEqual(2, code)
        self.assertEqual("invalid_arguments", result["error"]["code"])
        with patch("cli.main.fetch_html", side_effect=OSError("network unavailable")):
            code, result, _ = self.invoke(["https://openai.com/article", "--json"])
        self.assertEqual(1, code)
        self.assertIn("network unavailable", result["error"]["message"])

    def test_submission_failure_retains_path_in_json(self):
        article = Article("Title", "Ada", "https://openai.com/article", "<p>content</p>", [], [])
        with tempfile.TemporaryDirectory() as directory, \
                patch("cli.main.fetch_html", return_value=("html", article.source_url)), \
                patch("cli.main.extract_article", return_value=article), \
                patch("cli.main.submission_settings", return_value=({}, 587, "reader@kindle.com")), \
                patch("cli.main.send_to_kindle", side_effect=ArticleError("SMTP unavailable")):
            output = Path(directory) / "article.epub"
            code, result, _ = self.invoke(["convert", article.source_url, "--send", "-o", str(output), "--json"])
            self.assertTrue(output.exists())
        self.assertEqual(1, code)
        self.assertEqual(str(output), result["output"])
        self.assertEqual("unconfirmed", result["submission"])

    def test_doctor_and_self_test_json(self):
        for args in (["doctor", "--json"], ["self-test", "--json"]):
            code, result, _ = self.invoke(args)
            self.assertEqual(0, code)
            self.assertEqual(args[0], result["command"])
        code, result, _ = self.invoke(["doctor", "--json", "--companion", "--config", "/absent/config.env"])
        self.assertEqual(1, code)
        self.assertEqual("error", result["status"])

    def test_json_rejected_for_interactive_or_streaming_commands(self):
        for args in (["setup", "--json"], ["serve", "--json"]):
            code, result, _ = self.invoke(args)
            self.assertEqual(2, code)
            self.assertEqual("invalid_arguments", result["error"]["code"])

    def test_interruption_is_structured(self):
        with patch("cli.main.fetch_html", side_effect=KeyboardInterrupt):
            code, result, _ = self.invoke(["convert", "https://openai.com/article", "--json"])
        self.assertEqual(130, code)
        self.assertEqual("interrupted", result["error"]["code"])


if __name__ == "__main__":
    unittest.main()
