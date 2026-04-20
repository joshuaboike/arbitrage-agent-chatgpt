from __future__ import annotations

import httpx

from scanner.libs.nlp.lots import LotAnalyzer
from scanner.libs.nlp.openai_triage import OpenAIStageOneTriageService
from scanner.libs.schemas import RawListingEvent, TriageDecision


def test_openai_stage_one_triage_parses_structured_response() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "output_text": (
                    '{"is_candidate":true,"item_type":"laptop","brand":"Apple",'
                    '"family":"MacBook Air","variant_hint":"M1 13-inch",'
                    '"condition_guess":"used_good","risk_flags":["spec ambiguity"],'
                    '"needs_detail_fetch":true,"triage_score":0.86,"confidence":0.79,'
                    '"reason":"Looks like a plausible resale laptop with good downside."}'
                )
            },
        )

    service = OpenAIStageOneTriageService(
        api_key="test-key",
        model="gpt-4o-mini",
        request_timeout_seconds=30.0,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    event = RawListingEvent(
        event_id="evt-1",
        source="craigslist",
        source_listing_id="cl-1",
        event_type="CREATE",
        observed_at="2026-04-20T12:00:00Z",
        listing_url="https://newyork.craigslist.org/sys/d/example/1.html",
        title="MacBook Air M1",
        price=500.0,
        currency="USD",
    )
    stage_zero = TriageDecision(accepted=True, reasons=["Passed Stage 0."])
    lot_analysis = LotAnalyzer().analyze(event)

    result = service.evaluate(event=event, stage_zero=stage_zero, lot_analysis=lot_analysis)

    assert result.is_candidate is True
    assert result.needs_detail_fetch is True
    assert result.family == "MacBook Air"
