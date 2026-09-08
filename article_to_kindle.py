#!/usr/bin/env python3
"""Extract a public Medium article into an EPUB and optionally email it to Kindle."""

from __future__ import annotations

import argparse
import hashlib
import mimetypes
import os
import re
import smtplib
import ssl
import sys
import tempfile
import uuid
import zipfile
from dataclasses import dataclass
from datetime import UTC, datetime
from email.message import EmailMessage
from html import escape
from pathlib import Path
from typing import Iterable
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen

from bs4 import BeautifulSoup, Comment, Tag


USER_AGENT = "article-to-kindle/0.1 (+https://github.com/)"
MAX_HTML_BYTES = 10 * 1024 * 1024
MAX_IMAGE_BYTES = 5 * 1024 * 1024
MAX_IMAGES = 10
ALLOWED_HOSTS = ("medium.com", "towardsdatascience.com")
ALLOWED_TAGS = {
    "a", "b", "blockquote", "br", "code", "em", "figcaption", "figure", "h1",
    "h2", "h3", "h4", "hr", "i", "img", "li", "ol", "p", "pre", "strong",
    "table", "tbody", "td", "th", "thead", "tr", "ul",
}
IMAGE_EXTENSIONS = {
    "image/gif": ".gif",
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/svg+xml": ".svg",
    "image/webp": ".webp",
}


class ArticleError(Exception):
    """An expected user-facing error."""


@dataclass
class ImageAsset:
    href: str
    data: bytes
    media_type: str


@dataclass
class Article:
    title: str
    author: str
    source_url: str
    content_html: str
    headings: list[tuple[str, str]]
    images: list[ImageAsset]


def allowed_url(url: str) -> bool:
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    return parsed.scheme in {"http", "https"} and any(
        host == domain or host.endswith(f".{domain}") for domain in ALLOWED_HOSTS
    )


def require_article_url(url: str) -> None:
    if not allowed_url(url):
        domains = " or ".join(ALLOWED_HOSTS)
        raise ArticleError(f"URL must be an http(s) article on {domains}.")


