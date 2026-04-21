from __future__ import annotations

import base64
import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

import httpx
from pydantic import BaseModel, Field

from scanner.libs.schemas import PhotoExtractedFacts, PhotoReviewResult


@dataclass(frozen=True)
class DownloadedPhoto:
    image_url: str
    local_path: str
    content_type: str | None
    size_bytes: int
    image_hash: str
    perceptual_hash: str


class VisionPhotoAssessment(BaseModel):
    photo_quality_score: float
    device_visibility_score: float
    damage_flags: list[str] = Field(default_factory=list)
    accessory_flags: list[str] = Field(default_factory=list)
    fraud_flags: list[str] = Field(default_factory=list)
    mismatch_flags: list[str] = Field(default_factory=list)
    condition_band: str = "UNKNOWN"
    confidence: float = 0.0
    extracted_facts: PhotoExtractedFacts = Field(default_factory=PhotoExtractedFacts)
    reasons: list[str] = Field(default_factory=list)


def _nullable_int_schema() -> dict[str, object]:
    return {"anyOf": [{"type": "integer"}, {"type": "null"}]}


VISION_REVIEW_SCHEMA: dict[str, object] = {
    "name": "stage_three_photo_review",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "photo_quality_score": {"type": "number", "minimum": 0, "maximum": 1},
            "device_visibility_score": {"type": "number", "minimum": 0, "maximum": 1},
            "damage_flags": {"type": "array", "items": {"type": "string"}},
            "accessory_flags": {"type": "array", "items": {"type": "string"}},
            "fraud_flags": {"type": "array", "items": {"type": "string"}},
            "mismatch_flags": {"type": "array", "items": {"type": "string"}},
            "condition_band": {"type": "string"},
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
            "extracted_facts": {
                "type": "object",
                "properties": {
                    "brand": {"anyOf": [{"type": "string"}, {"type": "null"}]},
                    "family": {"anyOf": [{"type": "string"}, {"type": "null"}]},
                    "model_text": {"anyOf": [{"type": "string"}, {"type": "null"}]},
                    "cpu": {"anyOf": [{"type": "string"}, {"type": "null"}]},
                    "ram_gb": _nullable_int_schema(),
                    "storage_gb": _nullable_int_schema(),
                    "screen_size": {"anyOf": [{"type": "string"}, {"type": "null"}]},
                    "year": _nullable_int_schema(),
                    "battery_cycles": _nullable_int_schema(),
                    "battery_health_percent": _nullable_int_schema(),
                    "applecare_until": {"anyOf": [{"type": "string"}, {"type": "null"}]},
                    "ocr_text": {"anyOf": [{"type": "string"}, {"type": "null"}]},
                    "evidence_notes": {"type": "array", "items": {"type": "string"}},
                },
                "required": [
                    "brand",
                    "family",
                    "model_text",
                    "cpu",
                    "ram_gb",
                    "storage_gb",
                    "screen_size",
                    "year",
                    "battery_cycles",
                    "battery_health_percent",
                    "applecare_until",
                    "ocr_text",
                    "evidence_notes",
                ],
                "additionalProperties": False,
            },
            "reasons": {"type": "array", "items": {"type": "string"}},
        },
        "required": [
            "photo_quality_score",
            "device_visibility_score",
            "damage_flags",
            "accessory_flags",
            "fraud_flags",
            "mismatch_flags",
            "condition_band",
            "confidence",
            "extracted_facts",
            "reasons",
        ],
        "additionalProperties": False,
    },
}


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
        openai_api_key: str | None = None,
        openai_model: str = "gpt-4.1-mini",
        review_cache_version: str = "stage3-v2",
    ) -> None:
        self.cache_dir = cache_dir or Path("scanner_data/images/by-hash")
        self.review_cache_dir = review_cache_dir or Path("scanner_data/photo_reviews")
        self.max_images = max_images
        self.max_bytes = max_bytes
        self.client = client or httpx.Client(timeout=request_timeout_seconds, follow_redirects=True)
        self.openai_api_key = openai_api_key
        self.openai_model = openai_model
        self.review_cache_version = review_cache_version

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

        metadata_review = self._review_from_metadata(limited)
        if not limited or not self.openai_api_key:
            self._store_cached_review(metadata_review)
            return metadata_review

        try:
            vision_review = self._review_with_openai(limited)
        except Exception as exc:  # noqa: BLE001
            fallback = metadata_review.model_copy(
                update={
                    "reasons": [
                        *metadata_review.reasons,
                        (
                            "OpenAI vision review failed, so Stage 3 fell back to "
                            f"metadata-only review: {exc}"
                        ),
                    ],
                }
            )
            self._store_cached_review(fallback)
            return fallback

        merged = self._merge_reviews(
            metadata_review=metadata_review,
            vision_review=vision_review,
            photos=limited,
        )
        self._store_cached_review(merged)
        return merged

    def _review_from_metadata(self, photos: list[DownloadedPhoto]) -> PhotoReviewResult:
        photo_count = len(photos)
        image_hashes = [photo.image_hash for photo in photos]
        unique_hash_count = len(set(image_hashes))
        duplicate_count = max(photo_count - unique_hash_count, 0)
        duplicate_ratio = (duplicate_count / photo_count) if photo_count else 0.0
        average_size = (
            sum(photo.size_bytes for photo in photos) / photo_count if photo_count else 0.0
        )
        low_filesize_count = sum(1 for photo in photos if photo.size_bytes < 25_000)

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

        return PhotoReviewResult(
            review_strategy="metadata_first",
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
            local_paths=[photo.local_path for photo in photos],
            extracted_facts=PhotoExtractedFacts(),
            reasons=reasons,
        )

    def _review_with_openai(self, photos: list[DownloadedPhoto]) -> VisionPhotoAssessment:
        content: list[dict[str, str]] = [
            {
                "type": "input_text",
                "text": (
                    "Review all provided listing photos for a used laptop or Mac mini listing. "
                    "Read screenshots and labels carefully. Extract exact model/specs only when "
                    "the images support them. If something is uncertain, return null instead of "
                    "guessing. Treat battery screenshots, About This Mac, and AppleCare screens "
                    "as strong evidence. Also note visible accessories, damage, fraud cues, and "
                    "image-quality problems."
                ),
            }
        ]
        for photo in photos:
            content.append(
                {
                    "type": "input_image",
                    "image_url": _photo_to_data_url(photo),
                    "detail": "high",
                }
            )

        response = self.client.post(
            "https://api.openai.com/v1/responses",
            headers={
                "Authorization": f"Bearer {self.openai_api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": self.openai_model,
                "input": [
                    {
                        "role": "system",
                        "content": (
                            "You underwrite used electronics listings from photos. "
                            "Return strict JSON only."
                        ),
                    },
                    {
                        "role": "user",
                        "content": content,
                    },
                ],
                "text": {
                    "format": {
                        "type": "json_schema",
                        "name": VISION_REVIEW_SCHEMA["name"],
                        "strict": VISION_REVIEW_SCHEMA["strict"],
                        "schema": VISION_REVIEW_SCHEMA["schema"],
                    }
                },
            },
        )
        response.raise_for_status()
        payload = response.json()
        refusal = payload.get("refusal")
        if refusal:
            raise RuntimeError(f"OpenAI vision review refused the request: {refusal}")

        output_text = _extract_output_text(payload)
        return VisionPhotoAssessment.model_validate_json(output_text)

    def _merge_reviews(
        self,
        *,
        metadata_review: PhotoReviewResult,
        vision_review: VisionPhotoAssessment,
        photos: list[DownloadedPhoto],
    ) -> PhotoReviewResult:
        damage_flags = _dedupe_preserve_order(
            [*metadata_review.damage_flags, *vision_review.damage_flags]
        )
        accessory_flags = _dedupe_preserve_order(
            [*metadata_review.accessory_flags, *vision_review.accessory_flags]
        )
        fraud_flags = _dedupe_preserve_order(
            [*metadata_review.fraud_flags, *vision_review.fraud_flags]
        )
        mismatch_flags = _dedupe_preserve_order(
            [*metadata_review.mismatch_flags, *vision_review.mismatch_flags]
        )
        reasons = [
            *metadata_review.reasons,
            *vision_review.reasons,
            *vision_review.extracted_facts.evidence_notes,
        ]

        return PhotoReviewResult(
            review_strategy="metadata_plus_openai_vision",
            downloaded_photo_count=metadata_review.downloaded_photo_count,
            unique_photo_count=metadata_review.unique_photo_count,
            photo_quality_score=round(
                max(metadata_review.photo_quality_score, vision_review.photo_quality_score), 3
            ),
            device_visibility_score=round(
                max(metadata_review.device_visibility_score, vision_review.device_visibility_score),
                3,
            ),
            damage_flags=damage_flags,
            accessory_flags=accessory_flags,
            fraud_flags=fraud_flags,
            mismatch_flags=mismatch_flags,
            condition_band=(
                vision_review.condition_band
                if vision_review.condition_band and vision_review.condition_band != "UNKNOWN"
                else metadata_review.condition_band
            ),
            confidence=round(max(metadata_review.confidence, vision_review.confidence), 3),
            image_hashes=metadata_review.image_hashes,
            local_paths=[photo.local_path for photo in photos],
            extracted_facts=vision_review.extracted_facts,
            reasons=_dedupe_preserve_order(reasons),
        )

    def _cache_key(self, image_hashes: list[str]) -> str | None:
        if not image_hashes:
            return None
        strategy_key = self.openai_model if self.openai_api_key else "metadata"
        joined = f"{self.review_cache_version}:{strategy_key}:{','.join(sorted(image_hashes))}"
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


