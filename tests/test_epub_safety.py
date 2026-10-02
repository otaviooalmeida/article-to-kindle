import tempfile
import unittest
import zipfile
from pathlib import Path

from backend.epub import read_epub_metadata, write_epub
from backend.errors import ArticleError
from backend.models import Article


class EpubSafetyTest(unittest.TestCase):
    def article(self):
        return Article("Title", "Ada", "https://openai.com/article", "<p>content</p>", [], [])

    def test_no_clobber_is_enforced_at_publication_not_only_path_selection(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "article.epub"
            output.write_bytes(b"existing file")
            with self.assertRaisesRegex(ArticleError, "already exists"):
                write_epub(self.article(), output, overwrite=False)
            self.assertEqual(b"existing file", output.read_bytes())
            self.assertEqual([output], list(Path(directory).iterdir()))

    def test_new_file_is_valid_and_temporary_file_is_removed(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "article.epub"
            write_epub(self.article(), output, overwrite=False)
            self.assertEqual("Title", read_epub_metadata(output).title)
            self.assertEqual([output], list(Path(directory).iterdir()))

    def test_existing_symlink_is_not_followed_or_replaced(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "missing.epub"
            output = Path(directory) / "article.epub"
            output.symlink_to(target)
            with self.assertRaisesRegex(ArticleError, "already exists"):
                write_epub(self.article(), output, overwrite=False)
            self.assertTrue(output.is_symlink())
            self.assertFalse(target.exists())

    def test_dtd_and_oversized_metadata_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "article.epub"
            for data, message in ((b'<!DOCTYPE container [<!ENTITY x "unsafe">]><container/>', "DTDs"),
                                  (b"x" * (1024 * 1024 + 1), "1 MiB")):
                with self.subTest(message=message):
                    with zipfile.ZipFile(output, "w") as book:
                        book.writestr("mimetype", b"application/epub+zip")
                        book.writestr("META-INF/container.xml", data)
                    with self.assertRaisesRegex(ArticleError, message):
                        read_epub_metadata(output)


if __name__ == "__main__":
    unittest.main()
