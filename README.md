# Scanner

`scanner` is a production-oriented v1 for underwriting and alerting on electronics listings. The repository is organized as a Python monorepo with typed libraries, worker entrypoints, a FastAPI control plane, SQLAlchemy models, Alembic migrations, and pytest coverage for the first underwriting path.

## Product scope

The system is optimized for captureable expected value rather than raw spread. v1 focuses on:

- source ingestion through a pluggable connector abstraction
- Craigslist anchor-search generation for overlapping metros
- canonical `RawListingEvent` normalization
- deterministic triage and detail-page fulfillment gating
- rule-based entity resolution into seeded asset families and assets
- text-first condition and fraud heuristics
- baseline valuation using exact and family-level comps
- EV and `ActionScore` computation with threshold routing
- alert formatting for Slack and generic webhooks
- outcome logging hooks for future learning

## Repo layout

```text
scanner/
  apps/
    api/
    worker_alerts/
    worker_ingest/
    worker_normalize/
    worker_underwrite/
  libs/
    connectors/
    events/
    metrics/
    nlp/
    policy/
    schemas/
    services/
    storage/
    taxonomy/
    utils/
    valuation/
alembic/
tests/
```

## Local setup

1. Copy `.env.example` to `.env` and adjust secrets and URLs.
2. Install dependencies:

```bash
make setup
```

3. Start local infrastructure:

```bash
docker compose up -d postgres redis redpanda
```

4. Run database migrations:

```bash
alembic upgrade head
```

5. Start the API:

```bash
make run-api
```

6. Preview the generated Craigslist anchor searches:

```bash
curl "http://127.0.0.1:8000/sources/craigslist/searches"
```

## eBay connector setup

The eBay connector now supports a real Browse read path. Configure either:

- `EBAY_CLIENT_ID` and `EBAY_CLIENT_SECRET` so the app can mint an Application access token, or
- `EBAY_OAUTH_TOKEN` if you already have a short-lived Application token

Optional controls:

- `EBAY_ENVIRONMENT=sandbox` for sandbox testing
- `EBAY_SITE_ID=EBAY_US` to choose the marketplace header
- `EBAY_DETAIL_FIELDGROUPS=PRODUCT,ADDITIONAL_SELLER_DETAILS` to control `getItem` hydration
- `EBAY_HYDRATE_DETAILS=true` to have `worker_ingest` enrich search results with `getItem`

Quick smoke tests:

```bash
make run-api
curl "http://127.0.0.1:8000/sources/ebay/search?q=iphone%2015%20pro&hydrate_details=true"
```

```bash
EBAY_QUERY="macbook pro 14" make run-ingest
```

## API endpoints

- `GET /health`
- `GET /alerts/recent`
- `GET /sources/craigslist/searches`
- `GET /sources/ebay/search`
- `GET /listings/{listing_id}`
- `GET /underwriting/{listing_id}`
- `POST /listings/test-ingest`

## Test suite

```bash
make test
```

The included tests cover normalization, rule-based entity extraction, valuation behavior, and policy routing.
