from app.content import sanitize_article_html, slugify


def test_sanitizer_removes_active_content_and_keeps_layout():
    source = '<section style="color: red" onclick="steal()"><script>alert(1)</script><p>正文</p></section>'
    cleaned = sanitize_article_html(source)
    assert "script" not in cleaned
    assert "onclick" not in cleaned
    assert "alert" not in cleaned
    assert "color: red" in cleaned
    assert "正文" in cleaned


def test_slugify_supports_chinese_titles():
    assert slugify("公司法：三个变化", fallback="1") == "公司法-三个变化"