def read_url(url: str, limit: int, expected: str | None = None) -> tuple[bytes, str, str]:
    request = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml,*/*;q=0.8"})
    try:
        with urlopen(request, timeout=20) as response:
            final_url = response.geturl()
            content_type = response.headers.get_content_type()
            declared_length = response.headers.get("Content-Length")
            if declared_length and int(declared_length) > limit:
                raise ArticleError(f"Response is larger than the {limit // 1024 // 1024} MB limit.")
            if expected and not content_type.startswith(expected):
                raise ArticleError(f"Expected {expected} content, got {content_type}.")
            body = response.read(limit + 1)
            if len(body) > limit:
                raise ArticleError(f"Response is larger than the {limit // 1024 // 1024} MB limit.")
            return body, content_type, final_url
    except HTTPError as error:
        raise ArticleError(f"Could not fetch article (HTTP {error.code}).") from error
    except URLError as error:
        raise ArticleError(f"Could not fetch article: {error.reason}") from error


def fetch_html(url: str) -> tuple[str, str]:
    require_article_url(url)
    body, content_type, final_url = read_url(url, MAX_HTML_BYTES, "text/html")
    require_article_url(final_url)
    charset = "utf-8"
    try:
        charset = BeautifulSoup(body, "html.parser").original_encoding or charset
    except Exception:
        pass
    return body.decode(charset, errors="replace"), final_url


def first_meta(soup: BeautifulSoup, *names: str) -> str:
    for name in names:
        tag = soup.find("meta", attrs={"property": name}) or soup.find("meta", attrs={"name": name})
        if tag and tag.get("content"):
            return tag["content"].strip()
    return ""


def clean_text(value: str | None) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def choose_article_root(soup: BeautifulSoup) -> Tag:
    root = soup.select_one("article") or soup.select_one("[role=main]") or soup.find("main") or soup.body
    if not isinstance(root, Tag):
        raise ArticleError("The page has no readable article body.")
    return root


def make_absolute(url: str, base_url: str) -> str | None:
    absolute = urljoin(base_url, url)
    return absolute if urlparse(absolute).scheme in {"http", "https"} else None


def remove_noise(root: Tag) -> None:
    for comment in root.find_all(string=lambda value: isinstance(value, Comment)):
        comment.extract()
    for tag in root.select(
        "script, style, noscript, svg, iframe, form, button, nav, footer, aside, "
        "[class*='recommend'], [id*='recommend'], [data-testid*='recommend']"
    ):
        tag.decompose()


def sanitize_article(root: Tag, base_url: str) -> None:
    for tag in list(root.find_all(True)):
        if tag.name not in ALLOWED_TAGS:
            tag.unwrap()
            continue

        if tag.name == "a":
            href = make_absolute(str(tag.get("href", "")), base_url)
            tag.attrs = {"href": href} if href else {}
        elif tag.name == "img":
            source = tag.get("src") or tag.get("data-src")
            source = make_absolute(str(source), base_url) if source else None
            if source:
                tag.attrs = {"src": source, "alt": clean_text(str(tag.get("alt", "")))}
            else:
                tag.decompose()
        else:
            tag.attrs = {}


def download_images(root: Tag) -> list[ImageAsset]:
    assets: list[ImageAsset] = []
    fetched: dict[str, ImageAsset] = {}
    for tag in list(root.find_all("img")):
        source = str(tag.get("src", ""))
        if source in fetched:
            tag["src"] = fetched[source].href
            continue
        if len(assets) >= MAX_IMAGES:
            tag.decompose()
            continue
        try:
            data, media_type, final_url = read_url(source, MAX_IMAGE_BYTES, "image/")
            if urlparse(final_url).scheme not in {"http", "https"}:
                raise ArticleError("Image redirected to an unsupported URL.")
            extension = IMAGE_EXTENSIONS.get(media_type, mimetypes.guess_extension(media_type) or ".img")
            asset = ImageAsset(f"images/image-{len(assets) + 1}{extension}", data, media_type)
            assets.append(asset)
            fetched[source] = asset
            tag["src"] = asset.href
        except ArticleError:
            tag.decompose()
    return assets


def extract_article(page_html: str, source_url: str) -> Article:
    soup = BeautifulSoup(page_html, "html.parser")
    root = choose_article_root(soup)
    title = clean_text(first_meta(soup, "og:title", "twitter:title"))
    title = title or clean_text(root.find("h1").get_text(" ", strip=True) if root.find("h1") else "")
    title = title or clean_text(soup.title.get_text(" ", strip=True) if soup.title else "")
    if not title:
        raise ArticleError("Could not find an article title.")
    author = clean_text(first_meta(soup, "author", "article:author")) or "Unknown author"

    remove_noise(root)
    sanitize_article(root, source_url)
    if len(clean_text(root.get_text(" ", strip=True))) < 100:
        raise ArticleError("Could not find enough readable article content (it may be paywalled).")

    headings: list[tuple[str, str]] = []
    for index, heading in enumerate(root.find_all(["h2", "h3", "h4"]), start=1):
        heading_id = f"section-{index}"
        heading["id"] = heading_id
        headings.append((heading_id, clean_text(heading.get_text(" ", strip=True))))
    images = download_images(root)
    content = "".join(str(child) for child in root.contents)
    return Article(title, author, source_url, content, headings, images)


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug[:80] or "article"


def available_output(article: Article, requested: Path | None) -> Path:
    if requested:
        if requested.exists():
            raise ArticleError(f"Output already exists: {requested}")
        if not requested.parent.exists():
            raise ArticleError(f"Output directory does not exist: {requested.parent}")
        return requested
    stem = f"{slugify(article.title)}-{hashlib.sha256(article.source_url.encode()).hexdigest()[:8]}"
    candidate = Path.cwd() / f"{stem}.epub"
    index = 2
    while candidate.exists():
        candidate = Path.cwd() / f"{stem}-{index}.epub"
        index += 1
    return candidate


def epub_xhtml(article: Article) -> str:
    return f'''<?xml version="1.0" encoding="utf-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml"><head><title>{escape(article.title)}</title><link rel="stylesheet" type="text/css" href="style.css"/></head>
<body><article><h1>{escape(article.title)}</h1><p class="byline">{escape(article.author)}</p><p class="source">Source: <a href="{escape(article.source_url, quote=True)}">{escape(article.source_url)}</a></p>{article.content_html}</article></body></html>'''


def nav_xhtml(article: Article) -> str:
    items = "".join(f'<li><a href="article.xhtml#{escape(item_id)}">{escape(text)}</a></li>' for item_id, text in article.headings)
    return f'''<?xml version="1.0" encoding="utf-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml"><head><title>Contents</title></head><body><nav epub:type="toc" id="toc" xmlns:epub="http://www.idpf.org/2007/ops"><h1>Contents</h1><ol><li><a href="article.xhtml">{escape(article.title)}</a></li>{items}</ol></nav></body></html>'''


CSS = """
body { font-family: serif; line-height: 1.5; margin: 5%; }
h1, h2, h3, h4 { line-height: 1.2; margin-top: 1.5em; }
.byline, .source { color: #555; font-size: 0.9em; }
pre { background: #f4f4f4; padding: 0.8em; white-space: pre-wrap; font-family: monospace; }
code { font-family: monospace; }
img { display: block; max-width: 100%; height: auto; margin: 1em auto; }
blockquote { border-left: 0.25em solid #aaa; margin-left: 0; padding-left: 1em; }
table { border-collapse: collapse; max-width: 100%; } td, th { border: 1px solid #aaa; padding: 0.35em; }
""".strip()


def write_epub(article: Article, destination: Path) -> None:
    identifier = uuid.uuid5(uuid.NAMESPACE_URL, article.source_url)
    image_manifest = "".join(
        f'<item id="image-{index}" href="{escape(asset.href, quote=True)}" media-type="{escape(asset.media_type, quote=True)}"/>'
        for index, asset in enumerate(article.images, start=1)
    )
    manifest = (
        '<item id="article" href="article.xhtml" media-type="application/xhtml+xml"/>'
        '<item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>'
        '<item id="css" href="style.css" media-type="text/css"/>'
        f"{image_manifest}"
    )
    opf = f'''<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://www.idpf.org/2007/opf" unique-identifier="book-id" version="3.0"><metadata xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:identifier id="book-id">urn:uuid:{identifier}</dc:identifier><dc:title>{escape(article.title)}</dc:title><dc:creator>{escape(article.author)}</dc:creator><dc:language>en</dc:language><dc:source>{escape(article.source_url)}</dc:source><meta property="dcterms:modified">{datetime.now(UTC).strftime('%Y-%m-%dT%H:%M:%SZ')}</meta></metadata><manifest>{manifest}</manifest><spine><itemref idref="article"/></spine></package>'''
    container = '''<?xml version="1.0" encoding="UTF-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container"><rootfiles><rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/></rootfiles></container>'''

    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(dir=destination.parent, suffix=".epub", delete=False) as handle:
            temporary = Path(handle.name)
        with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED) as book:
            book.writestr("mimetype", "application/epub+zip", compress_type=zipfile.ZIP_STORED)
            book.writestr("META-INF/container.xml", container)
            book.writestr("OEBPS/content.opf", opf)
            book.writestr("OEBPS/style.css", CSS)
            book.writestr("OEBPS/article.xhtml", epub_xhtml(article))
            book.writestr("OEBPS/nav.xhtml", nav_xhtml(article))
            for asset in article.images:
                book.writestr(f"OEBPS/{asset.href}", asset.data)
        if not zipfile.is_zipfile(temporary):
            raise ArticleError("EPUB creation failed validation.")
        temporary.replace(destination)
        temporary = None
    finally:
        if temporary and temporary.exists():
            temporary.unlink()


def required_environment(names: Iterable[str]) -> dict[str, str]:
    values = {name: os.environ.get(name, "") for name in names}
    missing = [name for name, value in values.items() if not value]
    if missing:
        raise ArticleError(f"Missing environment variables for --send: {', '.join(missing)}")
    return values


def send_to_kindle(article: Article, epub: Path) -> None:
    settings = required_environment(("KINDLE_EMAIL", "SMTP_HOST", "SMTP_USERNAME", "SMTP_PASSWORD", "SMTP_FROM"))
    port = int(os.environ.get("SMTP_PORT", "587"))
    message = EmailMessage()
    message["From"] = settings["SMTP_FROM"]
    message["To"] = settings["KINDLE_EMAIL"]
    message["Subject"] = article.title
    message.set_content(f"{article.title}\n\nSource: {article.source_url}")
    message.add_attachment(epub.read_bytes(), maintype="application", subtype="epub+zip", filename=epub.name)

    context = ssl.create_default_context()
    try:
        if port == 465:
            with smtplib.SMTP_SSL(settings["SMTP_HOST"], port, context=context, timeout=30) as client:
                client.login(settings["SMTP_USERNAME"], settings["SMTP_PASSWORD"])
                client.send_message(message)
        else:
            with smtplib.SMTP(settings["SMTP_HOST"], port, timeout=30) as client:
                client.starttls(context=context)
                client.login(settings["SMTP_USERNAME"], settings["SMTP_PASSWORD"])
                client.send_message(message)
    except (OSError, smtplib.SMTPException) as error:
        raise ArticleError(f"EPUB was created but email delivery failed: {error}") from error


def self_test() -> None:
    sample = """<html><head><meta property="og:title" content="Hello Kindle"/><meta name="author" content="Ada"/></head><body><article><h1>Hello Kindle</h1><p>This is enough sample text to make the article extractor accept it as a readable article body for the EPUB self-test.</p><h2>Second section</h2><pre><code>print('hello')</code></pre><nav>Ignore this</nav></article></body></html>"""
    article = extract_article(sample, "https://medium.com/example/hello")
    with tempfile.TemporaryDirectory() as directory:
        epub = Path(directory) / "hello.epub"
        write_epub(article, epub)
        with zipfile.ZipFile(epub) as book:
            assert book.read("mimetype") == b"application/epub+zip"
            assert "OEBPS/article.xhtml" in book.namelist()
            assert b"Hello Kindle" in book.read("OEBPS/article.xhtml")
    print("self-test passed")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("url", nargs="?", help="Public Medium or Towards Data Science article URL")
    parser.add_argument("--output", type=Path, help="Where to write the EPUB")
    delivery = parser.add_mutually_exclusive_group()
    delivery.add_argument("--send", action="store_true", help="Email the EPUB to KINDLE_EMAIL")
    delivery.add_argument("--dry-run", action="store_true", help="Create the EPUB without sending email")
    parser.add_argument("--self-test", action="store_true", help="Run the built-in EPUB check")
    args = parser.parse_args()

    if args.self_test:
        self_test()
        return 0
    if not args.url:
        parser.error("a URL is required unless --self-test is used")

    page_html, final_url = fetch_html(args.url)
    article = extract_article(page_html, final_url)
    output = available_output(article, args.output)
    write_epub(article, output)
    print(f"Created: {output}")
    if args.send:
        send_to_kindle(article, output)
        print(f"Sent to: {os.environ['KINDLE_EMAIL']}")
    elif args.dry_run:
        print("Dry run: email not sent.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ArticleError as error:
        print(f"error: {error}", file=sys.stderr)
        raise SystemExit(1)
