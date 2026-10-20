from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass(slots=True)
class SourceAsset:
    url: str
    type: str = "image"


@dataclass(slots=True)
class SourceArticle:
    source: str
    account_id: str
    article_id: str
    original_url: str
    title: str
    published_at: datetime
    html_content: str
    updated_at: datetime | None = None
    cover_url: str | None = None
    author: str | None = None
    summary: str | None = None
    assets: list[SourceAsset] = field(default_factory=list)
    raw_payload: dict = field(default_factory=dict)

