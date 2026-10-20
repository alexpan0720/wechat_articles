import re
from datetime import datetime, timezone

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app.models import AdminProfile, Article, ArticleStatus, SourceAccount
from app.security import hash_password
from app.sync.types import SourceArticle


def test_public_website_and_article_rendering(monkeypatch):
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as db:
        account = SourceAccount(account_name="示例公众号", account_identifier="example")
        db.add(account)
        db.flush()
        db.add(Article(
            source_account_id=account.id,
            source_article_id="web-test-1",
            title="网站集成测试文章",
            slug="网站集成测试文章",
            summary="验证公开页面",
            source_url="https://example.com/source",
            content_html="<p>安全正文</p>",
            raw_html="<p>安全正文</p>",
            content_hash="a" * 64,
            status=ArticleStatus.published.value,
            published_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        ))
        db.add(AdminProfile(
            username="admin",
            password_hash=hash_password("Strong-Test-Password-2026"),
        ))
        db.commit()

    def override_db():
        with factory() as db:
            yield db

    app.dependency_overrides[get_db] = override_db
    try:
        with TestClient(app) as client:
            assert client.get("/").status_code == 200
            listing = client.get("/articles")
            assert listing.status_code == 200
            assert "网站集成测试文章" in listing.text
            detail = client.get("/articles/网站集成测试文章")
            assert detail.status_code == 200
            content = client.get("/articles/网站集成测试文章/content")
            assert content.status_code == 200
            assert "安全正文" in content.text
            assert "script-src" not in content.headers["content-security-policy"]
            assert client.get("/admin").status_code == 401

            login_page = client.get("/admin/login")
            login_csrf = re.search(
                r'name="csrf_token" value="([^"]+)"', login_page.text
            ).group(1)
            login = client.post(
                "/admin/login",
                data={
                    "username": "admin",
                    "password": "Strong-Test-Password-2026",
                    "csrf_token": login_csrf,
                },
                follow_redirects=False,
            )
            assert login.status_code == 303
            import_page = client.get("/admin/import")
            assert import_page.status_code == 200
            assert "下载并生成草稿" in import_page.text
            import_csrf = re.search(
                r'name="csrf_token" value="([^"]+)"', import_page.text
            ).group(1)

            source = SourceArticle(
                source="wechat",
                account_id="manual-account",
                article_id="manual-article",
                original_url="https://mp.weixin.qq.com/s/manual",
                title="后台链接导入文章",
                published_at=datetime(2026, 2, 1, tzinfo=timezone.utc),
                html_content="<section><p>导入正文</p></section>",
            )
            monkeypatch.setattr(
                "app.main.WechatUrlFetcher.fetch", lambda self, value: source
            )
            imported = client.post(
                "/admin/import",
                data={
                    "wechat_url": "https://mp.weixin.qq.com/s/manual",
                    "csrf_token": import_csrf,
                },
                follow_redirects=False,
            )
            assert imported.status_code == 303
            assert "imported=ready" in imported.headers["location"]
            with factory() as db:
                draft = db.query(Article).filter_by(source_article_id="manual-article").one()
                assert draft.status == ArticleStatus.processing.value
                draft_id = draft.id
                draft_slug = draft.slug

            edit_page = client.get(imported.headers["location"])
            assert "发布到官网" in edit_page.text
            publish_csrf = re.search(
                r'name="csrf_token" value="([^"]+)"', edit_page.text
            ).group(1)
            publish = client.post(
                f"/admin/articles/{draft_id}/status",
                data={"target": "published", "csrf_token": publish_csrf},
                follow_redirects=False,
            )
            assert publish.status_code == 303
            public_article = client.get(f"/articles/{draft_slug}")
            assert public_article.status_code == 200
            assert "后台链接导入文章" in public_article.text
    finally:
        app.dependency_overrides.clear()

