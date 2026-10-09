"""EPUB package generation."""

from __future__ import annotations

import os
import tempfile
import uuid
import zipfile
from datetime import UTC, datetime
from html import escape
import re
from pathlib import Path
from xml.etree import ElementTree

from .config import MAX_EPUB_BYTES
from .errors import ArticleError
from .models import Article

CSS = """
body { font-family: serif; line-height: 1.5; margin: 5%; }
h1, h2, h3, h4 { line-height: 1.2; margin-top: 1.5em; }
h1.title { font-size: 1.6em; }
.byline, .published-date, .source { color: #555; font-size: 0.9em; }
pre { background: #f4f4f4; padding: 0.8em; white-space: pre-wrap; font-family: monospace; }
code { font-family: monospace; }
img { display: block; max-width: 100%; height: auto; margin: 1em auto; }
blockquote { border-left: 0.25em solid #aaa; margin-left: 0; padding-left: 1em; }
table { border-collapse: collapse; max-width: 100%; } td, th { border: 1px solid #aaa; padding: 0.35em; }
math { font-size: 1.05em; } math[display="block"] { display: block; margin: 1em auto; text-align: center; }
""".strip()

EMOJI_RE = re.compile("[\\U0001F1E6-\\U0001F1FF\\U0001F300-\\U0001FAFF\\u2300-\\u23FF\\u2600-\\u27BF\\u2B00-\\u2BFF\\uFE0F\\u200D]")


def read_epub_metadata(path: Path) -> Article:
    """Read bounded EPUB metadata for resubmission; never extract archive members."""
    if path.stat().st_size > MAX_EPUB_BYTES:
        raise ArticleError("EPUB exceeds the 50 MiB Kindle submission limit.")

    def read_member(book, name):
        if book.getinfo(name).file_size > 1024 * 1024:
            raise ArticleError("EPUB metadata exceeds the 1 MiB limit.")
        return book.read(name)

    def xml(data):
        # EPUB metadata never needs DTDs or entities. Reject UTF-16/32 and NULs
        # as well so the declaration check cannot be bypassed by another encoding.
        if b"\x00" in data or b"<!DOCTYPE" in data.upper() or b"<!ENTITY" in data.upper():
            raise ArticleError("EPUB metadata must not contain DTDs or entities.")
        return ElementTree.fromstring(data)

    try:
        with zipfile.ZipFile(path) as book:
            if read_member(book, "mimetype") != b"application/epub+zip":
                raise ArticleError("File is not an EPUB.")
            container = xml(read_member(book, "META-INF/container.xml"))
            rootfile = container.find("{*}rootfiles/{*}rootfile")
            if rootfile is None or not rootfile.get("full-path"):
                raise ArticleError("EPUB has no package metadata.")
            package = xml(read_member(book, rootfile.get("full-path")))
        metadata = package.find("{*}metadata")
        if metadata is None:
            raise ArticleError("EPUB has no article metadata.")
        namespace = "{http://purl.org/dc/elements/1.1/}"
        title = (metadata.findtext(f"{namespace}title") or "").strip()
        author = (metadata.findtext(f"{namespace}creator") or "Unknown author").strip()
        source = (metadata.findtext(f"{namespace}source") or "").strip()
        published_date = (metadata.findtext(f"{namespace}date") or "").strip()
        if not title or "\n" in title or "\r" in title:
            raise ArticleError("EPUB title is missing or invalid.")
        return Article(title, author, source, "", [], [], [], published_date)
    except (zipfile.BadZipFile, KeyError, ElementTree.ParseError, RuntimeError, NotImplementedError) as error:
        raise ArticleError("Invalid or unsupported EPUB package.") from error


def without_emojis(value: str) -> str:
    return EMOJI_RE.sub("", value)


