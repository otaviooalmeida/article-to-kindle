import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from backend.errors import ArticleError
from backend.models import Article
from cli.main import main
from cli.batch import read_urls


class CliBatchTest(unittest.TestCase):
    def invoke(self, args):
        stdout, stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = main(args)
        return code, json.loads(stdout.getvalue()), stderr.getvalue()

    def article(self, html, url):
        return Article("Title", "Ada", url, "<p>content</p>", [], [], ["1 formula(s) retained as text"])

    def test_partial_failure_continues_and_duplicate_urls_are_skipped(self):
        first, bad, last = (f"https://openai.com/{name}" for name in ("first", "bad", "last"))
        def fetch(url):
            if url == bad:
                raise ArticleError("Article unavailable")
            return "html", url
        with tempfile.TemporaryDirectory() as directory, \
                patch("sys.stdin", io.StringIO(f"# Reading list\n{first}\n{bad}\n{first}\n\n{last}\n")), \
                patch("cli.main.fetch_html", side_effect=fetch) as fetching, \
                patch("cli.main.extract_article", side_effect=self.article):
            output_dir = Path(directory) / "reading-copies"
            code, result, stderr = self.invoke(["batch", "-", "--output-dir", str(output_dir), "--json"])
            self.assertEqual(2, len(list(output_dir.glob("*.epub"))))
        self.assertEqual(3, code)
        self.assertEqual("partial", result["status"])
        self.assertEqual(3, result["total"])
        self.assertEqual(2, result["succeeded"])
        self.assertEqual(1, result["failed"])
        self.assertEqual([first, bad, last], [item["input"] for item in result["results"]])
        self.assertEqual([0, 1, 0], [item["exitCode"] for item in result["results"]])
        self.assertEqual(3, fetching.call_count)
        self.assertIn("Article 3/3", stderr)

    def test_failed_submission_is_not_retried_and_retains_epub(self):
        with tempfile.TemporaryDirectory() as directory, \
                patch("sys.stdin", io.StringIO("https://openai.com/first\nhttps://openai.com/last")), \
                patch("cli.main.fetch_html", side_effect=lambda url: ("html", url)), \
                patch("cli.main.extract_article", side_effect=self.article), \
                patch("cli.main.submission_settings", return_value=({}, 587, "reader@kindle.com")) as preflight, \
                patch("cli.main.send_to_kindle", side_effect=[ArticleError("SMTP unavailable"), None]) as send:
            code, result, _ = self.invoke(["batch", "-", "--output-dir", directory, "--send", "--json"])
            self.assertTrue(Path(result["results"][0]["output"]).exists())
        self.assertEqual(3, code)
        self.assertEqual("unconfirmed", result["results"][0]["submission"])
        self.assertEqual("smtp_accepted", result["results"][1]["submission"])
        self.assertEqual(2, send.call_count)
        preflight.assert_called_once()

    def test_all_failed_and_invalid_input(self):
        with tempfile.TemporaryDirectory() as directory, patch("sys.stdin", io.StringIO("https://openai.com/bad")), \
                patch("cli.main.fetch_html", side_effect=ArticleError("Unavailable")):
            code, result, _ = self.invoke(["batch", "-", "--output-dir", directory, "--json"])
        self.assertEqual(1, code)
        self.assertEqual("error", result["status"])
        with patch("sys.stdin", io.StringIO("# empty\n")):
            code, _, _ = self.invoke(["batch", "-", "--json"])
        self.assertEqual(1, code)
        code, _, _ = self.invoke(["batch", "-", "--to", "reader@kindle.com", "--json"])
        self.assertEqual(2, code)

    def test_interruption_keeps_completed_results(self):
        with tempfile.TemporaryDirectory() as directory, \
                patch("sys.stdin", io.StringIO("https://openai.com/first\nhttps://openai.com/last")), \
                patch("cli.main.fetch_html", side_effect=[("html", "https://openai.com/first"), KeyboardInterrupt]), \
                patch("cli.main.extract_article", side_effect=self.article):
            code, result, _ = self.invoke(["--json", "batch", "-", "--output-dir", directory])
        self.assertEqual(130, code)
        self.assertEqual(1, result["succeeded"])
        self.assertEqual(130, result["results"][1]["exitCode"])
        self.assertEqual("ok", result["results"][0]["status"])

    def test_batch_input_is_bounded(self):
        with patch("sys.stdin", io.StringIO("\n".join(f"https://openai.com/{index}" for index in range(1001)))):
            with self.assertRaisesRegex(ArticleError, "1000"):
                read_urls("-")
        with patch("sys.stdin", io.StringIO("x" * 8193)):
            with self.assertRaisesRegex(ArticleError, "8192"):
                read_urls("-")


if __name__ == "__main__":
    unittest.main()
