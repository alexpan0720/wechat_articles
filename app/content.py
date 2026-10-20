from __future__ import annotations

import hashlib
import re
import unicodedata

import bleach
from bleach.css_sanitizer import CSSSanitizer
from bs4 import BeautifulSoup


ALLOWED_TAGS = {
    "a", "abbr", "article", "b", "blockquote", "br", "caption", "center", "code",
    "col", "colgroup", "dd", "del", "details", "div", "dl", "dt", "em", "figcaption",
    "figure", "font", "h1", "h2", "h3", "h4", "h5", "h6", "hr", "i", "img", "ins",
    "li", "mark", "ol", "p", "pre", "s", "section", "small", "span", "strong", "sub",
    "summary", "sup", "table", "tbody", "td", "tfoot", "th", "thead", "tr", "u", "ul",
}

ALLOWED_CSS_PROPERTIES = {
    "align-items", "align-self", "background", "background-color", "background-image",
    "background-position", "background-repeat", "background-size", "border", "border-bottom",
    "border-color", "border-left", "border-radius", "border-right", "border-style", "border-top",
    "border-width", "box-shadow", "box-sizing", "clear", "color", "column-count", "display",
    "flex", "flex-basis", "flex-direction", "flex-flow", "flex-grow", "flex-shrink", "flex-wrap",
    "float", "font", "font-family", "font-size", "font-style", "font-weight", "gap", "height",
    "justify-content", "letter-spacing", "line-height", "list-style", "margin", "margin-bottom",
    "margin-left", "margin-right", "margin-top", "max-height", "max-width", "min-height",
    "min-width", "object-fit", "opacity", "overflow", "overflow-wrap", "padding", "padding-bottom",
    "padding-left", "padding-right", "padding-top", "position", "table-layout", "text-align",
    "text-decoration", "text-indent", "text-overflow", "text-shadow", "text-transform",
    "transform", "vertical-align", "visibility", "white-space", "width", "word-break",
    "word-spacing", "word-wrap", "z-index",
}


def _allow_attribute(tag: str, name: str, value: str) -> bool:
    if name.lower().startswith("on"):
        return False
    if name in {"class", "style", "title", "align", "width", "height", "colspan", "rowspan"}:
        return True
    if name.startswith("data-") or name.startswith("aria-"):
        return True
    if tag == "a" and name in {"href", "target", "rel"}:
        return True
    if tag == "img" and name in {"src", "alt", "loading", "decoding"}:
        return True
    return False


def sanitize_article_html(raw_html: str) -> str:
    """Keep presentation-oriented HTML while removing active and unsafe content."""
    # Bleach strips forbidden tags but intentionally keeps their text. Active elements need
    # to be removed with their complete contents before the allow-list pass.
    preclean = BeautifulSoup(raw_html, "html.parser")
    for active in preclean.find_all({"script", "style", "iframe", "object", "embed", "form"}):
        active.decompose()
    cleaned = bleach.clean(
        str(preclean),
        tags=ALLOWED_TAGS,
        attributes=_allow_attribute,
        protocols={"http", "https", "mailto", "tel", "data"},
        css_sanitizer=CSSSanitizer(allowed_css_properties=ALLOWED_CSS_PROPERTIES),
        strip=True,
        strip_comments=True,
    )
    soup = BeautifulSoup(cleaned, "html.parser")
    for link in soup.find_all("a"):
        if link.get("target") == "_blank":
            link["rel"] = "noopener noreferrer"
    for image in soup.find_all("img"):
        image["loading"] = image.get("loading", "lazy")
        image["decoding"] = image.get("decoding", "async")
        if image.get("data-src") and not image.get("src"):
            image["src"] = image["data-src"]
    return str(soup)


def content_hash(raw_html: str) -> str:
    normalized = re.sub(r"\s+", " ", raw_html).strip()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def slugify(value: str, *, fallback: str) -> str:
    value = unicodedata.normalize("NFKC", value).lower()
    value = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "-", value).strip("-")
    if not value:
        value = f"article-{hashlib.sha1(fallback.encode()).hexdigest()[:12]}"
    return value[:180]


def text_excerpt(html: str, limit: int = 150) -> str:
    text = BeautifulSoup(html, "html.parser").get_text(" ", strip=True)
    return text if len(text) <= limit else text[:limit].rstrip() + "…"


def article_document(title: str, content: str) -> str:
    safe_title = bleach.clean(title, tags=set(), strip=True)
    return f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{safe_title}</title>
<style>
:root {{ color-scheme: light; }}
html,body {{ margin:0; padding:0; background:#fff; }}
body {{ color:#292824; font-family:"Noto Serif SC","Songti SC",serif; line-height:1.8;
  overflow-wrap:anywhere; -webkit-font-smoothing:antialiased; }}
.wechat-content {{ width:100%; max-width:100%; overflow:hidden; }}
.wechat-content img {{ max-width:100% !important; height:auto !important; }}
.wechat-content table {{ max-width:100% !important; }}
@media (max-width:640px) {{ .wechat-content {{ font-size:16px; }} }}
</style></head><body><main class="wechat-content">{content}</main></body></html>"""

