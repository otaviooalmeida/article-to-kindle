"""Data exchanged between extraction, EPUB, and delivery modules."""

from dataclasses import dataclass, field


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
    warnings: list[str] = field(default_factory=list)
