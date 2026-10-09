"""Fetch and normalize the readable part of supported article pages."""

from __future__ import annotations

import base64
import ipaddress
import json
import re
import socket
from datetime import date, datetime
from io import BytesIO
import mimetypes
import re
from html import escape
from urllib.error import HTTPError, URLError
from urllib.parse import unquote_to_bytes, urljoin, urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener

from bs4 import BeautifulSoup, Comment, NavigableString, Tag
from latex2mathml.converter import convert as latex_to_mathml_markup
from PIL import Image

from .article_analysis import select_article_root
from .config import MAX_CAPTURE_BYTES
from .nlp import classify_article_blocks
from .errors import ArticleError
from .models import Article, ImageAsset


USER_AGENT = "article-to-kindle/0.1 (+https://github.com/)"
MAX_HTML_BYTES = MAX_CAPTURE_BYTES
MAX_IMAGE_BYTES = 5 * 1024 * 1024
MAX_TOTAL_IMAGE_BYTES = 50 * 1024 * 1024
LOCAL_HOST_SUFFIXES = (".localhost", ".local", ".internal", ".lan", ".home", ".home.arpa")
NON_PUBLIC_SUFFIXES = {"test", "example", "invalid", "localhost", "local", "internal", "lan"}
DNS_LABEL = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$", re.IGNORECASE)
ALLOWED_TAGS = {
    "a", "b", "blockquote", "br", "code", "em", "figcaption", "figure", "h1",
    "h2", "h3", "h4", "hr", "i", "img", "li", "ol", "p", "pre", "strong",
    "table", "tbody", "td", "th", "thead", "tr", "ul", "span", "math", "mrow", "mi",
    "mn", "mo", "mfrac", "msqrt", "msup", "msub", "msubsup", "mtext", "mstyle",
    "semantics", "annotation", "annotation-xml", "maction", "maligngroup", "malignmark",
    "menclose", "merror", "mfenced", "mglyph", "mlabeledtr", "mlongdiv", "mmultiscripts",
    "mover", "mpadded", "mphantom", "mprescripts", "mroot", "mspace", "ms", "msgroup",
    "msline", "msqrt", "msrow", "mstack", "mtable", "mtd", "mtr", "munder",
    "munderover", "none",
}
MATHML_TAGS = {
    "math", "maction", "menclose", "merror", "mfenced", "mfrac", "mi", "mmultiscripts",
    "mn", "mo", "mover", "mpadded", "mphantom", "mprescripts", "mroot", "mrow", "ms",
    "mspace", "msqrt", "mstyle", "msub", "msubsup", "msup", "mtable", "mtd", "mtext",
    "mtr", "munder", "munderover", "none", "annotation", "annotation-xml", "maligngroup",
    "malignmark", "mlabeledtr", "mlongdiv", "msgroup", "msline", "msrow", "mstack", "semantics",
}
MATHML_ATTRIBUTES = {
    "accent", "accentunder", "align", "alttext", "bevelled", "charalign", "close",
    "columnalign", "columnlines", "columnspacing", "columnspan", "denomalign", "depth",
    "dir", "display", "displaystyle", "encoding", "equalcolumns", "equalrows", "fence",
    "form", "frame", "framespacing", "groupalign", "height", "indentalign", "indentshift",
    "infixlinebreakstyle", "largeop", "length", "linebreak", "linethickness", "location",
    "longdivstyle", "lspace", "mathbackground", "mathcolor", "mathsize", "mathvariant",
    "maxsize", "minlabelspacing", "minsize", "movablelimits", "notation", "numalign", "open",
    "overflow", "position", "rowalign", "rowlines", "rowspacing", "rowspan", "rspace",
    "scriptlevel", "selection", "separator", "separators", "side", "stackalign", "stretchy",
    "subscriptshift", "superscriptshift", "symmetric", "voffset", "width", "xmlns", "xml:lang",
}
MATHML_NAMESPACE = "http://www.w3.org/1998/Math/MathML"
IMAGE_EXTENSIONS = {
    "image/gif": ".gif", "image/jpeg": ".jpg", "image/png": ".png",
    "image/svg+xml": ".svg", "image/webp": ".webp",
}


