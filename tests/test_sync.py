from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from app.config import Settings
from app.database import Base
from app.models import Article, ArticleStatus, ArticleVersion, SyncRun
from app.sync.adapters import ArticleSourceAdapter
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

