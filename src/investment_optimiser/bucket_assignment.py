from dataclasses import dataclass
from typing import Literal, Optional

Method = Literal["override", "derived_metadata", "name_keywords", "asset_type_fallback", "catch_all"]

SYMBOL_OVERRIDES: dict[str, str] = {}

_ASSET_TYPE_FALLBACKS: dict[str, str] = {
    "equity": "listed_risk_assets",
    "etf": "listed_risk_assets",
    "investment_trust": "listed_risk_assets",
    "gilt_conventional": "long_duration_nominal_gilts",
    "reit": "diversifiers_and_manual",
    "fund": "diversifiers_and_manual",
    "other": "diversifiers_and_manual",
}

# Asset types that cannot be classified by type alone — name keywords must be tried first.
_AMBIGUOUS_ASSET_TYPES = {"etf", "fund", "investment_trust", "other"}

# Keyword groups checked in priority order within _resolve_name_keywords.
_KEYWORD_GROUPS: list[tuple[list[str], str]] = [
    (["infrastructure", "property", "real estate", "reit", "commodity",
      "gold", "silver", "natural resource", "absolute return", "hedge"],
     "diversifiers_and_manual"),
    (["index-linked", "index linked", "linker", "inflation-linked", "inflation linked"],
     "index_linked_gilts"),
    (["gilt", "government bond", "uk bond"],
     "long_duration_nominal_gilts"),
    (["money market", "cash fund", "liquidity", "ultra short"],
     "liquidity_reserve"),
    (["equity", "equities", "shares", "stock"],
     "listed_risk_assets"),
]


@dataclass(frozen=True)
class BucketResolution:
    bucket_id: str
    method: Method


def _resolve_explicit_override(row: dict) -> Optional[BucketResolution]:
    bucket = SYMBOL_OVERRIDES.get(row.get("symbol", ""))
    if bucket:
        return BucketResolution(bucket_id=bucket, method="override")
    return None


def _resolve_derived_metadata(row: dict) -> Optional[BucketResolution]:
    asset_type = row.get("asset_type", "")
    if asset_type == "mmf":
        return BucketResolution(bucket_id="liquidity_reserve", method="derived_metadata")
    if asset_type == "gilt_index_linked":
        return BucketResolution(bucket_id="index_linked_gilts", method="derived_metadata")
    if asset_type == "gilt_conventional":
        maturity = row.get("maturity_years")
        if maturity is not None:
            bucket = "short_duration_nominal_gilts" if maturity <= 5.0 else "long_duration_nominal_gilts"
            return BucketResolution(bucket_id=bucket, method="derived_metadata")
    return None


def _resolve_name_keywords(row: dict) -> Optional[BucketResolution]:
    if row.get("asset_type") not in _AMBIGUOUS_ASSET_TYPES:
        return None
    name = row.get("instrument_name", "").lower()
    if not name:
        return None
    for keywords, bucket_id in _KEYWORD_GROUPS:
        if any(kw in name for kw in keywords):
            return BucketResolution(bucket_id=bucket_id, method="name_keywords")
    return None


def _resolve_asset_type_fallback(row: dict) -> Optional[BucketResolution]:
    bucket = _ASSET_TYPE_FALLBACKS.get(row.get("asset_type", ""))
    if bucket:
        return BucketResolution(bucket_id=bucket, method="asset_type_fallback")
    return None


_RESOLVERS = [
    _resolve_explicit_override,
    _resolve_derived_metadata,
    _resolve_name_keywords,
    _resolve_asset_type_fallback,
]


def assign_bucket(row: dict) -> BucketResolution:
    for resolver in _RESOLVERS:
        result = resolver(row)
        if result is not None:
            return result
    return BucketResolution(bucket_id="diversifiers_and_manual", method="catch_all")
