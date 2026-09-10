"""Authenticated loopback API used by the Chrome extension."""

import hmac
import os
import sys
import tempfile
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field

from .config import ALLOWED_ORIGIN, API_TOKEN, MAX_CAPTURE_BYTES, MAX_EPUB_BYTES
from .delivery import send_to_kindle
from .epub import write_epub
from .errors import ArticleError
from .extractor import extract_article, require_article_url, slugify


def error(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse({"code": code, "message": message}, status_code=status)


class OriginMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        headers = {key.decode(): value.decode() for key, value in scope["headers"]}
        origin = headers.get("origin", "")
        declared_origin = headers.get("x-article-to-kindle-origin", "")
        request_origin = origin or declared_origin
        allowed_origin = os.environ.get(ALLOWED_ORIGIN, "")
        if (origin and declared_origin and not hmac.compare_digest(origin, declared_origin)) or not allowed_origin or not hmac.compare_digest(request_origin, allowed_origin):
            print(f"Rejected extension origin: received={request_origin or '<missing>'!r} expected={allowed_origin or '<missing>'!r}", file=sys.stderr, flush=True)
            return await error(403, "origin_rejected", "Extension origin is not allowed.")(scope, receive, send)
        try:
            content_length = int(headers.get("content-length", "0") or 0)
        except ValueError:
            return await error(400, "invalid_capture", "Invalid Content-Length header.")(scope, receive, send)
        if content_length > MAX_CAPTURE_BYTES + 65536:
            response = error(413, "size_limit", "Article capture exceeds 10 MiB.")
            response.headers.update(self.headers(request_origin))
            return await response(scope, receive, send)
        if scope["method"] == "OPTIONS":
            return await Response(status_code=204, headers=self.headers(request_origin))(scope, receive, send)

        async def send_with_cors(message):
            if message["type"] == "http.response.start":
                message["headers"].extend((key.encode(), value.encode()) for key, value in self.headers(request_origin).items())
            await send(message)
        await self.app(scope, receive, send_with_cors)

    @staticmethod
    def headers(origin):
        return {"Access-Control-Allow-Origin": origin, "Access-Control-Allow-Headers": "Authorization, Content-Type, X-Article-To-Kindle-Origin", "Access-Control-Allow-Methods": "GET, POST, OPTIONS", "Access-Control-Expose-Headers": "X-Article-Warnings"}


app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
app.add_middleware(OriginMiddleware)


@app.exception_handler(HTTPException)
async def http_error(_request: Request, exception: HTTPException):
    code = {400: "invalid_capture", 401: "invalid_token", 413: "size_limit", 422: "conversion_failed", 502: "smtp_failed"}.get(exception.status_code, "request_failed")
    return error(exception.status_code, code, str(exception.detail))


@app.exception_handler(RequestValidationError)
async def invalid_request(_request: Request, _exception: RequestValidationError):
    return error(400, "invalid_capture", "Article capture is invalid.")


class ArticleCapture(BaseModel):
    title: str = Field(min_length=1)
    author: str = Field(min_length=1)
    sourceUrl: str = Field(min_length=1)
    html: str = Field(min_length=1)


async def authenticate(authorization: str = Header(default="")) -> None:
    expected = f"Bearer {os.environ.get(API_TOKEN, '')}"
    if not os.environ.get(API_TOKEN) or not hmac.compare_digest(authorization, expected):
        raise HTTPException(401, detail="Invalid bearer token.")


@app.get("/health", dependencies=[Depends(authenticate)])
async def health() -> dict[str, str]:
    return {"status": "ok"}


def captured_article(capture: ArticleCapture):
    if len(capture.html.encode()) > MAX_CAPTURE_BYTES:
        raise HTTPException(413, detail="Article capture exceeds 10 MiB.")
    try:
        require_article_url(capture.sourceUrl)
        article = extract_article(capture.html, capture.sourceUrl)
    except ArticleError as exception:
        raise HTTPException(400, detail=str(exception)) from exception
    article.title, article.author = capture.title.strip(), capture.author.strip()
    return article


def warning_headers(article) -> dict[str, str]:
    return {"X-Article-Warnings": "; ".join(article.warnings)}


def write_article_epub(article, output: Path) -> None:
    try:
        write_epub(article, output)
    except (OSError, ValueError) as exception:
        raise HTTPException(422, detail="EPUB conversion failed.") from exception


@app.post("/epub", dependencies=[Depends(authenticate)])
async def create_epub(capture: ArticleCapture):
    article = captured_article(capture)
    with tempfile.TemporaryDirectory() as directory:
        output = Path(directory) / "article.epub"
        write_article_epub(article, output)
        if output.stat().st_size > MAX_EPUB_BYTES:
            raise HTTPException(413, detail="Generated EPUB exceeds 50 MiB.")
        content = output.read_bytes()
    return Response(content, media_type="application/epub+zip", headers={"Content-Disposition": f'attachment; filename="{slugify(article.title)}.epub"', **warning_headers(article)})


@app.post("/kindle", dependencies=[Depends(authenticate)])
async def submit_to_kindle(capture: ArticleCapture):
    article = captured_article(capture)
    with tempfile.TemporaryDirectory() as directory:
        output = Path(directory) / f"{article.title}.epub"
        write_article_epub(article, output)
        if output.stat().st_size > MAX_EPUB_BYTES:
            raise HTTPException(413, detail="Generated EPUB exceeds 50 MiB.")
        try:
            send_to_kindle(article, output)
        except ArticleError as exception:
            raise HTTPException(502, detail="Kindle submission failed.") from exception
    return {"message": "Sent to Kindle email; Amazon delivery is pending.", "warnings": article.warnings}
