"""Read a bounded, ordered URL list without duplicating exact submissions."""

from backend.errors import ArticleError
from cli.sources import read_input

MAX_BATCH_ARTICLES = 1000


def read_urls(path: str) -> list[str]:
    urls = []
    seen = set()
    for line in read_input(path).splitlines():
        url = line.strip()
        if not url or url.startswith("#") or url in seen:
            continue
        if len(url) > 8192:
            raise ArticleError("Batch URL exceeds the 8192-character limit.")
        seen.add(url)
        urls.append(url)
        if len(urls) > MAX_BATCH_ARTICLES:
            raise ArticleError(f"Batch input exceeds {MAX_BATCH_ARTICLES} unique articles.")
    if not urls:
        raise ArticleError("Batch input contains no article URLs.")
    return urls
