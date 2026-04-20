# V1 Spec: Craigslist -> Laptops -> eBay Comps -> Telegram

## Goal

Build a narrow, cheap-to-run underwriting loop that can scan a large number of Craigslist listings, reject junk quickly, and send only the best laptop opportunities to Telegram for human review.

This v1 is intentionally opinionated:

- `source`: Craigslist
- `category`: laptops only
- `exit venue`: eBay comps
- `alert channel`: Telegram
- `review model`: one human operator reviewing the top alerts
- `learning loop`: required from day one

## Product Shape

The system should answer these questions in order:

1. Should we ignore this listing immediately?
2. Is it likely a real laptop opportunity worth deeper review?
3. Does the full listing plus photos still look viable?
4. Is it likely positive EV after costs and risk?
5. Is it worth human attention right now?

## Acquisition

Poll overlapping Craigslist searches every 3-5 minutes with jitter.

Start with 8 anchor ZIP codes:

- `10001` New York
- `20001` Washington, DC
- `30303` Atlanta
- `60601` Chicago
- `75201` Dallas
- `80202` Denver
- `90012` Los Angeles
- `98101` Seattle

Use:

- category: `sya`
- `delivery_available=1`
- `search_distance=500` initially
- move to `1000` after quality is validated

Broad query:

```text
(macbook|thinkpad|xps|latitude|"surface laptop"|elitebook|zenbook|spectre) -parts -repair -broken -wanted -service
```

At poll time, collect card-level fields only:

- `source_listing_id`
- `url`
- `title`
- `price`
- `posted_at`
- `location_text`
- `anchor_zip`
- `observed_at`

Do not use OCR for ingestion. Parse the rendered page or DOM directly. Screenshots are only for QA/debugging when selectors drift.

## Funnel

### Stage 0: Free Rejects

Reject before any model call if:

- title or URL is missing
- Craigslist post ID already exists
- normalized title + rounded price was seen recently
- price is below `80` or above `2500`
- title contains hard negatives:
  - `wanted`
  - `repair`
  - `service`
  - `parts`
  - `trade`
  - `lease`
  - `financing`
- title lacks a laptop-family token
- listing falls into a repost cooling window

Every reject should be logged with a deterministic reason.

### Stage 1: Cheap LLM Text Triage

Run a cheap LLM on every Stage 0 survivor.

Inputs:

- title
- price
- location
- age
- source
- category
- short snippet if visible

Required structured output:

```json
{
  "is_candidate": true,
  "item_type": "laptop",
  "brand": "Apple",
  "family": "MacBook Pro",
  "variant_hint": "14-inch M1 Pro",
  "condition_guess": "used_good",
  "risk_flags": ["possible low-spec ambiguity"],
  "needs_detail_fetch": true,
  "triage_score": 0.82,
  "confidence": 0.78,
  "reason": "Looks like a real resale-grade laptop listing with plausible price"
}
```

The model should decide:

- is this probably a laptop listing?
- is it likely resale-grade?
- is it likely worth deeper review?
- what family is most likely?
- what obvious risks are visible from text only?

The model should be conservative but should not reject potentially profitable laptops just because specs are incomplete.

### Stage 2: Detail Fetch Gate

For each listing where `needs_detail_fetch=true`:

- fetch the detail page
- parse the full description
- extract fulfillment signals
- decide whether the listing is eligible for photo download

Hard exclusion:

- if the detail page says `pickup only`, reject immediately

Preferred keep signals:

- `delivery available`
- `shipping available`
- equivalent shippable language

If fulfillment is unknown:

- mark `fulfillment_unknown`
- either reject or place into a low-priority bucket

This exclusion should be logged explicitly as:

- `exclusion_reason = pickup_only`

### Stage 3: Download and Review All Photos

Only for listings that pass the detail gate:

- download all photos
- hash every photo
- store photo metadata and local/object paths
- do not redownload known image URLs or hashes

Per-listing safeguards:

- cap at `10` photos for v1
- skip huge images after a size threshold
- cache image-review outputs by image hash

Photo reviewer output contract:

