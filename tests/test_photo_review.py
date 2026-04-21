from __future__ import annotations

import base64
import json

import httpx

from scanner.libs.schemas import (
    DetailGateDecision,
    EventType,
    FulfillmentStatus,
    LlmTriageDecision,
    PhotoExtractedFacts,
    PhotoReviewResult,
    RawListingEvent,
)
from scanner.libs.storage.models import ListingImageModel
from scanner.libs.storage.repositories import ListingRepository, TriageRepository
from scanner.libs.vision.review import PhotoReviewService

PNG_BYTES = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO2pK1cAAAAASUVORK5CYII="
)
PNG_BYTES_ALT = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAIAAAACCAQAAADZc7J/AAAADElEQVR42mNk+M8AAAMBAQAYlp8AAAAASUVORK5CYII="
)


def _build_event(
    *,
    source_listing_id: str,
    title: str,
    price: float,
    listing_url: str,
    images: list[str],
    attributes: dict | None = None,
) -> RawListingEvent:
    return RawListingEvent(
        event_id=f"evt-{source_listing_id}",
        source="craigslist",
        source_listing_id=source_listing_id,
        event_type=EventType.CREATE,
        observed_at="2026-04-20T12:00:00Z",
        listing_url=listing_url,
        title=title,
        price=price,
        currency="USD",
        images=images,
        attributes=attributes or {},
    )


def test_photo_review_service_downloads_and_caches_reviews(tmp_path) -> None:
    responses = {
        "https://images.craigslist.org/one_600x450.png": PNG_BYTES,
        "https://images.craigslist.org/two_600x450.png": PNG_BYTES,
        "https://images.craigslist.org/three_600x450.png": PNG_BYTES_ALT,
        "https://www.example.com/static.js": b"console.log('nope')",
    }

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=responses[str(request.url)],
            headers={"content-type": "image/png"},
        )

    service = PhotoReviewService(
        cache_dir=tmp_path / "images",
        review_cache_dir=tmp_path / "reviews",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    photos = [
        service.download_photo("https://images.craigslist.org/one_600x450.png"),
        service.download_photo("https://images.craigslist.org/two_600x450.png"),
        service.download_photo("https://images.craigslist.org/three_600x450.png"),
    ]
    downloaded = [photo for photo in photos if photo is not None]

    review = service.review(downloaded)
    cached_review = service.review(downloaded)

    assert len(downloaded) == 3
    assert all((tmp_path / "images").exists() for _ in [0])
    assert review.downloaded_photo_count == 3
    assert review.unique_photo_count == 2
    assert "duplicate_photo_content" in review.fraud_flags
    assert cached_review.image_hashes == review.image_hashes
    assert len(list((tmp_path / "reviews").glob("*.json"))) == 1

    skipped_thumb = service.download_photo("https://images.craigslist.org/abc_50x50c.jpg")
    skipped_static = service.download_photo("https://www.example.com/static.js")
    assert skipped_thumb is None
    assert skipped_static is None


def test_photo_review_service_extracts_image_evidence_with_openai(tmp_path) -> None:
    image_payload = {
        "output_text": json.dumps(
            {
                "photo_quality_score": 0.86,
                "device_visibility_score": 0.9,
                "damage_flags": [],
                "accessory_flags": ["charger_included", "original_box"],
                "fraud_flags": [],
                "mismatch_flags": [],
                "condition_band": "B",
                "confidence": 0.87,
                "extracted_facts": {
                    "brand": "Apple",
                    "family": "MacBook Pro",
                    "model_text": "MacBook Pro 16-inch M3 Max",
                    "cpu": "M3 Max",
                    "ram_gb": 64,
                    "storage_gb": 1024,
                    "screen_size": "16",
                    "year": 2023,
                    "battery_cycles": 16,
                    "battery_health_percent": 100,
                    "applecare_until": "Jan 12, 2027",
                    "ocr_text": (
                        "MacBook Pro 16-inch M3 Max 64 GB 1 TB Battery cycles: 16 "
                        "AppleCare until Jan 12, 2027"
                    ),
                    "evidence_notes": [
                        "About This Mac screenshot confirms the exact model and specs."
                    ],
                },
                "reasons": ["Read all provided screenshots and product photos."],
            }
        )
    }

    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url) == "https://api.openai.com/v1/responses":
            return httpx.Response(200, json=image_payload)
        return httpx.Response(
            200,
            content=PNG_BYTES,
            headers={"content-type": "image/png"},
        )

    service = PhotoReviewService(
        cache_dir=tmp_path / "images",
        review_cache_dir=tmp_path / "reviews",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        openai_api_key="test-key",
        openai_model="gpt-4.1-mini",
    )

    photo = service.download_photo("https://images.craigslist.org/one_600x450.png")
    assert photo is not None

    review = service.review([photo])

    assert review.review_strategy == "metadata_plus_openai_vision"
    assert review.extracted_facts.model_text == "MacBook Pro 16-inch M3 Max"
    assert review.extracted_facts.battery_cycles == 16
    assert "charger_included" in review.accessory_flags
    assert review.confidence >= 0.8


