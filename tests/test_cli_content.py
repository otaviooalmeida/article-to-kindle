import io
import json
import tempfile
import unittest
import zipfile
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from backend.epub import read_epub_metadata
from cli.main import main
from cli.sources import read_capture, read_input
from backend.errors import ArticleError

URL = "https://openai.com/research/article"
HTML = '''<html><head><script type="application/ld+json">{"@type":"Article","headline":"Old title","author":{"name":"Original author"}}</script></head><body><article><h1>Old title</h1><p>''' + "Readable content with enough words. " * 8 + '''<a href="/reference">Reference text</a><img src="https://example.com/chart.png" alt="Chart"></p></article></body></html>'''


class CliContentTest(unittest.TestCase):
    def invoke(self, args):
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            return main(args)

    def test_saved_html_preferences_and_metadata(self):
        with tempfile.TemporaryDirectory() as directory, patch("backend.extractor.read_url") as fetch:
            source = Path(directory) / "saved.html"
            source.write_text(HTML)
            output = Path(directory) / "article.epub"
            self.assertEqual(0, self.invoke(["convert", "--html", str(source), "--source-url", URL,
                                             "--no-images", "--no-links", "--title", "New title", "--author", "Ada",
                                             "--output", str(output)]))
            article = read_epub_metadata(output)
            self.assertEqual("New title", article.title)
            self.assertEqual("Ada", article.author)
            with zipfile.ZipFile(output) as book:
                content = book.read("OEBPS/article.xhtml").decode()
                self.assertNotIn("<img", content)
                self.assertNotIn("<a ", content)
                self.assertIn("Reference text", content)
                self.assertIn(URL, content)
                self.assertNotIn("Old title", content)
                self.assertFalse(any("images/" in name for name in book.namelist()))
        fetch.assert_not_called()

    def test_capture_from_stdin_does_not_trust_recipient(self):
        capture = {"title": "Captured title", "author": "Grace", "sourceUrl": URL,
                   "html": "<article><p>" + "Readable content. " * 15 + "</p></article>",
                   "kindleEmail": "attacker@example.com"}
        with tempfile.TemporaryDirectory() as directory, patch("sys.stdin", io.StringIO(json.dumps(capture))), \
                patch("cli.main.send_to_kindle") as send, patch("cli.main.fetch_html") as fetch:
            output = Path(directory) / "article.epub"
            self.assertEqual(0, self.invoke(["convert", "--capture", "-", "-o", str(output)]))
            self.assertEqual("Captured title", read_epub_metadata(output).title)
            self.assertEqual("Grace", read_epub_metadata(output).author)
        send.assert_not_called()
        fetch.assert_not_called()

    def test_html_stdin_and_title_without_page_metadata(self):
        with tempfile.TemporaryDirectory() as directory, patch("sys.stdin", io.StringIO("<article><p>" + "Readable content. " * 15 + "</p></article>")):
            output = Path(directory) / "article.epub"
            self.assertEqual(0, self.invoke(["convert", "--html", "-", "--source-url", URL,
                                             "--title", "Explicit title", "-o", str(output)]))
            self.assertEqual("Explicit title", read_epub_metadata(output).title)

    def test_invalid_inputs_and_conflicting_modes(self):
        for args in (["convert"], ["convert", "--html", "file"],
                     ["convert", URL, "--html", "file", "--source-url", URL],
                     ["convert", URL, "--source-url", URL]):
            with self.subTest(args=args):
                self.assertEqual(2, self.invoke(args))
        for value in ({}, {"title": True}, [], "bad json"):
            with self.subTest(value=value), patch("sys.stdin", io.StringIO(json.dumps(value))):
                with self.assertRaises(ArticleError):
                    read_capture("-")
        with patch("sys.stdin", io.BytesIO(b"\xff")):
            with self.assertRaisesRegex(ArticleError, "UTF-8"):
                read_input("-")

    def test_bounded_input_and_unsupported_source(self):
        with patch("sys.stdin", io.StringIO("x" * (10 * 1024 * 1024 + 65537))):
            with self.assertRaisesRegex(ArticleError, "limit"):
                read_input("-")
        with tempfile.TemporaryDirectory() as directory, patch("sys.stdin", io.StringIO(HTML)), \
                patch("backend.extractor.read_url") as fetch:
            self.assertEqual(1, self.invoke(["convert", "--html", "-", "--source-url", "https://unsupported.example/article",
                                             "-o", str(Path(directory) / "article.epub")]))
        fetch.assert_not_called()


if __name__ == "__main__":
    unittest.main()
