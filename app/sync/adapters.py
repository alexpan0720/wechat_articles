from __future__ import annotations

import json
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

from app.sync.types import SourceArticle, SourceAsset


def _parse_datetime(value: str | None) -> datetime:
    if not value:
        return datetime.now(timezone.utc)
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def normalize_article(payload: dict[str, Any]) -> SourceArticle:
    required = ["accountId", "articleId", "originalUrl", "title", "htmlContent"]
    missing = [key for key in required if not payload.get(key)]
    if missing:
        raise ValueError(f"source article is missing required fields: {', '.join(missing)}")
    return SourceArticle(
        source=str(payload.get("source", "wechat")),
        account_id=str(payload["accountId"]),
        article_id=str(payload["articleId"]),
        original_url=str(payload["originalUrl"]),
        title=str(payload["title"]),
        published_at=_parse_datetime(payload.get("publishedAt")),
        updated_at=_parse_datetime(payload["updatedAt"]) if payload.get("updatedAt") else None,
        cover_url=payload.get("coverUrl"),
        author=payload.get("author"),
        summary=payload.get("summary"),
        html_content=str(payload["htmlContent"]),
        assets=[SourceAsset(url=str(item["url"]), type=str(item.get("type", "image")))
                for item in payload.get("assets", []) if item.get("url")],
        raw_payload=payload,
    )


class ArticleSourceAdapter(ABC):
    @abstractmethod
    def list_articles(self, lookback_days: int = 30) -> list[SourceArticle]:
        raise NotImplementedError

    def check_health(self) -> bool:
        return True


class FileArticleSourceAdapter(ArticleSourceAdapter):
    """Deterministic adapter for demos, migrations, fixtures and contract testing."""

    def __init__(self, path: Path):
        self.path = path

    def list_articles(self, lookback_days: int = 30) -> list[SourceArticle]:
        del lookback_days
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        rows = payload.get("articles", payload) if isinstance(payload, dict) else payload
        if not isinstance(rows, list):
            raise ValueError("feed must be a JSON list or an object containing an articles list")
        return [normalize_article(item) for item in rows]

    def check_health(self) -> bool:
        return self.path.is_file()


class HttpArticleSourceAdapter(ArticleSourceAdapter):
    """Reference HTTP contract: GET /articles returns normalized SourceArticle JSON."""

    def __init__(self, base_url: str, token: str | None = None):
        self.base_url = base_url.rstrip("/")
        self.headers = {"Authorization": f"Bearer {token}"} if token else {}

    def list_articles(self, lookback_days: int = 30) -> list[SourceArticle]:
        with httpx.Client(timeout=30, follow_redirects=True) as client:
            response = client.get(
                f"{self.base_url}/articles",
                headers=self.headers,
                params={"lookback_days": lookback_days},
            )
            response.raise_for_status()
            payload = response.json()
        rows = payload.get("articles", payload) if isinstance(payload, dict) else payload
        return [normalize_article(item) for item in rows]

    def check_health(self) -> bool:
        try:
            with httpx.Client(timeout=10) as client:
                response = client.get(f"{self.base_url}/health", headers=self.headers)
            return response.is_success
        except httpx.HTTPError:
            return False

