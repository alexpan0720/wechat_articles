from __future__ import annotations

from app.config import Settings
from app.sync.adapters import ArticleSourceAdapter, FileArticleSourceAdapter, HttpArticleSourceAdapter


def build_adapter(settings: Settings) -> ArticleSourceAdapter:
    if settings.sync_adapter == "file":
        return FileArticleSourceAdapter(settings.sync_feed_path)
    if settings.sync_adapter == "http":
        if not settings.sync_api_base_url:
            raise ValueError("SYNC_API_BASE_URL is required when SYNC_ADAPTER=http")
        return HttpArticleSourceAdapter(settings.sync_api_base_url, settings.sync_api_token)
    raise ValueError(f"unsupported sync adapter: {settings.sync_adapter}")

