"""EPUB package generation."""

from __future__ import annotations

import tempfile
import uuid
import zipfile
from datetime import UTC, datetime
from html import escape
from pathlib import Path


CSS = """
body { font-family: serif; line-height: 1.5; margin: 5%; }
h1, h2, h3, h4 { line-height: 1.2; margin-top: 1.5em; }
.byline, .source { color: #555; font-size: 0.9em; }
pre { background: #f4f4f4; padding: 0.8em; white-space: pre-wrap; font-family: monospace; }
code { font-family: monospace; }
img { display: block; max-width: 100%; height: auto; margin: 1em auto; }
blockquote { border-left: 0.25em solid #aaa; margin-left: 0; padding-left: 1em; }
table { border-collapse: collapse; max-width: 100%; } td, th { border: 1px solid #aaa; padding: 0.35em; }
math { font-size: 1.05em; } math[display="block"] { display: block; margin: 1em auto; text-align: center; }
""".strip()


def epub_xhtml(article) -> str:
    return f'''<?xml version="1.0" encoding="utf-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml"><head><title>{escape(article.title)}</title><link rel="stylesheet" type="text/css" href="style.css"/></head>
<body><article><h1>{escape(article.title)}</h1><p class="byline">{escape(article.author)}</p><p class="source">Source: <a href="{escape(article.source_url, quote=True)}">{escape(article.source_url)}</a></p>{article.content_html}</article></body></html>'''


def nav_xhtml(article) -> str:
    items = "".join(f'<li><a href="article.xhtml#{escape(item_id)}">{escape(text)}</a></li>' for item_id, text in article.headings)
    return f'''<?xml version="1.0" encoding="utf-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml"><head><title>Contents</title></head><body><nav epub:type="toc" id="toc" xmlns:epub="http://www.idpf.org/2007/ops"><h1>Contents</h1><ol><li><a href="article.xhtml">{escape(article.title)}</a></li>{items}</ol></nav></body></html>'''


def write_epub(article, destination: Path) -> None:
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
            raise ValueError("EPUB creation failed validation.")
        temporary.replace(destination)
        temporary = None
    finally:
        if temporary and temporary.exists():
            temporary.unlink()
