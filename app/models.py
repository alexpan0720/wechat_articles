from __future__ import annotations

import enum
import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def new_id() -> str:
    return str(uuid.uuid4())


class ArticleStatus(str, enum.Enum):
    processing = "processing"
    published = "published"
    failed = "failed"
    withdrawn = "withdrawn"


class RunResult(str, enum.Enum):
    running = "running"
    succeeded = "succeeded"
    partial = "partial"
    failed = "failed"


class SourceAccount(Base):
    __tablename__ = "source_accounts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    account_name: Mapped[str] = mapped_column(String(200))
    account_identifier: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    articles: Mapped[list[Article]] = relationship(back_populates="source_account")


class Article(Base):
    __tablename__ = "articles"
    __table_args__ = (
        UniqueConstraint("source_account_id", "source_article_id", name="uq_source_article"),
        Index("ix_articles_status_published", "status", "published_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    source_account_id: Mapped[str] = mapped_column(ForeignKey("source_accounts.id"), index=True)
    source_article_id: Mapped[str] = mapped_column(String(300))
    title: Mapped[str] = mapped_column(String(500))
    slug: Mapped[str] = mapped_column(String(550), unique=True, index=True)
    summary: Mapped[str | None] = mapped_column(Text)
    author: Mapped[str | None] = mapped_column(String(200))
    cover_url: Mapped[str | None] = mapped_column(Text)
    source_url: Mapped[str] = mapped_column(Text)
    content_html: Mapped[str] = mapped_column(Text, default="")
    raw_html: Mapped[str] = mapped_column(Text, default="")
    content_hash: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(32), default=ArticleStatus.processing.value, index=True)
    failure_reason: Mapped[str | None] = mapped_column(Text)
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    source_account: Mapped[SourceAccount] = relationship(back_populates="articles")
    versions: Mapped[list[ArticleVersion]] = relationship(
        back_populates="article", cascade="all, delete-orphan"
    )
    assets: Mapped[list[ArticleAsset]] = relationship(
        back_populates="article", cascade="all, delete-orphan"
    )


class ArticleVersion(Base):
    __tablename__ = "article_versions"
    __table_args__ = (UniqueConstraint("article_id", "version", name="uq_article_version"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    article_id: Mapped[str] = mapped_column(ForeignKey("articles.id"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    raw_html: Mapped[str] = mapped_column(Text)
    content_html: Mapped[str] = mapped_column(Text)
    content_hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    article: Mapped[Article] = relationship(back_populates="versions")


class ArticleAsset(Base):
    __tablename__ = "article_assets"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    article_id: Mapped[str] = mapped_column(ForeignKey("articles.id"), index=True)
    source_url: Mapped[str] = mapped_column(Text)
    storage_path: Mapped[str | None] = mapped_column(Text)
    media_type: Mapped[str] = mapped_column(String(100), default="image")
    status: Mapped[str] = mapped_column(String(32), default="pending")
    checksum: Mapped[str | None] = mapped_column(String(64))
    error: Mapped[str | None] = mapped_column(Text)

    article: Mapped[Article] = relationship(back_populates="assets")


class SyncRun(Base):
    __tablename__ = "sync_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    trigger: Mapped[str] = mapped_column(String(50), default="manual")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    result: Mapped[str] = mapped_column(String(32), default=RunResult.running.value)
    success_count: Mapped[int] = mapped_column(Integer, default=0)
    skipped_count: Mapped[int] = mapped_column(Integer, default=0)
    failed_count: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text)

    items: Mapped[list[SyncItem]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )


class SyncItem(Base):
    __tablename__ = "sync_items"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    run_id: Mapped[str] = mapped_column(ForeignKey("sync_runs.id"), index=True)
    source_article_id: Mapped[str] = mapped_column(String(300), index=True)
    article_id: Mapped[str | None] = mapped_column(ForeignKey("articles.id"), nullable=True)
    status: Mapped[str] = mapped_column(String(32))
    error_code: Mapped[str | None] = mapped_column(String(100))
    message: Mapped[str | None] = mapped_column(Text)
    attempts: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    run: Mapped[SyncRun] = relationship(back_populates="items")


class AdminProfile(Base):
    __tablename__ = "admin_profiles"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    username: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(500))
    role: Mapped[str] = mapped_column(String(50), default="admin")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

