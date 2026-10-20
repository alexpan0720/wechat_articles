from __future__ import annotations

import hashlib
import mimetypes
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup


ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/gif", "image/webp", "image/avif"}


@dataclass(slots=True)
class AssetResult:
    source_url: str
    public_url: str | None
    storage_path: str | None
    checksum: str | None
    media_type: str | None
    error: str | None = None


def migrate_article_images(
    html: str,
    *,
    article_id: str,
    storage_dir: Path,
    max_bytes: int,
    referer: str,
) -> tuple[str, list[AssetResult]]:
    soup = BeautifulSoup(html, "html.parser")
    target_dir = storage_dir / "article-images" / article_id
    results: list[AssetResult] = []
    cache: dict[str, AssetResult] = {}

    for index, image in enumerate(soup.find_all("img"), start=1):
        source_url = image.get("data-src") or image.get("src")
        if not source_url or source_url.startswith(("data:", "/media/")):
            continue
        if source_url in cache:
            result = cache[source_url]
        else:
            result = _download_image(
                source_url,
                target_dir=target_dir,
                index=index,
                max_bytes=max_bytes,
                referer=referer,
                article_id=article_id,
            )
            cache[source_url] = result
            results.append(result)
        if result.public_url:
            image["src"] = result.public_url
            image.attrs.pop("data-src", None)

    return str(soup), results


def _download_image(
    url: str, *, target_dir: Path, index: int, max_bytes: int, referer: str, article_id: str
) -> AssetResult:
    try:
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"}:
            raise ValueError("unsupported asset URL scheme")
        with httpx.stream(
            "GET",
            url,
            follow_redirects=True,
            timeout=30,
            headers={"Referer": referer, "User-Agent": "LawFirmArticleSync/1.0"},
        ) as response:
            response.raise_for_status()
            media_type = response.headers.get("content-type", "").split(";", 1)[0].lower()
            if media_type not in ALLOWED_IMAGE_TYPES:
                raise ValueError(f"unsupported image type: {media_type or 'unknown'}")
            chunks: list[bytes] = []
            size = 0
            for chunk in response.iter_bytes():
                size += len(chunk)
                if size > max_bytes:
                    raise ValueError("asset exceeds configured size limit")
                chunks.append(chunk)
        body = b"".join(chunks)
        checksum = hashlib.sha256(body).hexdigest()
        extension = mimetypes.guess_extension(media_type) or ".bin"
        if extension == ".jpe":
            extension = ".jpg"
        filename = f"image-{index:03d}-{checksum[:12]}{extension}"
        target_dir.mkdir(parents=True, exist_ok=True)
        path = target_dir / filename
        path.write_bytes(body)
        storage_path = str(path.as_posix())
        return AssetResult(
            source_url=url,
            public_url=f"/media/article-images/{article_id}/{filename}",
            storage_path=storage_path,
            checksum=checksum,
            media_type=media_type,
        )
    except (httpx.HTTPError, OSError, ValueError) as exc:
        return AssetResult(url, None, None, None, None, str(exc))

