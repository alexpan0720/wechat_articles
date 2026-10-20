from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from app.config import Settings
from app.database import Base
from app.models import Article, ArticleStatus, ArticleVersion, SyncRun
from app.sync.adapters import ArticleSourceAdapter
from app.sync.assets import AssetResult
from app.sync.service import SyncService
from app.sync.types import SourceArticle


class StubAdapter(ArticleSourceAdapter):
    def list_articles(self, lookback_days: int = 30):
        return [SourceArticle(
            source="wechat", account_id="account-1", article_id="article-1",
            original_url="https://example.com/article-1", title="测试文章",
            published_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            html_content='<section style="color:#333"><p>完整正文</p></section>',
        )]


def test_sync_is_idempotent_and_publishes(tmp_path: Path):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    settings = Settings(
        database_url="sqlite:///:memory:", storage_dir=tmp_path, auto_publish=True,
        sync_feed_path=tmp_path / "unused.json",
    )
    with session_factory() as db:
        first = SyncService(db, StubAdapter(), settings).run()
        second = SyncService(db, StubAdapter(), settings).run()
        assert (first.success, first.skipped, first.failed) == (1, 0, 0)
        assert (second.success, second.skipped, second.failed) == (0, 1, 0)
        assert db.scalar(select(func.count()).select_from(Article)) == 1
        article = db.scalar(select(Article))
        assert article.status == ArticleStatus.published.value
        assert "完整正文" in article.content_html
        assert db.scalar(select(func.count()).select_from(ArticleVersion)) == 1
        assert db.scalar(select(func.count()).select_from(SyncRun)) == 2


def test_failed_update_preserves_existing_published_version(tmp_path: Path, monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    settings = Settings(storage_dir=tmp_path, auto_publish=True)
    adapter = StubAdapter()
    with session_factory() as db:
        SyncService(db, adapter, settings).run()
        original = db.scalar(select(Article))
        original_html = original.content_html

        def changed_articles(lookback_days: int = 30):
            rows = StubAdapter().list_articles(lookback_days)
            rows[0].html_content = '<p>新正文<img src="https://invalid.example/broken.jpg"></p>'
            return rows

        monkeypatch.setattr(adapter, "list_articles", changed_articles)
        monkeypatch.setattr(
            "app.sync.service.migrate_article_images",
            lambda *args, **kwargs: (
                args[0],
                [AssetResult("https://invalid.example/broken.jpg", None, None, None, None, "404")],
            ),
        )
        summary = SyncService(db, adapter, settings).run()
        db.refresh(original)
        assert summary.failed == 1
        assert original.status == ArticleStatus.published.value
        assert original.content_html == original_html

