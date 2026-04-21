from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path

import httpx

from scanner.libs.schemas import LotAnalysis, PhotoReviewResult, TriageDecision
from scanner.libs.services.container import ApplicationContainer
from scanner.libs.storage.repositories import ListingRepository, TriageRepository
from scanner.libs.utils.logging import get_logger
from scanner.libs.vision.review import DownloadedPhoto, PhotoReviewService

logger = get_logger(__name__)


def _photo_service_from_env() -> PhotoReviewService:
    cache_dir = Path(os.getenv("PHOTO_CACHE_DIR", "scanner_data/images/by-hash"))
    review_cache_dir = Path(os.getenv("PHOTO_REVIEW_CACHE_DIR", "scanner_data/photo_reviews"))
    max_images = int(os.getenv("PHOTO_MAX_IMAGES", "10"))
    max_bytes = int(os.getenv("PHOTO_MAX_BYTES", "5000000"))
    timeout = float(os.getenv("PHOTO_DOWNLOAD_TIMEOUT_SECONDS", "20"))
    openai_api_key = os.getenv("OPENAI_API_KEY") or None
    openai_model = os.getenv("OPENAI_STAGE3_MODEL", "gpt-4.1-mini")
    return PhotoReviewService(
        cache_dir=cache_dir,
        review_cache_dir=review_cache_dir,
        max_images=max_images,
        max_bytes=max_bytes,
        request_timeout_seconds=timeout,
        openai_api_key=openai_api_key,
        openai_model=openai_model,
    )


def _no_photo_review() -> PhotoReviewResult:
    return PhotoReviewResult(
        downloaded_photo_count=0,
        unique_photo_count=0,
        photo_quality_score=0.0,
        device_visibility_score=0.0,
        mismatch_flags=["no_photos"],
        condition_band="UNKNOWN",
        confidence=0.0,
        reasons=["Listing advanced to Stage 3 but had no downloadable photos."],
    )


def run_once(*, limit: int | None = None) -> dict:
    container = ApplicationContainer()
    container.ensure_database()
    photo_service = _photo_service_from_env()
    include_low_info_rechecks = (
        os.getenv("CRAIGSLIST_STAGE3_RECHECK_LOW_INFO", "").strip().lower()
        in {"1", "true", "yes", "on"}
    )

    processed = 0
    reviewed = 0
    skipped = 0
    downloaded_photo_total = 0
    examples: list[dict] = []

    with container.session_scope() as session:
        triage_repository = TriageRepository(session)
        listing_repository = ListingRepository(session)
        candidates = triage_repository.list_photo_review_candidates(
            source="craigslist",
            limit=limit,
            include_low_info_rechecks=include_low_info_rechecks,
        )

        for listing, triage_row in candidates:
            downloaded_photos: list[DownloadedPhoto] = []
            for image in listing.images[: photo_service.max_images]:
                cached_photo = photo_service.load_cached_photo(
                    image_url=image.image_url,
                    local_path=image.local_path,
                    content_type=image.content_type,
                    size_bytes=image.size_bytes,
                    image_hash=image.image_hash,
                    perceptual_hash=image.perceptual_hash,
                )
                if cached_photo is not None:
                    downloaded_photos.append(cached_photo)
                    continue

                try:
                    downloaded_photo = photo_service.download_photo(image.image_url)
                except httpx.HTTPError:
                    continue
                if downloaded_photo is None:
                    continue

                listing_repository.update_image_metadata(
                    listing_pk=listing.listing_pk,
                    image_url=image.image_url,
                    local_path=downloaded_photo.local_path,
                    content_type=downloaded_photo.content_type,
                    size_bytes=downloaded_photo.size_bytes,
                    image_hash=downloaded_photo.image_hash,
                    perceptual_hash=downloaded_photo.perceptual_hash,
                    downloaded_at=datetime.now(UTC),
                )
                downloaded_photos.append(downloaded_photo)

            photo_review = (
                photo_service.review(downloaded_photos) if downloaded_photos else _no_photo_review()
            )

            triage_repository.save(
                listing_pk=listing.listing_pk,
                stage_zero=TriageDecision.model_validate(triage_row.stage_zero_json),
                lot_analysis=LotAnalysis.model_validate(triage_row.lot_analysis_json),
                photo_review=photo_review,
            )

            processed += 1
            downloaded_photo_total += photo_review.downloaded_photo_count
            if photo_review.downloaded_photo_count:
                reviewed += 1
            else:
                skipped += 1

            if len(examples) < 10:
                examples.append(
                    {
                        "listing_pk": listing.listing_pk,
                        "title": listing.title,
                        "photo_count": photo_review.downloaded_photo_count,
                        "unique_photo_count": photo_review.unique_photo_count,
                        "photo_quality_score": photo_review.photo_quality_score,
                        "device_visibility_score": photo_review.device_visibility_score,
                        "fraud_flags": photo_review.fraud_flags,
                        "mismatch_flags": photo_review.mismatch_flags,
                        "condition_band": photo_review.condition_band,
                        "confidence": photo_review.confidence,
                    }
                )

    summary = {
        "processed": processed,
        "reviewed": reviewed,
        "skipped": skipped,
        "downloaded_photo_total": downloaded_photo_total,
        "include_low_info_rechecks": include_low_info_rechecks,
        "examples": examples,
    }
    logger.info("craigslist_stage3.completed", **summary)
    return summary


if __name__ == "__main__":
    raw_limit = os.getenv("CRAIGSLIST_STAGE3_LIMIT")
    result = run_once(limit=int(raw_limit) if raw_limit else None)
    print(json.dumps(result, indent=2))
