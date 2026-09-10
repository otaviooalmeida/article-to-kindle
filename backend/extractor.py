"""Fetch and normalize the readable part of supported article pages."""

from __future__ import annotations

import base64
import mimetypes
import re
from html import escape
from urllib.error import HTTPError, URLError
from urllib.parse import unquote_to_bytes, urljoin, urlparse
from urllib.request import Request, urlopen

from bs4 import BeautifulSoup, Comment, Tag
from latex2mathml.converter import convert as latex_to_mathml_markup

from .config import MAX_CAPTURE_BYTES
from .errors import ArticleError
from .models import Article, ImageAsset


USER_AGENT = "article-to-kindle/0.1 (+https://github.com/)"
MAX_HTML_BYTES = MAX_CAPTURE_BYTES
MAX_IMAGE_BYTES = 5 * 1024 * 1024
MAX_TOTAL_IMAGE_BYTES = 50 * 1024 * 1024
ALLOWED_HOSTS = ("medium.com", "towardsdatascience.com")
ALLOWED_TAGS = {
    "a", "b", "blockquote", "br", "code", "em", "figcaption", "figure", "h1",
    "h2", "h3", "h4", "hr", "i", "img", "li", "ol", "p", "pre", "strong",
    "table", "tbody", "td", "th", "thead", "tr", "ul", "math", "mrow", "mi",
    "mn", "mo", "mfrac", "msqrt", "msup", "msub", "msubsup", "mtext", "mstyle",
    "semantics", "annotation", "menclose", "merror", "mfenced", "mmultiscripts",
    "mover", "mpadded", "mphantom", "mprescripts", "mroot", "mspace", "mtable",
    "mtd", "mtr", "munder", "munderover", "none",
}
IMAGE_EXTENSIONS = {
    "image/gif": ".gif", "image/jpeg": ".jpg", "image/png": ".png",
    "image/svg+xml": ".svg", "image/webp": ".webp",
}


def allowed_url(url: str) -> bool:
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    return parsed.scheme in {"http", "https"} and any(
        host == domain or host.endswith(f".{domain}") for domain in ALLOWED_HOSTS
    )


def require_article_url(url: str) -> None:
    if not allowed_url(url):
        raise ArticleError(f"URL must be an http(s) article on {' or '.join(ALLOWED_HOSTS)}.")


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
    body, _, final_url = read_url(url, MAX_HTML_BYTES, "text/html")
    require_article_url(final_url)
    charset = BeautifulSoup(body, "html.parser").original_encoding or "utf-8"
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
    for tag in root.select("script, style, noscript, svg, iframe, form, button, nav, footer, aside, [class*='recommend'], [id*='recommend'], [data-testid*='recommend']"):
        tag.decompose()


def latex_to_mathml(latex: str, display: bool = False) -> str:
    markup = latex_to_mathml_markup(latex.strip())
    return markup.replace('display="inline"', f'display="{"block" if display else "inline"}"', 1)


def _replace_with_math(node: Tag, latex: str, display: bool = False) -> None:
    fragment = BeautifulSoup(latex_to_mathml(latex, display), "html.parser")
    node.replace_with(fragment.math)


