from __future__ import annotations

import json
from typing import Any

import httpx

from scanner.libs.schemas import LlmTriageDecision, LotAnalysis, RawListingEvent, TriageDecision

STAGE_ONE_TRIAGE_SCHEMA: dict[str, Any] = {
    "name": "stage_one_triage",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "is_candidate": {"type": "boolean"},
            "item_type": {"type": "string"},
            "brand": {"type": "string"},
            "family": {"type": "string"},
            "variant_hint": {"type": "string"},
            "condition_guess": {"type": "string"},
            "risk_flags": {"type": "array", "items": {"type": "string"}},
            "needs_detail_fetch": {"type": "boolean"},
            "triage_score": {"type": "number", "minimum": 0, "maximum": 100},
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
            "reason": {"type": "string"},
        },
        "required": [
            "is_candidate",
            "item_type",
            "brand",
            "family",
            "variant_hint",
            "condition_guess",
            "risk_flags",
            "needs_detail_fetch",
            "triage_score",
            "confidence",
            "reason",
        ],
        "additionalProperties": False,
    },
}


class OpenAIStageOneTriageService:
    def __init__(
        self,
        *,
        api_key: str | None,
        model: str,
        request_timeout_seconds: float,
        client: httpx.Client | None = None,
    ) -> None:
        self.api_key = api_key
        self.model = model
        self.client = client or httpx.Client(timeout=request_timeout_seconds)

    @property
    def is_configured(self) -> bool:
        return bool(self.api_key)

    def evaluate(
        self,
        *,
        event: RawListingEvent,
        stage_zero: TriageDecision,
        lot_analysis: LotAnalysis,
    ) -> LlmTriageDecision:
        if not self.api_key:
            raise RuntimeError("OPENAI_API_KEY is required for Stage 1 LLM triage.")

        response = self.client.post(
            "https://api.openai.com/v1/responses",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": self.model,
                "input": [
                    {
                        "role": "system",
                        "content": (
                            "You are a first-pass resale triage model for Craigslist laptop and "
                            "Mac mini listings. Return JSON only. Be conservative about sending "
                            "junk deeper, but do not reject good opportunities just because "
                            "specs are incomplete. Use empty strings for unknown brand, family, "
                            "variant_hint, or condition_guess values. Use triage_score on a "
                            "0-100 scale and confidence on a 0-1 scale."
                        ),
                    },
                    {
                        "role": "user",
                        "content": self._build_listing_prompt(
                            event=event,
                            stage_zero=stage_zero,
                            lot_analysis=lot_analysis,
                        ),
                    },
                ],
                "text": {
                    "format": {
                        "type": "json_schema",
                        "name": STAGE_ONE_TRIAGE_SCHEMA["name"],
                        "strict": STAGE_ONE_TRIAGE_SCHEMA["strict"],
                        "schema": STAGE_ONE_TRIAGE_SCHEMA["schema"],
                    }
                },
            },
        )
        response.raise_for_status()
        payload = response.json()
        refusal = payload.get("refusal")
        if refusal:
            raise RuntimeError(f"OpenAI triage refused the request: {refusal}")
        output_text = self._extract_output_text(payload)
        return LlmTriageDecision.model_validate_json(output_text)

    def _build_listing_prompt(
        self,
        *,
        event: RawListingEvent,
        stage_zero: TriageDecision,
        lot_analysis: LotAnalysis,
    ) -> str:
        return (
            "Evaluate whether this listing should advance to detail-page review.\n"
            f"Title: {event.title or ''}\n"
            f"Price: {event.price}\n"
            f"Location: {event.location_text or 'unknown'}\n"
            f"URL: {event.listing_url or 'unknown'}\n"
            f"Stage 0 accepted: {stage_zero.accepted}\n"
            f"Stage 0 reasons: {stage_zero.reasons}\n"
            f"Lot analysis says multi-item: {lot_analysis.is_multi_item}\n"
            f"Lot reasons: {lot_analysis.reasons}\n"
            "Decide if this is a real laptop or Mac mini resale candidate, note the likely "
            "family, obvious risks, and whether we should fetch the detail page."
        )

    def _extract_output_text(self, payload: dict[str, Any]) -> str:
        if isinstance(payload.get("output_text"), str) and payload["output_text"].strip():
            return payload["output_text"]

        for output in payload.get("output", []):
            for content in output.get("content", []):
                if content.get("type") == "output_text" and content.get("text"):
                    return content["text"]

        raise RuntimeError(
            f"Unable to extract structured triage text from response: {json.dumps(payload)}"
        )