def test_listing_repository_updates_image_metadata(test_container) -> None:
    with test_container.session_scope() as session:
        listing_repository = ListingRepository(session)
        event = _build_event(
            source_listing_id="img-1",
            title="MacBook Air M1",
            price=650.0,
            listing_url="https://example.com/listing/1",
            images=["https://images.craigslist.org/one_600x450.png"],
        )
        listing = listing_repository.upsert_event(event)

        listing_repository.update_image_metadata(
            listing_pk=listing.listing_pk,
            image_url="https://images.craigslist.org/one_600x450.png",
            local_path="/tmp/photo.png",
            content_type="image/png",
            size_bytes=12345,
            image_hash="abc123",
            perceptual_hash="abc123def456",
        )

        image = session.query(ListingImageModel).one()
        assert image.local_path == "/tmp/photo.png"
        assert image.content_type == "image/png"
        assert image.size_bytes == 12345
        assert image.image_hash == "abc123"


def test_triage_repository_lists_photo_review_candidates(test_container) -> None:
    with test_container.session_scope() as session:
        listing_repository = ListingRepository(session)
        triage_repository = TriageRepository(session)
        event = _build_event(
            source_listing_id="stage3-1",
            title="MacBook Pro 14",
            price=900.0,
            listing_url="https://example.com/listing/2",
            images=["https://images.craigslist.org/one_600x450.png"],
            attributes={"search_delivery_filter_applied": True},
        )
        listing = listing_repository.upsert_event(event)
        stage_zero = test_container.stage_zero_triage.evaluate(event)
        lot_analysis = test_container.lot_analyzer.analyze(event)
        llm_triage = LlmTriageDecision(
            is_candidate=True,
            item_type="laptop",
            brand="Apple",
            family="MacBook Pro",
            variant_hint="14-inch",
            condition_guess="used_good",
            risk_flags=[],
            needs_detail_fetch=True,
            triage_score=0.9,
            confidence=0.84,
            reason="Looks promising.",
        )
        detail_gate = DetailGateDecision(
            should_download_photos=True,
            fulfillment_status=FulfillmentStatus.UNKNOWN,
            reasons=["Advances because search used delivery filter."],
        )

        triage_repository.save(
            listing_pk=listing.listing_pk,
            stage_zero=stage_zero,
            lot_analysis=lot_analysis,
            llm_triage=llm_triage,
            llm_model="gpt-4o-mini",
            detail_gate=detail_gate,
        )

        candidates = triage_repository.list_photo_review_candidates(source="craigslist")
        assert len(candidates) == 1

        photo_review = PhotoReviewResult(
            downloaded_photo_count=1,
            unique_photo_count=1,
            photo_quality_score=0.3,
            device_visibility_score=0.4,
            damage_flags=[],
            accessory_flags=[],
            fraud_flags=[],
            mismatch_flags=["low_filesize_photos"],
            condition_band="UNKNOWN",
            confidence=0.25,
            image_hashes=["abc123"],
            local_paths=["/tmp/photo.png"],
            extracted_facts=PhotoExtractedFacts(),
            reasons=["Reviewed one photo."],
        )
        triage_repository.save(
            listing_pk=listing.listing_pk,
            stage_zero=stage_zero,
            lot_analysis=lot_analysis,
            photo_review=photo_review,
        )

        assert triage_repository.list_photo_review_candidates(source="craigslist") == []
        assert (
            len(
                triage_repository.list_photo_review_candidates(
                    source="craigslist",
                    include_low_info_rechecks=True,
                )
            )
            == 1
        )
