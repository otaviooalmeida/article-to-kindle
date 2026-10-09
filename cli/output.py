"""One structured result on stdout; human progress and warnings on stderr."""

import json
import sys
from dataclasses import dataclass, field

from backend.errors import ArticleError


class UsageError(ArticleError):
    def __init__(self, message: str, usage: str):
        super().__init__(message)
        self.usage = usage


@dataclass
class Reporter:
    json_mode: bool = False
    result: dict = field(default_factory=lambda: {"schemaVersion": 1, "command": None, "status": "ok"})

    def progress(self, message: str) -> None:
        print(message, file=sys.stderr)

    def notice(self, message: str) -> None:
        if not self.json_mode:
            print(message)

    def article(self, article, output) -> None:
        self.result.update(title=article.title, author=article.author, sourceUrl=article.source_url,
                           publishedDate=article.published_date or None, images=len(article.images),
                           warnings=list(article.warnings), output=str(output), submission="not_requested")
        date_line = f"\nPublished: {article.published_date}" if article.published_date else ""
        self.notice(f"Title: {article.title}\nAuthor: {article.author}{date_line}\nImages: {len(article.images)}\nCreated: {output}")
        for warning in article.warnings:
            self.progress(f"warning: {warning}")

    def error(self, error: Exception, *, code="operation_failed") -> None:
        self.result.update(status="error", error={"code": code, "message": str(error)})
        if isinstance(error, UsageError) and not self.json_mode:
            print(error.usage, file=sys.stderr, end="")
        self.progress(f"error: {error}")

    def emit(self, exit_code: int) -> None:
        if self.json_mode:
            print(json.dumps({**self.result, "exitCode": exit_code}, ensure_ascii=False))