def allowed_url(url: str) -> bool:
    """Accept public-looking HTTP(S) URLs without a publisher-specific allowlist."""
    try:
        parsed = urlparse(url)
        host = (parsed.hostname or "").rstrip(".").lower()
        parsed.port  # Reject malformed ports before the URL reaches a network client.
    except (AttributeError, TypeError, ValueError):
        return False
    if (parsed.scheme not in {"http", "https"} or not host or parsed.username or parsed.password
            or host == "localhost" or host.endswith(LOCAL_HOST_SUFFIXES)):
        return False
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        try:
            ascii_host = host.encode("idna").decode("ascii")
        except UnicodeError:
            return False
        labels = ascii_host.split(".")
        return (
            len(ascii_host) <= 253
            and len(labels) >= 2
            and labels[-1] not in NON_PUBLIC_SUFFIXES
            and not labels[-1].isdigit()
            and all(DNS_LABEL.fullmatch(label) for label in labels)
        )
    return address.is_global


def require_article_url(url: str) -> None:
    if not allowed_url(url):
        raise ArticleError("URL must be a public HTTP(S) webpage; local, private-network, and non-web URLs are not supported.")


def _require_public_dns(url: str) -> None:
    require_article_url(url)
    parsed = urlparse(url)
    host = parsed.hostname or ""
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        try:
            records = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
        except OSError as error:
            raise ArticleError("Could not resolve the public webpage host.") from error
        addresses = {record[4][0].split("%", 1)[0] for record in records}
        if not addresses or any(not ipaddress.ip_address(value).is_global for value in addresses):
            raise ArticleError("Webpage host must resolve only to public IP addresses; local/private addresses are blocked.")
    else:
        if not address.is_global:
            raise ArticleError("Webpage host must resolve only to public IP addresses; local/private addresses are blocked.")


class PublicRedirectHandler(HTTPRedirectHandler):
    """Check every redirect destination before urllib follows it."""

    def redirect_request(self, request, file, code, message, headers, new_url):
        _require_public_dns(new_url)
        return super().redirect_request(request, file, code, message, headers, new_url)