def epub_xhtml(article: Article, *, include_source_link: bool = True) -> str:
    title = without_emojis(article.title)
    author = without_emojis(article.author)
    source_url = without_emojis(article.source_url)
    content_html = without_emojis(article.content_html)
    published_date = without_emojis(article.published_date)
    date_markup = f'<p class="published-date">Published: {escape(published_date)}</p>' if published_date else ""
    source = (f'<a href="{escape(source_url, quote=True)}">{escape(source_url)}</a>'
              if include_source_link else escape(source_url))
    return f'''<?xml version="1.0" encoding="utf-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml"><head><title>{escape(title)}</title><link rel="stylesheet" type="text/css" href="style.css"/></head>
<body><article><h1 class="title">{escape(title)}</h1><p class="byline">{escape(author)}</p>{date_markup}{content_html}<p class="source">Source: {source}</p></article></body></html>'''


def nav_xhtml(article: Article) -> str:
    items = "".join(f'<li><a href="article.xhtml#{escape(item_id)}">{escape(without_emojis(text))}</a></li>' for item_id, text in article.headings)
    title = without_emojis(article.title)
    return f'''<?xml version="1.0" encoding="utf-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml"><head><title>Contents</title></head><body><nav epub:type="toc" id="toc" xmlns:epub="http://www.idpf.org/2007/ops"><h1>Contents</h1><ol><li><a href="article.xhtml">{escape(title)}</a></li>{items}</ol></nav></body></html>'''


def write_epub(article: Article, destination: Path, *, include_source_link: bool = True, overwrite: bool = True) -> None:
    identifier = uuid.uuid5(uuid.NAMESPACE_URL, article.source_url)
    title = without_emojis(article.title)
    author = without_emojis(article.author)
    source_url = without_emojis(article.source_url)
    published_date = without_emojis(article.published_date)
    date_metadata = f"<dc:date>{escape(published_date)}</dc:date>" if published_date else ""
    image_manifest = "".join(
        f'<item id="image-{index}" href="{escape(asset.href, quote=True)}" media-type="{escape(asset.media_type, quote=True)}"/>'
        for index, asset in enumerate(article.images, start=1)
    )
    manifest = '<item id="article" href="article.xhtml" media-type="application/xhtml+xml"/><item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/><item id="css" href="style.css" media-type="text/css"/>' + image_manifest
    opf = f'''<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://www.idpf.org/2007/opf" unique-identifier="book-id" version="3.0"><metadata xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:identifier id="book-id">urn:uuid:{identifier}</dc:identifier><dc:title>{escape(title)}</dc:title><dc:creator>{escape(author)}</dc:creator><dc:language>en</dc:language><dc:source>{escape(source_url)}</dc:source>{date_metadata}<meta property="dcterms:modified">{datetime.now(UTC).strftime('%Y-%m-%dT%H:%M:%SZ')}</meta></metadata><manifest>{manifest}</manifest><spine><itemref idref="article"/></spine></package>'''
    container = '''<?xml version="1.0" encoding="UTF-8"?><container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container"><rootfiles><rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/></rootfiles></container>'''
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=destination.parent, suffix=".epub", delete=False) as handle:
            temporary = Path(handle.name)
        with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED) as book:
            book.writestr("mimetype", "application/epub+zip", compress_type=zipfile.ZIP_STORED)
            book.writestr("META-INF/container.xml", container)
            book.writestr("OEBPS/content.opf", opf)
            book.writestr("OEBPS/style.css", CSS)
            book.writestr("OEBPS/article.xhtml", epub_xhtml(article, include_source_link=include_source_link))
            book.writestr("OEBPS/nav.xhtml", nav_xhtml(article))
            for asset in article.images:
                book.writestr(f"OEBPS/{asset.href}", asset.data)
        if not zipfile.is_zipfile(temporary):
            raise ValueError("EPUB creation failed validation.")
        if overwrite:
            temporary.replace(destination)
            temporary = None
        else:
            try:
                os.link(temporary, destination)
            except FileExistsError as error:
                raise ArticleError(f"Output already exists: {destination}") from error
    finally:
        if temporary and temporary.exists():
            temporary.unlink()