def extract_math(root: Tag) -> list[str]:
    failed = 0
    for tag in list(root.find_all(["script", "span", "div"])[::-1]):
        classes = " ".join(tag.get("class", [])) if tag.name != "script" else ""
        annotation = tag.find("annotation", attrs={"encoding": "application/x-tex"})
        latex = tag.get("data-latex") or tag.get("data-tex") or (annotation.get_text() if annotation else None)
        if tag.name == "script" and "math/tex" in tag.get("type", ""):
            latex = tag.get_text()
        if latex:
            try:
                _replace_with_math(tag, latex, "display" in classes or "display" in tag.get("data-mode", ""))
            except Exception:
                tag.replace_with(latex)
                failed += 1

    pattern = re.compile(r"(\\\[(.+?)\\\]|\\\((.+?)\\\)|\$\$(.+?)\$\$|\$(?!\s)(.+?)(?<!\s)\$)", re.DOTALL)
    for text_node in list(root.find_all(string=True)):
        if text_node.parent and text_node.parent.name in {"math", "script", "style"} or not pattern.search(str(text_node)):
            continue
        fragment, last = BeautifulSoup("", "html.parser"), 0
        for match in pattern.finditer(str(text_node)):
            fragment.append(str(text_node)[last:match.start()])
            latex = next(part for part in match.groups()[1:] if part is not None)
            try:
                fragment.append(BeautifulSoup(latex_to_mathml(latex, match.group().startswith(("\\[", "$$"))), "html.parser").math)
            except Exception:
                fragment.append(latex)
                failed += 1
            last = match.end()
        fragment.append(str(text_node)[last:])
        text_node.replace_with(*list(fragment.contents))
    return [f"{failed} formula(s) retained as text"] if failed else []


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
            source = str(source) if source and str(source).startswith("data:image/") else make_absolute(str(source), base_url) if source else None
            if source:
                tag.attrs = {"src": source, "alt": clean_text(str(tag.get("alt", "")))}
            else:
                tag.decompose()
        else:
            tag.attrs = {key: value for key, value in tag.attrs.items() if tag.name == "math" and key in {"xmlns", "display"}}


def download_images(root: Tag) -> tuple[list[ImageAsset], int]:
    assets, fetched, failed, total_bytes = [], {}, 0, 0
    for tag in list(root.find_all("img")):
        source = str(tag.get("src", ""))
        if source in fetched:
            tag["src"] = fetched[source].href
            continue
        try:
            if source.startswith("data:image/"):
                header, encoded = source.split(",", 1)
                media_type = header[5:].split(";", 1)[0]
                data = base64.b64decode(encoded, validate=True) if ";base64" in header else unquote_to_bytes(encoded)
                if len(data) > MAX_IMAGE_BYTES:
                    raise ArticleError("Image is larger than the limit.")
            else:
                data, media_type, final_url = read_url(source, MAX_IMAGE_BYTES, "image/")
                if urlparse(final_url).scheme not in {"http", "https"}:
                    raise ArticleError("Image redirected to an unsupported URL.")
            if media_type not in IMAGE_EXTENSIONS or total_bytes + len(data) > MAX_TOTAL_IMAGE_BYTES:
                raise ArticleError("Unsupported image type or article image limit exceeded.")
            extension = IMAGE_EXTENSIONS[media_type] or mimetypes.guess_extension(media_type) or ".img"
            asset = ImageAsset(f"images/image-{len(assets) + 1}{extension}", data, media_type)
            assets.append(asset)
            total_bytes += len(data)
            fetched[source] = asset
            tag["src"] = asset.href
        except (ArticleError, ValueError, TypeError):
            tag.decompose()
            failed += 1
    return assets, failed


def extract_article(page_html: str, source_url: str) -> Article:
    soup = BeautifulSoup(page_html, "html.parser")
    root = choose_article_root(soup)
    title = clean_text(first_meta(soup, "og:title", "twitter:title")) or clean_text(root.find("h1").get_text(" ", strip=True) if root.find("h1") else "") or clean_text(soup.title.get_text(" ", strip=True) if soup.title else "")
    if not title:
        raise ArticleError("Could not find an article title.")
    author = clean_text(first_meta(soup, "author", "article:author")) or "Unknown author"
    warnings = extract_math(root)
    remove_noise(root)
    sanitize_article(root, source_url)
    if len(clean_text(root.get_text(" ", strip=True))) < 100:
        raise ArticleError("Could not find enough readable article content (it may be paywalled).")
    headings = []
    for index, heading in enumerate(root.find_all(["h2", "h3", "h4"]), start=1):
        heading_id = f"section-{index}"
        heading["id"] = heading_id
        headings.append((heading_id, clean_text(heading.get_text(" ", strip=True))))
    images, failed_images = download_images(root)
    if failed_images:
        warnings.append(f"{failed_images} image(s) omitted")
    return Article(title, author, source_url, "".join(str(child) for child in root.contents), headings, images, warnings)


def slugify(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")[:80] or "article"
