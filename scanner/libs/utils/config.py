from __future__ import annotations

import os
from dataclasses import dataclass


def _get_float(name: str, default: float) -> float:
    raw_value = os.getenv(name)
    if raw_value is None or raw_value == "":
        return default
    return float(raw_value)


def _get_int(name: str, default: int) -> int:
    raw_value = os.getenv(name)
    if raw_value is None or raw_value == "":
        return default
    return int(raw_value)


def _get_csv(name: str, default: tuple[str, ...]) -> tuple[str, ...]:
    raw_value = os.getenv(name)
    if raw_value is None or raw_value == "":
        return default
    return tuple(part.strip() for part in raw_value.split(",") if part.strip())


@dataclass(frozen=True)
class AppSettings:
    app_env: str
    database_url: str
    redis_url: str
    event_bus_backend: str
    event_bus_topic_prefix: str
    slack_webhook_url: str | None
    generic_webhook_url: str | None

    @classmethod
    def from_env(cls) -> AppSettings:
        return cls(
            app_env=os.getenv("APP_ENV", "development"),
            database_url=os.getenv(
                "DATABASE_URL",
                "sqlite+pysqlite:///:memory:",
            ),
            redis_url=os.getenv("REDIS_URL", "redis://localhost:6379/0"),
            event_bus_backend=os.getenv("EVENT_BUS_BACKEND", "inmemory"),
            event_bus_topic_prefix=os.getenv("EVENT_BUS_TOPIC_PREFIX", "scanner"),
            slack_webhook_url=os.getenv("SLACK_WEBHOOK_URL") or None,
            generic_webhook_url=os.getenv("GENERIC_WEBHOOK_URL") or None,
        )


@dataclass(frozen=True)
class EbaySettings:
    client_id: str | None
    client_secret: str | None
    oauth_token: str | None
    oauth_scopes: tuple[str, ...]
    detail_fieldgroups: tuple[str, ...]
    environment: str
    site_id: str
    end_user_context: str | None
    request_timeout_seconds: float
    page_size: int

    @classmethod
    def from_env(cls) -> EbaySettings:
        return cls(
            client_id=os.getenv("EBAY_CLIENT_ID") or os.getenv("EBAY_APP_ID") or None,
            client_secret=os.getenv("EBAY_CLIENT_SECRET") or None,
            oauth_token=os.getenv("EBAY_OAUTH_TOKEN") or None,
            oauth_scopes=_get_csv(
                "EBAY_OAUTH_SCOPES",
                ("https://api.ebay.com/oauth/api_scope",),
            ),
            detail_fieldgroups=_get_csv(
                "EBAY_DETAIL_FIELDGROUPS",
                ("PRODUCT", "ADDITIONAL_SELLER_DETAILS"),
            ),
            environment=os.getenv("EBAY_ENVIRONMENT", "production"),
            site_id=os.getenv("EBAY_SITE_ID", "EBAY_US"),
            end_user_context=os.getenv("EBAY_ENDUSER_CONTEXT") or None,
            request_timeout_seconds=_get_float("EBAY_REQUEST_TIMEOUT_SECONDS", 10.0),
            page_size=_get_int("EBAY_PAGE_SIZE", 25),
        )

    @property
    def identity_base_url(self) -> str:
        if self.environment == "sandbox":
            return "https://api.sandbox.ebay.com/identity/v1"
        return "https://api.ebay.com/identity/v1"

    @property
    def browse_base_url(self) -> str:
        if self.environment == "sandbox":
            return "https://api.sandbox.ebay.com/buy/browse/v1"
        return "https://api.ebay.com/buy/browse/v1"

    @property
    def has_application_token_material(self) -> bool:
        return bool(self.oauth_token or (self.client_id and self.client_secret))


@dataclass(frozen=True)
class PolicySettings:
    standard_alert_ev: float
    priority_alert_ev: float
    priority_action_score: float
    min_capture_probability: float

    @classmethod
    def from_env(cls) -> PolicySettings:
        return cls(
            standard_alert_ev=_get_float("ALERT_STANDARD_EV", 20.0),
            priority_alert_ev=_get_float("ALERT_PRIORITY_EV", 50.0),
            priority_action_score=_get_float("ALERT_PRIORITY_ACTION_SCORE", 65.0),
            min_capture_probability=_get_float("MIN_CAPTURE_PROBABILITY", 0.1),
        )
