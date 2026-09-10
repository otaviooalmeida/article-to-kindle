"""Command-line entry point for article-to-kindle."""

from __future__ import annotations

import argparse
import hashlib
import os
import sys
import tempfile
import zipfile
from pathlib import Path

from backend.config import KINDLE_EMAIL
from backend.delivery import send_to_kindle
from backend.epub import write_epub
from backend.errors import ArticleError
from backend.extractor import extract_article, fetch_html, slugify


def available_output(article, requested: Path | None) -> Path:
    if requested:
        if requested.exists():
            raise ArticleError(f"Output already exists: {requested}")
        if not requested.parent.exists():
            raise ArticleError(f"Output directory does not exist: {requested.parent}")
        return requested
    stem = f"{slugify(article.title)}-{hashlib.sha256(article.source_url.encode()).hexdigest()[:8]}"
    output_dir = Path.cwd() / "outputs"
    output_dir.mkdir(exist_ok=True)
    candidate = output_dir / f"{stem}.epub"
    index = 2
    while candidate.exists():
        candidate = output_dir / f"{stem}-{index}.epub"
        index += 1
    return candidate


def self_test() -> None:
    sample = r'''<html><head><meta property="og:title" content="Hello Kindle"/><meta name="author" content="Ada"/></head><body><article><h1>Hello Kindle</h1><p>This is enough sample text to make the article extractor accept it as a readable article body for the EPUB self-test.</p><p>Formula: \(x^2 + \frac{1}{2}\).</p><p>Fallback: \(\begin{matrix}\).</p><span class="katex"><annotation encoding="application/x-tex">y=\sqrt{x}</annotation></span><figure><img src="data:image/png;base64,invalid"/></figure><h2>Second section</h2><pre><code>print('hello')</code></pre><nav>Ignore this</nav></article></body></html>'''
    article = extract_article(sample, "https://medium.com/example/hello")
    assert "<math" in article.content_html and "<mfrac>" in article.content_html
    assert r"\frac" not in article.content_html and r"\begin{matrix}" in article.content_html
    assert article.warnings == ["1 formula(s) retained as text", "1 image(s) omitted"]
    with tempfile.TemporaryDirectory() as directory:
        epub = Path(directory) / "hello.epub"
        write_epub(article, epub)
        with zipfile.ZipFile(epub) as book:
            assert book.read("mimetype") == b"application/epub+zip"
            assert "OEBPS/article.xhtml" in book.namelist()
    print("self-test passed")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("url", nargs="?", help="Public Medium or Towards Data Science article URL")
    parser.add_argument("--output", type=Path, help="Where to write the EPUB")
    delivery = parser.add_mutually_exclusive_group()
    delivery.add_argument("--send", action="store_true", help="Email the EPUB to KINDLE_EMAIL")
    delivery.add_argument("--dry-run", action="store_true", help="Create the EPUB without sending email")
    parser.add_argument("--self-test", action="store_true", help="Run the built-in EPUB check")
    parser.add_argument("--serve", action="store_true", help="Run the local API on 127.0.0.1:8765")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    if args.serve:
        import uvicorn
        uvicorn.run("backend.api:app", host="127.0.0.1", port=8765, log_level="warning")
        return 0
    if not args.url:
        parser.error("a URL is required unless --self-test or --serve is used")
    page_html, final_url = fetch_html(args.url)
    article = extract_article(page_html, final_url)
    output = available_output(article, args.output)
    write_epub(article, output)
    print(f"Created: {output}")
    if args.send:
        send_to_kindle(article, output)
        print(f"Sent to: {os.environ[KINDLE_EMAIL]}")
    elif args.dry_run:
        print("Dry run: email not sent.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ArticleError as error:
        print(f"error: {error}", file=sys.stderr)
        raise SystemExit(1)
