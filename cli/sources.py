"""Bounded saved HTML and browser Article Capture inputs."""

import json
import re
import sys
from datetime import date
from pathlib import Path

from backend.config import MAX_CAPTURE_BYTES
from backend.errors import ArticleError


def read_input(path: str) -> str:
    limit = MAX_CAPTURE_BYTES + 65536
    if path == "-":
        stream = getattr(sys.stdin, "buffer", sys.stdin)
        data = stream.read(limit + 1)
        data = data.encode("utf-8") if isinstance(data, str) else data
    else:
        with Path(path).expanduser().open("rb") as stream:
            data = stream.read(limit + 1)
    if len(data) > limit:
        raise ArticleError("Saved article input exceeds the 10 MiB capture limit plus metadata allowance.")
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise ArticleError("Saved article input must be UTF-8.") from error


def read_capture(path: str) -> dict[str, str]:
    try:
        capture = json.loads(read_input(path))
    except (ValueError, RecursionError) as error:
        raise ArticleError("Article Capture must be a JSON object with title, author, sourceUrl, and html.") from error
    fields = ("title", "author", "sourceUrl", "html")
    if not isinstance(capture, dict) or any(not isinstance(capture.get(name), str) or not capture[name].strip() for name in fields):
        raise ArticleError("Article Capture requires non-empty string title, author, sourceUrl, and html fields.")
    if len(capture["html"].encode("utf-8")) > MAX_CAPTURE_BYTES:
        raise ArticleError("Article Capture HTML exceeds 10 MiB.")
    published_date = capture.get("publishedDate")
    if published_date is not None:
        if not isinstance(published_date, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", published_date):
            raise ArticleError("Article Capture publishedDate must use YYYY-MM-DD format.")
        try:
            date.fromisoformat(published_date)
        except ValueError as error:
            raise ArticleError("Article Capture publishedDate is not a valid calendar date.") from error
    # Ignore all other fields, especially recipient/settings from untrusted input.
    result = {name: capture[name] for name in fields}
    if published_date:
        result["publishedDate"] = published_date
    return result
