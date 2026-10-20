from __future__ import annotations

import logging
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import Settings
from app.content import content_hash, sanitize_article_html, slugify, text_excerpt
from app.models import (
    Article, ArticleAsset, ArticleStatus, ArticleVersion, RunResult, SourceAccount, SyncItem,
    SyncRun, new_id, utcnow,
)
from app.sync.adapters import ArticleSourceAdapter
from app.sync.assets import migrate_article_images
from app.sync.types import SourceArticle

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class SyncSummary:
    run_id: str
    success: int
    skipped: int
    failed: int


class SyncService:
    def __init__(self, db: Session, adapter: ArticleSourceAdapter, settings: Settings):
        self.db = db
        self.adapter = adapter
        self.settings = settings

    def run(self, trigger: str = "manual") -> SyncSummary:
        run = SyncRun(trigger=trigger)
        self.db.add(run)
        self.db.commit()
        try:
            source_articles = self.adapter.list_articles(self.settings.sync_lookback_days)
        except Exception as exc:
            run.result = RunResult.failed.value
            run.error = str(exc)
            run.ended_at = utcnow()
            self.db.commit()
            raise

        for source in source_articles:
            try:
                outcome, article_id = self._sync_one(source)
                if outcome == "skipped":
                    run.skipped_count += 1
                else:
                    run.success_count += 1
                self.db.add(SyncItem(
                    run_id=run.id, source_article_id=source.article_id,
                    article_id=article_id, status=outcome,
                ))
                self.db.commit()
            except Exception as exc:
                logger.exception("Article sync failed: %s", source.article_id)
                self.db.rollback()
                run = self.db.get(SyncRun, run.id)
                run.failed_count += 1
                self.db.add(SyncItem(
                    run_id=run.id, source_article_id=source.article_id, status="failed",
                    error_code=type(exc).__name__, message=str(exc)[:2000],
                ))
                self.db.commit()

        run = self.db.get(SyncRun, run.id)
        run.ended_at = utcnow()
        run.result = (
            RunResult.succeeded.value if run.failed_count == 0
            else RunResult.failed.value if run.success_count == 0 and run.skipped_count == 0
            else RunResult.partial.value
        )
        self.db.commit()
        return SyncSummary(run.id, run.success_count, run.skipped_count, run.failed_count)

    def _sync_one(self, source: SourceArticle) -> tuple[str, str]:
        account = self.db.scalar(
            select(SourceAccount).where(SourceAccount.account_identifier == source.account_id)
        )
        if not account:
            account = SourceAccount(
                account_name=source.account_id, account_identifier=source.account_id, enabled=True
            )
            self.db.add(account)
            self.db.flush()
        if not account.enabled:
            raise ValueError("source account is disabled")

        digest = content_hash(source.html_content)
        article = self.db.scalar(select(Article).where(
            Article.source_account_id == account.id,
            Article.source_article_id == source.article_id,
        ))
        if article and article.content_hash == digest:
            return "skipped", article.id

        article_id = article.id if article else new_id()
        migrated_html, asset_results = migrate_article_images(
            source.html_content,
            article_id=article_id,
            storage_dir=self.settings.storage_dir,
            max_bytes=self.settings.max_asset_bytes,
            referer=source.original_url,
        )
        failures = [item for item in asset_results if item.error]
        cleaned_html = sanitize_article_html(migrated_html)
        if not cleaned_html.strip() or not text_excerpt(cleaned_html, 20).strip():
            raise ValueError("article body is empty after sanitization")

        if not article:
            candidate = slugify(source.title, fallback=source.article_id)
            if self.db.scalar(select(Article.id).where(Article.slug == candidate)):
                candidate = f"{candidate}-{digest[:8]}"
            article = Article(
                id=article_id,
                source_account_id=account.id,
                source_article_id=source.article_id,
                title=source.title.strip(),
                slug=candidate,
                source_url=source.original_url,
                content_hash=digest,
                published_at=source.published_at,
            )
            self.db.add(article)
            self.db.flush()

        article.title = source.title.strip()
        article.summary = source.summary or text_excerpt(cleaned_html)
        article.author = source.author
        article.cover_url = source.cover_url
        article.source_url = source.original_url
        article.raw_html = source.html_content
        article.content_html = cleaned_html
        article.content_hash = digest
        article.failure_reason = "; ".join(item.error or "" for item in failures) or None
        article.status = (
            ArticleStatus.failed.value if failures
            else ArticleStatus.published.value if self.settings.auto_publish
            else ArticleStatus.processing.value
        )

        version = (self.db.scalar(
            select(func.max(ArticleVersion.version)).where(ArticleVersion.article_id == article.id)
        ) or 0) + 1
        self.db.add(ArticleVersion(
            article_id=article.id, version=version, raw_html=source.html_content,
            content_html=cleaned_html, content_hash=digest,
        ))
        for item in asset_results:
            self.db.add(ArticleAsset(
                article_id=article.id, source_url=item.source_url,
                storage_path=item.storage_path, media_type=item.media_type or "image",
                status="ready" if not item.error else "failed",
                checksum=item.checksum, error=item.error,
            ))
        self.db.flush()
        return "published" if article.status == ArticleStatus.published.value else article.status, article.id

