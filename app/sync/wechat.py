from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from urllib.parse import parse_qs, urljoin, urlsplit, urlunsplit

import httpx
from bs4 import BeautifulSoup

from app.sync.types import SourceArticle, SourceAsset


WECHAT_HOSTS = {"mp.weixin.qq.com"}
REDIRECT_CODES = {301, 302, 303, 307, 308}


class WechatFetchError(ValueError):
    """A user-facing error raised when a WeChat page cannot be imported safely."""


def validate_wechat_url(value: str) -> str:
    value = value.strip()
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError as exc:
        raise WechatFetchError("链接格式不正确") from exc
    if parsed.scheme.lower() != "https":
        raise WechatFetchError("仅支持 HTTPS 微信文章链接")
    if (parsed.hostname or "").lower() not in WECHAT_HOSTS:
        raise WechatFetchError("仅支持 mp.weixin.qq.com 域名的微信文章链接")
    if parsed.username or parsed.password or (port is not None and port != 443):
        raise WechatFetchError("链接包含不允许的认证信息或端口")
    if not parsed.path.startswith("/s"):
        raise WechatFetchError("这不是受支持的微信公众号文章链接")
    # Fragments never affect the server response and should not enter article identity.
    return urlunsplit(("https", parsed.netloc.lower(), parsed.path, parsed.query, ""))


def parse_wechat_html(html: str, url: str) -> SourceArticle:
    soup = BeautifulSoup(html, "html.parser")
    content = soup.find(id="js_content")
    if content is None:
        if "环境异常" in soup.get_text(" ", strip=True) or "verify" in html.lower():
            raise WechatFetchError("微信返回了访问验证页面，请稍后重试或更换网络环境")
        raise WechatFetchError("页面中没有找到微信正文（js_content）")

    title = _meta(soup, "property", "og:title") or _first_text(soup, "#activity-name")
    if not title:
        raise WechatFetchError("无法从微信页面提取文章标题")
    author = _meta(soup, "name", "author") or _first_text(soup, "#js_name")
    summary = _meta(soup, "name", "description") or _meta(soup, "property", "og:description")
    cover_url = _meta(soup, "property", "og:image")

    # WeChat initially hides the article container and reveals it through JavaScript. Scripts are
    # intentionally not executed on our site, so make the imported container visible explicitly.
    style = content.get("style", "")
    style = re.sub(r"(?:visibility\s*:\s*hidden|opacity\s*:\s*0)\s*;?", "", style, flags=re.I)
    content["style"] = f"{style};visibility:visible;opacity:1".strip(";")

    assets: list[SourceAsset] = []
    seen: set[str] = set()
    for image in content.find_all("img"):
        image_url = image.get("data-src") or image.get("src")
        if image_url and image_url.startswith(("http://", "https://")) and image_url not in seen:
            seen.add(image_url)
            assets.append(SourceAsset(url=image_url, type="image"))

    parsed_url = urlsplit(url)
    params = parse_qs(parsed_url.query)
    identity_parts = [params.get(key, [""])[0] for key in ("__biz", "mid", "idx", "sn")]
    stable_identity = "|".join(part for part in identity_parts if part) or url
    article_id = hashlib.sha256(stable_identity.encode("utf-8")).hexdigest()[:32]
    account_id = params.get("__biz", [""])[0] or author or "wechat-manual-import"

    published_at = _extract_publish_time(html)
    return SourceArticle(
        source="wechat",
        account_id=account_id,
        article_id=article_id,
        original_url=url,
        title=title.strip(),
        published_at=published_at,
        cover_url=cover_url,
        author=author.strip() if author else None,
        summary=summary.strip() if summary else None,
        html_content=str(content),
        assets=assets,
        raw_payload={"import_method": "wechat_url", "url": url},
    )


class WechatUrlFetcher:
    def __init__(
        self,
        *,
        timeout_seconds: float = 20,
        max_html_bytes: int = 8 * 1024 * 1024,
        transport: httpx.BaseTransport | None = None,
    ):
        self.timeout_seconds = timeout_seconds
        self.max_html_bytes = max_html_bytes
        self.transport = transport

    def fetch(self, value: str) -> SourceArticle:
        current_url = validate_wechat_url(value)
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.6",
        }
        try:
            with httpx.Client(
                timeout=self.timeout_seconds,
                follow_redirects=False,
                transport=self.transport,
                headers=headers,
            ) as client:
                for _ in range(4):
                    with client.stream("GET", current_url) as response:
                        if response.status_code in REDIRECT_CODES:
                            location = response.headers.get("location")
                            if not location:
                                raise WechatFetchError("微信返回了无效跳转")
                            current_url = validate_wechat_url(urljoin(current_url, location))
                            continue
                        response.raise_for_status()
                        media_type = response.headers.get("content-type", "").lower()
                        if media_type and "html" not in media_type:
                            raise WechatFetchError("微信链接没有返回 HTML 文章页面")
                        declared = response.headers.get("content-length")
                        if declared and int(declared) > self.max_html_bytes:
                            raise WechatFetchError("文章页面超过允许的大小")
                        chunks: list[bytes] = []
                        size = 0
                        for chunk in response.iter_bytes():
                            size += len(chunk)
                            if size > self.max_html_bytes:
                                raise WechatFetchError("文章页面超过允许的大小")
                            chunks.append(chunk)
                        body = b"".join(chunks)
                        encoding = response.encoding or "utf-8"
                        html = body.decode(encoding, errors="replace")
                        return parse_wechat_html(html, current_url)
                raise WechatFetchError("微信链接跳转次数过多")
        except WechatFetchError:
            raise
        except (httpx.HTTPError, UnicodeError, ValueError) as exc:
            raise WechatFetchError(f"下载微信文章失败：{exc}") from exc


def _meta(soup: BeautifulSoup, key: str, value: str) -> str | None:
    element = soup.find("meta", attrs={key: value})
    content = element.get("content") if element else None
    return str(content) if content else None


def _first_text(soup: BeautifulSoup, selector: str) -> str | None:
    element = soup.select_one(selector)
    return element.get_text(" ", strip=True) if element else None


def _extract_publish_time(html: str) -> datetime:
    patterns = [
        r"\bct\s*=\s*[\"'](\d{9,12})[\"']",
        r"\bcreateTime\s*[:=]\s*[\"']?(\d{9,12})",
    ]
    for pattern in patterns:
        match = re.search(pattern, html)
        if match:
            try:
                return datetime.fromtimestamp(int(match.group(1)), tz=timezone.utc)
            except (ValueError, OSError):
                pass
    return datetime.now(timezone.utc)

