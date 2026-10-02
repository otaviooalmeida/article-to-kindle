"""Apply reader preferences before the shared extraction pipeline."""

from bs4 import BeautifulSoup

from .config import MAX_CAPTURE_BYTES
from .errors import ArticleError
from .extractor import clean_text, first_meta, json_ld_metadata, require_article_url


def prepare_html(html: str, source_url: str, *, title: str | None = None,
                 author: str | None = None, include_images=True, include_links=True) -> str:
    """Keep opt-out assets from being fetched, and provide explicit metadata."""
    require_article_url(source_url)
    if len(html.encode("utf-8")) > MAX_CAPTURE_BYTES:
        raise ArticleError("Article HTML exceeds 10 MiB.")
    if title is not None and not title.strip():
        raise ArticleError("Reading Copy title must not be empty.")
    if title is not None and any(char in title for char in "\r\n"):
        raise ArticleError("Reading Copy title must be single-line.")
    if title is None and author is None and include_images and include_links:
        return html
    soup = BeautifulSoup(html, "html.parser")
    if not include_images:
        for image in soup.find_all("img"):
            image.decompose()
    if not include_links:
        for link in soup.find_all("a"):
            link.unwrap()
    if title is not None or author is not None:
        json_title, json_author = json_ld_metadata(soup)
        original_title = json_title or first_meta(soup, "og:title", "twitter:title")
        first_heading = soup.find("h1")
        if not original_title and first_heading:
            original_title = clean_text(first_heading.get_text(" ", strip=True))
        if title is not None:
            for heading in list(soup.find_all("h1")):
                if clean_text(heading.get_text(" ", strip=True)) == clean_text(original_title):
                    heading.decompose()
        resolved_title = title.strip() if title is not None else original_title
        resolved_author = (author.strip() or "Unknown author") if author is not None else json_author or first_meta(soup, "author", "article:author")
        for script in soup.select("script[type='application/ld+json']"):
            script.decompose()
        for name, value in (("og:title", resolved_title), ("author", resolved_author)):
            if value:
                for meta in list(soup.find_all("meta")):
                    if meta.get("property") == name or meta.get("name") == name:
                        meta.decompose()
                soup.insert(0, soup.new_tag("meta", attrs={"property" if name == "og:title" else "name": name, "content": value}))
    return str(soup)