def _extract_output_text(payload: dict[str, object]) -> str:
    output_text = payload.get("output_text")
    if isinstance(output_text, str) and output_text.strip():
        return output_text

    for output in payload.get("output", []):
        if not isinstance(output, dict):
            continue
        for content in output.get("content", []):
            if (
                isinstance(content, dict)
                and content.get("type") == "output_text"
                and content.get("text")
            ):
                return str(content["text"])

    raise RuntimeError(f"Unable to extract structured vision text from response: {payload}")


def _photo_to_data_url(photo: DownloadedPhoto) -> str:
    content_type = photo.content_type or _guess_mime_type_from_path(photo.local_path)
    data = Path(photo.local_path).read_bytes()
    encoded = base64.b64encode(data).decode("ascii")
    return f"data:{content_type};base64,{encoded}"


def _guess_mime_type_from_path(local_path: str) -> str:
    suffix = Path(local_path).suffix.lower()
    if suffix in {".jpg", ".jpeg"}:
        return "image/jpeg"
    if suffix == ".png":
        return "image/png"
    if suffix == ".webp":
        return "image/webp"
    return "application/octet-stream"


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


def _dedupe_preserve_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        if not value or value in seen:
            continue
        seen.add(value)
        ordered.append(value)
    return ordered


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, value))
