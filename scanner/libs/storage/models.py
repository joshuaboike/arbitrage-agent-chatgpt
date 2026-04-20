from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class ListingModel(Base):
    __tablename__ = "listings"
    __table_args__ = (UniqueConstraint("source", "source_listing_id", name="uq_listing_source_id"),)

    listing_pk: Mapped[str] = mapped_column(String(64), primary_key=True)
    source: Mapped[str] = mapped_column(String(50), nullable=False)
    source_listing_id: Mapped[str] = mapped_column(String(255), nullable=False)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    price: Mapped[float | None] = mapped_column(Float, nullable=True)
    shipping_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    seller_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    geo_hash: Mapped[str | None] = mapped_column(String(32), nullable=True)
    title: Mapped[str | None] = mapped_column(String(500), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    currency: Mapped[str | None] = mapped_column(String(16), nullable=True)
    listing_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    raw_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    images: Mapped[list[ListingImageModel]] = relationship(
        back_populates="listing", cascade="all, delete-orphan"
    )
    underwriting_score: Mapped[UnderwritingScoreModel | None] = relationship(
        back_populates="listing", cascade="all, delete-orphan", uselist=False
    )


class ListingImageModel(Base):
    __tablename__ = "listing_images"

    image_pk: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    listing_pk: Mapped[str] = mapped_column(ForeignKey("listings.listing_pk"), nullable=False)
    image_url: Mapped[str] = mapped_column(String(1000), nullable=False)
    image_hash: Mapped[str | None] = mapped_column(String(128), nullable=True)
    perceptual_hash: Mapped[str | None] = mapped_column(String(128), nullable=True)
    embedding_vector: Mapped[list[float] | None] = mapped_column(JSON, nullable=True)

    listing: Mapped[ListingModel] = relationship(back_populates="images")


class AssetModel(Base):
    __tablename__ = "assets"

    asset_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    asset_family_id: Mapped[str] = mapped_column(String(100), nullable=False)
    brand: Mapped[str] = mapped_column(String(100), nullable=False)
    model: Mapped[str] = mapped_column(String(200), nullable=False)
    variant: Mapped[str | None] = mapped_column(String(200), nullable=True)
    taxonomy_path: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    spec_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)


class ListingAssetLinkModel(Base):
    __tablename__ = "listing_asset_links"

    link_pk: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    listing_pk: Mapped[str] = mapped_column(ForeignKey("listings.listing_pk"), nullable=False)
    asset_id: Mapped[str] = mapped_column(ForeignKey("assets.asset_id"), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    link_method: Mapped[str] = mapped_column(String(64), nullable=False)
    explanation_json: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)


class UnderwritingScoreModel(Base):
    __tablename__ = "underwriting_scores"

    underwriting_pk: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    listing_pk: Mapped[str] = mapped_column(
        ForeignKey("listings.listing_pk"), nullable=False, unique=True
    )
    condition_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    fraud_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    valuation_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    cost_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    capture_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    ev: Mapped[float] = mapped_column(Float, nullable=False)
    ev_lower: Mapped[float] = mapped_column(Float, nullable=False)
    ev_upper: Mapped[float] = mapped_column(Float, nullable=False)
    action_score: Mapped[float] = mapped_column(Float, nullable=False)
    route: Mapped[str] = mapped_column(String(32), nullable=False)
    model_version: Mapped[str] = mapped_column(String(64), nullable=False)
    scored_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )

    listing: Mapped[ListingModel] = relationship(back_populates="underwriting_score")


class CompModel(Base):
    __tablename__ = "comps"

    comp_pk: Mapped[str] = mapped_column(String(64), primary_key=True)
    asset_id: Mapped[str] = mapped_column(String(100), nullable=False)
    asset_family_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    channel: Mapped[str] = mapped_column(String(50), nullable=False)
    condition_bucket: Mapped[str] = mapped_column(String(8), nullable=False)
    sale_price: Mapped[float] = mapped_column(Float, nullable=False)
    sale_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    days_to_sell: Mapped[float] = mapped_column(Float, nullable=False)
    fees: Mapped[float] = mapped_column(Float, nullable=False)
    net_proceeds: Mapped[float] = mapped_column(Float, nullable=False)


class OutcomeModel(Base):
    __tablename__ = "outcomes"

    outcome_pk: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    listing_pk: Mapped[str] = mapped_column(ForeignKey("listings.listing_pk"), nullable=False)
    action_taken: Mapped[str] = mapped_column(String(50), nullable=False)
    won_flag: Mapped[bool] = mapped_column(Boolean, nullable=False)
    purchase_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    landed_cost: Mapped[float | None] = mapped_column(Float, nullable=True)
    inspection_grade: Mapped[str | None] = mapped_column(String(16), nullable=True)
    realized_exit_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    realized_profit: Mapped[float | None] = mapped_column(Float, nullable=True)
    return_flag: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    fraud_flag: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class SellerModel(Base):
    __tablename__ = "sellers"

    source: Mapped[str] = mapped_column(String(50), primary_key=True)
    seller_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    seller_features_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    historical_close_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    historical_issue_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
