from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

import httpx

from scanner.libs.schemas import PhotoReviewResult


@dataclass(frozen=True)
class DownloadedPhoto:
    image_url: str
    local_path: str
    content_type: str | None
    size_bytes: int
    image_hash: str
    perceptual_hash: str


class PhotoReviewService:
    def __init__(
        self,
        *,
        cache_dir: Path | None = None,
        review_cache_dir: Path | None = None,
        max_images: int = 10,
        max_bytes: int = 5_000_000,
        request_timeout_seconds: float = 20.0,
        client: httpx.Client | None = None,
    ) -> None:
        self.cache_dir = cache_dir or Path("scanner_data/images/by-hash")
        self.review_cache_dir = review_cache_dir or Path("scanner_data/photo_reviews")
        self.max_images = max_images
        self.max_bytes = max_bytes
        self.client = client or httpx.Client(timeout=request_timeout_seconds, follow_redirects=True)

    def load_cached_photo(
        self,
        *,
        image_url: str,
        local_path: str | None,
        content_type: str | None,
        size_bytes: int | None,
        image_hash: str | None,
        perceptual_hash: str | None,
    ) -> DownloadedPhoto | None:
        if not local_path or not image_hash or not size_bytes:
            return None
        path = Path(local_path)
        if not path.exists():
            return None
        return DownloadedPhoto(
            image_url=image_url,
            local_path=str(path),
            content_type=content_type,
            size_bytes=size_bytes,
            image_hash=image_hash,
            perceptual_hash=perceptual_hash or image_hash[:16],
        )

    def download_photo(self, image_url: str) -> DownloadedPhoto | None:
        if _should_skip_image_url(image_url):
            return None
        response = self.client.get(image_url)
        response.raise_for_status()

        content = response.content
        if not content:
            return None
        if len(content) > self.max_bytes:
            return None
        content_type = response.headers.get("content-type")
        if content_type and not content_type.lower().startswith("image/"):
            return None

        image_hash = hashlib.sha256(content).hexdigest()
        perceptual_hash = image_hash[:16]
        extension = _choose_extension(
            content_type=content_type,
            image_url=image_url,
        )
        target_path = self.cache_dir / image_hash[:2] / f"{image_hash}{extension}"
        target_path.parent.mkdir(parents=True, exist_ok=True)
        if not target_path.exists():
            target_path.write_bytes(content)

        return DownloadedPhoto(
            image_url=image_url,
            local_path=str(target_path.resolve()),
            content_type=content_type,
            size_bytes=len(content),
            image_hash=image_hash,
            perceptual_hash=perceptual_hash,
        )

    def review(self, photos: list[DownloadedPhoto]) -> PhotoReviewResult:
        limited = photos[: self.max_images]
        image_hashes = [photo.image_hash for photo in limited]
        cached = self._load_cached_review(image_hashes)
        if cached is not None:
            return cached.model_copy(
                update={
                    "local_paths": [photo.local_path for photo in limited],
                }
            )

        photo_count = len(limited)
        unique_hash_count = len(set(image_hashes))
        duplicate_count = max(photo_count - unique_hash_count, 0)
        duplicate_ratio = (duplicate_count / photo_count) if photo_count else 0.0
        average_size = (
            sum(photo.size_bytes for photo in limited) / photo_count if photo_count else 0.0
        )
        low_filesize_count = sum(1 for photo in limited if photo.size_bytes < 25_000)

        fraud_flags: list[str] = []
        mismatch_flags: list[str] = []
        reasons: list[str] = []

        if photo_count == 0:
            mismatch_flags.append("no_photos")
            reasons.append("Listing had no downloadable photos after Stage 2.")
        else:
            reasons.append(f"Reviewed {photo_count} downloaded photo(s).")

        if duplicate_count:
            fraud_flags.append("duplicate_photo_content")
            reasons.append("At least two image URLs resolved to duplicate photo content.")

        if photo_count == 1:
            mismatch_flags.append("limited_photo_coverage")
            reasons.append("Only one photo is available, which limits confidence.")
        elif photo_count == 2:
            mismatch_flags.append("light_photo_coverage")
            reasons.append("Only two photos are available, so coverage is still thin.")

        if photo_count and low_filesize_count >= max(1, photo_count // 2):
            mismatch_flags.append("low_filesize_photos")
            reasons.append("Most downloaded photos are low-file-size and may be low information.")

        unique_ratio = (unique_hash_count / photo_count) if photo_count else 0.0
        photo_quality_score = _clamp(
            0.15
            + min(photo_count, 6) * 0.1
            + unique_ratio * 0.25
            + min(average_size / 350_000, 1.0) * 0.2
            - duplicate_ratio * 0.2
        )
        device_visibility_score = _clamp(
            0.1
            + min(photo_count, 5) * 0.12
            + unique_ratio * 0.2
            - (0.12 if "limited_photo_coverage" in mismatch_flags else 0.0)
        )
        confidence = _clamp(
            ((photo_quality_score + device_visibility_score) / 2.0)
            - (0.12 if "low_filesize_photos" in mismatch_flags else 0.0)
        )

        condition_band = "UNKNOWN"
        if photo_count >= 3 and not fraud_flags and "low_filesize_photos" not in mismatch_flags:
            condition_band = "B/C"

        review = PhotoReviewResult(
            downloaded_photo_count=photo_count,
            unique_photo_count=unique_hash_count,
            photo_quality_score=round(photo_quality_score, 3),
            device_visibility_score=round(device_visibility_score, 3),
            damage_flags=[],
            accessory_flags=[],
            fraud_flags=fraud_flags,
            mismatch_flags=mismatch_flags,
            condition_band=condition_band,
            confidence=round(confidence, 3),
            image_hashes=image_hashes,
            local_paths=[photo.local_path for photo in limited],
            reasons=reasons,
        )
        self._store_cached_review(review)
        return review

    def _cache_key(self, image_hashes: list[str]) -> str | None:
        if not image_hashes:
            return None
        joined = ",".join(sorted(image_hashes))
        return hashlib.sha256(joined.encode()).hexdigest()

    def _load_cached_review(self, image_hashes: list[str]) -> PhotoReviewResult | None:
        cache_key = self._cache_key(image_hashes)
        if cache_key is None:
            return None
        cache_path = self.review_cache_dir / f"{cache_key}.json"
        if not cache_path.exists():
            return None
        return PhotoReviewResult.model_validate_json(cache_path.read_text())

    def _store_cached_review(self, review: PhotoReviewResult) -> None:
        cache_key = self._cache_key(review.image_hashes)
        if cache_key is None:
            return
        self.review_cache_dir.mkdir(parents=True, exist_ok=True)
        cache_path = self.review_cache_dir / f"{cache_key}.json"
        cache_path.write_text(json.dumps(review.model_dump(mode="json"), indent=2))


def _choose_extension(*, content_type: str | None, image_url: str) -> str:
    if content_type:
        lowered = content_type.lower()
        if "png" in lowered:
            return ".png"
        if "jpeg" in lowered or "jpg" in lowered:
            return ".jpg"
        if "webp" in lowered:
            return ".webp"

    path = urlparse(image_url).path.lower()
    for extension in (".png", ".jpg", ".jpeg", ".webp"):
        if path.endswith(extension):
            return extension
    return ".img"


def _should_skip_image_url(image_url: str) -> bool:
    parsed = urlparse(image_url)
    path = parsed.path.lower()
    if parsed.netloc and parsed.netloc != "images.craigslist.org":
        return True
    thumbnail_match = re.search(r"_(?P<width>\d+)x(?P<height>\d+)(?:c)?\.", path)
    if thumbnail_match:
        width = int(thumbnail_match.group("width"))
        height = int(thumbnail_match.group("height"))
        if width <= 100 and height <= 100:
            return True
    return False


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, value))