```json
{
  "photo_quality_score": 0.71,
  "device_visibility_score": 0.88,
  "damage_flags": ["lid wear", "keyboard shine"],
  "accessory_flags": ["charger_visible"],
  "fraud_flags": ["possible stock_photo_match"],
  "mismatch_flags": [],
  "condition_band": "B/C",
  "confidence": 0.69
}
```

Photo review should look for:

- cracks
- dents
- keyboard wear
- hinge damage
- charger visibility
- stock-photo suspicion
- blurry or low-information images
- text/image mismatch

## Underwriting

Combine:

- card text
- full description
- photo review
- laptop taxonomy
- cached eBay priors

Output:

- canonical family
- likely specs
- underwriting confidence
- condition/risk flags
- expected landed cost
- fast-sale exit
- median exit
- `EV`
- `EV_lower`
- `ActionScore`

V1 can use rule-based extraction plus a cheap LLM-backed identity pass. It does not need a full ML stack.

## Comp Engine

Do not hit eBay live for every Craigslist listing.

Maintain cached comp priors by:

- `brand`
- `family`
- `variant`
- `condition_bucket`

Store:

- `fast_sale`
- `median_sale`
- `comp_count_30d`
- `days_to_sell_proxy`

Refresh eBay priors on a schedule, then use local lookup during underwriting.

## Caching

Cache aggressively:

- page fetches by URL and minute bucket
- Stage 1 LLM outputs by normalized card fingerprint
- downloaded images by URL
- image reviews by image hash
- comp lookups by family/variant/condition
- final underwriting by listing fingerprint

Fingerprint examples:

- card fingerprint: normalized title + rounded price + source listing ID
- listing fingerprint: title + description + sorted image hashes

## Alerting

Send Telegram alerts only when:

- `EV_lower > 40`
- `ActionScore > 55`
- underwriting confidence `> 0.72`
- no hard fraud flag
- listing is not duplicate/relist spam

Priority alert when:

- `EV_lower > 100`
- `ActionScore > 75`
- underwriting confidence `> 0.82`

Daily guardrail:

- hard cap at `20` alerts per day

Telegram payload should include:

- title
- price
- source
- location
- estimated fast exit
- estimated landed cost
- `EV`
- `EV_lower`
- `ActionScore`
- confidence
- key risks
- why it matters
- listing URL

Example:

```json
{
  "title": "MacBook Pro 14 M1 Pro 16GB 1TB",
  "price": 850,
  "source": "craigslist",
  "location": "Brooklyn",
  "estimated_exit_fast": 1180,
  "estimated_landed_cost": 960,
  "ev": 220,
  "ev_lower": 105,
  "action_score": 77,
  "confidence": 0.84,
  "risks": ["possible battery wear"],
  "why": [
    "priced below cached fast-sale baseline",
    "high-liquidity family",
    "charger appears included"
  ],
  "listing_url": "...",
  "review_action": "open"
}
```

## Minimum Tables

Start with:

- `search_hits`
- `listings`
- `listing_images`
- `triage_results`
- `underwriting_results`
- `alerts`
- `operator_labels`

Operator labels:

- `ignore`
- `interesting`
- `contacted`
- `bought`
- `false_positive`
- `missed`

## Success Metrics

The first two weeks should answer:

- are we finding real laptops at scale?
- what percentage survive Stage 0?
- what percentage survive Stage 1?
- what percentage survive the detail gate?
- what percentage survive photo review?
- how many Telegram alerts are actually worth review?
- which errors dominate: identity, condition, pricing, or fulfillment?

## Build Order

Ship in this order:

1. Craigslist DOM poller
2. Stage 0 deterministic filters
3. Stage 1 cheap LLM JSON triage
4. detail fetch and fulfillment gate
5. photo download and cached review
6. cached eBay priors
7. Telegram alert delivery
8. operator labeling and outcome tracking

## Non-Goals for V1

Do not expand into these yet:

- dozens of sources
- all electronics
- full automation
- expensive multimodal models on every listing
- complex distributed infrastructure
- perfect demand forecasting

The point of v1 is to prove the funnel has life, not to look complete.
