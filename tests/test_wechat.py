from datetime import timezone

import httpx
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.config import Settings
from app.database import Base
from app.models import Article, ArticleStatus
from app.sync.adapters import SingleArticleAdapter
from app.sync.service import SyncService
from app.sync.wechat import (
    WechatFetchError, WechatUrlFetcher, parse_wechat_html, validate_wechat_url,
)


WECHAT_HTML = """
<!doctype html><html><head>
<meta property="og:title" content="微信测试文章">
<meta property="og:image" content="https://mmbiz.qpic.cn/cover.jpg">
<meta name="author" content="测试公众号">
<meta name="description" content="测试摘要">
</head><body>
<div id="js_content" style="visibility: hidden; opacity: 0; color: #333">
  <section><p>第一段</p><div><p>嵌套内容</p></div></section>
  <img data-src="https://mmbiz.qpic.cn/image.jpg">
</div>
<script>var ct = "1760918400";</script>
</body></html>
"""


def test_validate_wechat_url_blocks_non_wechat_and_unsafe_urls():
    assert validate_wechat_url("https://mp.weixin.qq.com/s/abc#fragment") == \
        "https://mp.weixin.qq.com/s/abc"
    with pytest.raises(WechatFetchError):
        validate_wechat_url("https://example.com/s/abc")
    with pytest.raises(WechatFetchError):
        validate_wechat_url("http://mp.weixin.qq.com/s/abc")
    with pytest.raises(WechatFetchError):
        validate_wechat_url("https://user:password@mp.weixin.qq.com/s/abc")


def test_parse_wechat_html_preserves_nested_content_and_metadata():
    article = parse_wechat_html(WECHAT_HTML, "https://mp.weixin.qq.com/s/abc")
    assert article.title == "微信测试文章"
    assert article.author == "测试公众号"
    assert "第一段" in article.html_content and "嵌套内容" in article.html_content
    assert "visibility:visible" in article.html_content
    assert len(article.assets) == 1
    assert article.published_at.tzinfo == timezone.utc


def test_fetcher_reads_a_wechat_page_with_bounded_http_client():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "mp.weixin.qq.com"
        return httpx.Response(
            200,
            headers={"content-type": "text/html; charset=utf-8"},
            content=WECHAT_HTML.encode("utf-8"),
        )

    article = WechatUrlFetcher(transport=httpx.MockTransport(handler)).fetch(
        "https://mp.weixin.qq.com/s/abc"
    )
    assert article.title == "微信测试文章"


def test_manual_import_is_saved_as_draft(tmp_path):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    article = parse_wechat_html(
        WECHAT_HTML.replace('<img data-src="https://mmbiz.qpic.cn/image.jpg">', ""),
        "https://mp.weixin.qq.com/s/abc",
    )
    settings = Settings(storage_dir=tmp_path, auto_publish=False)
    with factory() as db:
        result = SyncService(db, SingleArticleAdapter(article), settings).run(
            trigger="wechat-url-import"
        )
        stored = db.scalar(select(Article))
        assert result.success == 1
        assert stored.status == ArticleStatus.processing.value
        assert "微信测试文章" == stored.title