def read_url(url: str, limit: int, expected: str | None = None) -> tuple[bytes, str, str]:
    _require_public_dns(url)
    request = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml,*/*;q=0.8"})
    opener = build_opener(PublicRedirectHandler())
    try:
        with opener.open(request, timeout=20) as response:
            final_url = response.geturl()
            _require_public_dns(final_url)
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


def _json_ld_articles(soup: BeautifulSoup) -> list[dict]:
    articles = []
    for script in soup.select("script[type='application/ld+json']"):
        try:
            value = json.loads(script.string or script.get_text())
        except (TypeError, ValueError):
            continue
        items = value if isinstance(value, list) else value.get("@graph", []) if isinstance(value, dict) else []
        if isinstance(value, dict) and not items:
            items = [value]
        for item in items:
            if not isinstance(item, dict):
                continue
            types = item.get("@type", [])
            types = types if isinstance(types, list) else [types]
            if any("Article" in str(item_type) for item_type in types):
                articles.append(item)
    return articles


def json_ld_metadata(soup: BeautifulSoup) -> tuple[str, str]:
    """Read common Article JSON-LD fields without trusting it as article content."""
    for item in _json_ld_articles(soup):
        author = item.get("author", "")
        if isinstance(author, list):
            author = author[0] if author else ""
        if isinstance(author, dict):
            author = author.get("name", "")
        return clean_text(str(item.get("headline") or item.get("name") or "")), clean_text(str(author))
    return "", ""


def _normalize_date(value: str | None) -> str:
    value = clean_text(value)
    if not value:
        return ""
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.date().isoformat()
    except ValueError:
        try:
            return date.fromisoformat(value[:10]).isoformat()
        except ValueError:
            return ""


def article_published_date(soup: BeautifulSoup) -> str:
    """Return an evidence-backed publication date, never a date guessed from prose."""
    articles = _json_ld_articles(soup)
    for key in ("datePublished", "dateCreated"):
        for item in articles:
            value = _normalize_date(str(item.get(key) or ""))
            if value:
                return value
    for key in ("article:published_time", "datePublished", "date"):
        value = _normalize_date(first_meta(soup, key))
        if value:
            return value
    for tag in soup.select("time[itemprop='datePublished'][datetime], time[property='article:published_time'][datetime], time[class*='published'][datetime], time[id*='published'][datetime]"):
        value = _normalize_date(str(tag.get("datetime", "")))
        if value:
            return value
    return ""


CONTENT_SELECTORS = (
    "article", "[itemprop='articleBody']", "[role='main']", "main",
    ".article-body", ".article-content", ".post-content", ".entry-content",
)
END_MARKER_SELECTOR = (
    "[class*='related'], [id*='related'], [class*='recommended'], [id*='recommended'], "
    "[class*='read-next'], [id*='read-next'], [class*='readnext'], [id*='readnext'], "
    "[class*='comment'], [id*='comment'], [class*='tag-list'], [id*='tag-list']"
)


def trim_article_end(root: Tag) -> None:
    """Trim explicitly marked widgets; a heading alone is not exclusion evidence."""
    candidates = list(root.select(END_MARKER_SELECTOR))
    if not candidates:
        return
    marker = next(tag for tag in root.find_all(True) if tag in candidates)
    parent = marker.parent
    if not isinstance(parent, Tag):
        marker.decompose()
        return
    for node in [marker, *marker.find_next_siblings()]:
        node.decompose()


def _content_score(root: Tag) -> int:
    text_length = len(clean_text(root.get_text(" ", strip=True)))
    paragraphs = len(root.find_all("p"))
    headings = len(root.find_all(["h1", "h2", "h3", "h4"]))
    noise = len(root.select("nav, footer, aside, [class*='recommend'], [class*='newsletter'], [class*='subscribe']"))
    return text_length + paragraphs * 80 + headings * 40 - noise * 250


def choose_article_root(soup: BeautifulSoup) -> Tag:
    candidates = []
    for selector in CONTENT_SELECTORS:
        candidates.extend(soup.select(selector))
    candidates = list(dict.fromkeys(candidate for candidate in candidates if isinstance(candidate, Tag)))
    if not candidates and isinstance(soup.body, Tag):
        candidates = [soup.body]
    if not candidates:
        raise ArticleError("The page has no readable article body.")
    return max(candidates, key=_content_score)

def make_absolute(url: str, base_url: str) -> str | None:
    absolute = urljoin(base_url, url)
    return absolute if urlparse(absolute).scheme in {"http", "https"} else None


def remove_noise(root: Tag, author: str, *, select_content: bool = True) -> None:
    for comment in root.find_all(string=lambda value: isinstance(value, Comment)):
        comment.extract()
    selector = "script, style, noscript, svg, iframe, form, button"
    if select_content:
        selector += ", nav, footer, aside, [class*='recommend'], [id*='recommend'], [data-testid*='recommend'], time, [class*='byline'], [id*='byline'], [class*='author'], [id*='author'], [class*='published'], [id*='published'], [class*='reading-time'], [id*='reading-time'], [class*='read-time'], [id*='read-time']"
    for tag in root.select(selector):
        tag.decompose()
    if not select_content:
        return
    author = clean_text(author).casefold()
    for tag in list(root.find_all(["p", "div", "span", "header"])):
        if not tag.find("a"):
            continue
        text = clean_text(tag.get_text(" ", strip=True)).casefold()
        if text in {author, f"by {author}", f"written by {author}", f"por {author}"}:
            tag.decompose()


def latex_to_mathml(latex: str, display: bool = False) -> str:
    markup = latex_to_mathml_markup(latex.strip())
    return markup.replace('display="inline"', f'display="{"block" if display else "inline"}"', 1)


def _replace_with_math(node: Tag, latex: str, display: bool = False) -> None:
    fragment = BeautifulSoup(latex_to_mathml(latex, display), "html.parser")
    node.replace_with(fragment.math)


def _is_math_renderer(tag: Tag) -> bool:
    if tag.name == "mjx-container":
        return True
    classes = tag.get("class", [])
    return any(re.match(r"^(?:katex(?:-|$)|mathjax(?:[_-]|$)|mjx-)", name, re.IGNORECASE) for name in classes)


def extract_math(root: Tag) -> list[str]:
    failed = 0
    for tag in list(root.find_all(True))[::-1]:
        if _is_math_renderer(tag):
            semantic_math = tag.find("math")
            if semantic_math:
                tag.replace_with(semantic_math)

    for tag in list(root.find_all(["script", "span", "div", "mjx-container"])[::-1]):
        classes = " ".join(tag.get("class", [])) if tag.name != "script" else ""
        annotation = tag.find("annotation", attrs={"encoding": "application/x-tex"})
        latex = tag.get("data-latex") or tag.get("data-tex") or (annotation.get_text() if annotation else None)
        if tag.name == "script" and "math/tex" in tag.get("type", ""):
            latex = tag.get_text()
        if latex:
            script_display = (
                tag.name == "script"
                and re.search(r"mode\s*=\s*display", tag.get("type", ""), re.IGNORECASE)
            )
            display = "display" in classes or "display" in tag.get("data-mode", "") or script_display
            try:
                _replace_with_math(tag, latex, display)
            except Exception:
                tag.replace_with(latex)
                failed += 1

    pattern = re.compile(r"(\\\[(.+?)\\\]|\\\((.+?)\\\)|\$\$(.+?)\$\$|\$(?!\s)(.+?)(?<!\s)\$)", re.DOTALL)
    for text_node in list(root.find_all(string=True)):
        if text_node.find_parent(["math", "script", "style"]) or not pattern.search(str(text_node)):
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


def deduplicate_content(root: Tag, title: str, *, deduplicate_blocks: bool = True) -> None:
    """Remove the copied title; optionally remove repeated rendered blocks."""
    seen: set[tuple[str, str]] = set()
    block_tags = ["h1", "h2", "h3", "h4", "p", "blockquote", "pre", "li", "figcaption"]
    for tag in list(root.find_all(block_tags)):
        text = clean_text(tag.get_text(" ", strip=True))
        if tag.name == "h1" and text == clean_text(title):
            tag.decompose()
            continue
        if not text:
            continue
        key = (tag.name, text)
        if deduplicate_blocks and key in seen:
            tag.decompose()
        else:
            seen.add(key)


def sanitize_article(root: Tag, base_url: str, *, preserve_review_markers: bool = False) -> None:
    for tag in list(root.find_all(True)):
        review_marker = tag.get("data-article-to-kindle-excluded") if preserve_review_markers else None
        if tag.name not in ALLOWED_TAGS:
            if review_marker:
                for child in list(tag.children):
                    if isinstance(child, NavigableString) and not isinstance(child, Comment) and str(child).strip():
                        wrapper = BeautifulSoup("", "html.parser").new_tag("span")
                        wrapper["data-article-to-kindle-excluded"] = "true"
                        child.wrap(wrapper)
                for descendant in tag.find_all(True):
                    descendant["data-article-to-kindle-excluded"] = "true"
            tag.unwrap()
            continue
        if tag.name == "a":
            href = make_absolute(str(tag.get("href", "")), base_url)
            tag.attrs = {"href": href} if href else {}
        elif tag.name == "img":
            source = tag.get("src") or tag.get("data-src") or tag.get("data-article-to-kindle-src")
            source = str(source) if source and str(source).startswith("data:image/") else make_absolute(str(source), base_url) if source else None
            if source:
                tag.attrs = {"src": source, "alt": clean_text(str(tag.get("alt", "")))}
            else:
                tag.decompose()
        elif tag.name in MATHML_TAGS:
            tag.attrs = {key: value for key, value in tag.attrs.items() if key.lower() in MATHML_ATTRIBUTES}
            if tag.name == "math" and not tag.get("xmlns"):
                tag["xmlns"] = MATHML_NAMESPACE
        else:
            tag.attrs = {}
        if review_marker:
            tag["data-article-to-kindle-excluded"] = "true"


def normalize_image(data: bytes, media_type: str) -> tuple[bytes, str, str]:
    """Convert formats with weak Kindle support to a broadly supported JPEG."""
    if media_type != "image/webp":
        return data, media_type, IMAGE_EXTENSIONS[media_type]
    with Image.open(BytesIO(data)) as image:
        if image.mode in {"RGBA", "LA"} or "transparency" in image.info:
            rgba = image.convert("RGBA")
            background = Image.new("RGB", rgba.size, "white")
            background.paste(rgba, mask=rgba.getchannel("A"))
            image = background
        else:
            image = image.convert("RGB")
        output = BytesIO()
        image.save(output, format="JPEG", quality=90, optimize=True)
    return output.getvalue(), "image/jpeg", ".jpg"


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
            else:
                data, media_type, final_url = read_url(source, MAX_IMAGE_BYTES, "image/")
                if urlparse(final_url).scheme not in {"http", "https"}:
                    raise ArticleError("Image redirected to an unsupported URL.")
            if media_type not in IMAGE_EXTENSIONS:
                raise ArticleError("Unsupported image type.")
            data, media_type, extension = normalize_image(data, media_type)
            if len(data) > MAX_IMAGE_BYTES or total_bytes + len(data) > MAX_TOTAL_IMAGE_BYTES:
                raise ArticleError("Article image limit exceeded.")
            asset = ImageAsset(f"images/image-{len(assets) + 1}{extension}", data, media_type)
            assets.append(asset)
            total_bytes += len(data)
            fetched[source] = asset
            tag["src"] = asset.href
        except (ArticleError, ValueError, TypeError):
            tag.decompose()
            failed += 1
    return assets, failed


def analyze_article_html(page_html: str, source_url: str, *, title: str | None = None,
                         author: str | None = None, include_excluded: bool = False) -> dict:
    """Select and sanitize an article snapshot without fetching its images."""
    if len(page_html.encode("utf-8")) > MAX_HTML_BYTES:
        raise ArticleError("Article HTML exceeds 10 MiB.")
    soup = BeautifulSoup(page_html, "html.parser")
    json_title, json_author = json_ld_metadata(soup)
    published_date = article_published_date(soup)
    model_selection = classify_article_blocks(soup, source_url, include_excluded=include_excluded)
    model_active = model_selection is not None
    if model_selection:
        root, warnings = model_selection
    else:
        root = select_article_root(soup, source_url) or choose_article_root(soup)
        warnings = []
    resolved_title = (title or "").strip() or json_title or clean_text(first_meta(soup, "og:title", "twitter:title")) or clean_text(root.find("h1").get_text(" ", strip=True) if root.find("h1") else "") or clean_text(soup.title.get_text(" ", strip=True) if soup.title else "")
    if not resolved_title:
        raise ArticleError("Could not find an article title.")
    resolved_author = (author or "").strip() or json_author or clean_text(first_meta(soup, "author", "article:author")) or "Unknown author"
    if not (include_excluded and model_active):
        trim_article_end(root)
    warnings.extend(extract_math(root))
    review_mode = include_excluded and model_active
    remove_noise(root, resolved_author, select_content=not review_mode)
    sanitize_article(root, source_url, preserve_review_markers=review_mode)
    deduplicate_content(root, resolved_title, deduplicate_blocks=not review_mode)
    if len(clean_text(root.get_text(" ", strip=True))) < 100:
        raise ArticleError("Could not find enough readable article content (it may be paywalled).")
    return {
        "title": resolved_title,
        "author": resolved_author,
        "publishedDate": published_date,
        "sourceUrl": source_url,
        "html": f"<article>{''.join(str(child) for child in root.contents)}</article>",
        "warnings": warnings,
    }


def extract_article(page_html: str, source_url: str, *, select_content: bool = True) -> Article:
    """Select an Article Page, or finalize an already selected Article Capture.

    Disabling selection never disables sanitization or bounded image processing.
    """
    if select_content:
        analysis = analyze_article_html(page_html, source_url)
        soup = BeautifulSoup(analysis["html"], "html.parser")
        root = soup.find("article") or soup.body or soup
        title, author = analysis["title"], analysis["author"]
        published_date = analysis["publishedDate"]
        warnings = list(analysis["warnings"])
    else:
        soup = BeautifulSoup(page_html, "html.parser")
        root = soup.find("article") or soup.body or choose_article_root(soup)
        json_title, json_author = json_ld_metadata(soup)
        title = json_title or clean_text(first_meta(soup, "og:title", "twitter:title")) or clean_text(root.find("h1").get_text(" ", strip=True) if root.find("h1") else "") or clean_text(soup.title.get_text(" ", strip=True) if soup.title else "")
        author = json_author or clean_text(first_meta(soup, "author", "article:author")) or "Unknown author"
        published_date = article_published_date(soup)
        warnings = []
    if not title:
        raise ArticleError("Could not find an article title.")
    warnings.extend(extract_math(root))
    remove_noise(root, author, select_content=False)
    sanitize_article(root, source_url)
    deduplicate_content(root, title, deduplicate_blocks=False)
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
    return Article(title, author, source_url, "".join(str(child) for child in root.contents), headings, images, warnings, published_date)


def slugify(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")[:80] or "article"
