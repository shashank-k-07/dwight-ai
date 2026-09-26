"""Pricing from data/prices.yaml. Spend is always tokens x price (ADR 0006).

Token semantics follow OTel GenAI: input_tokens includes cache-read and
cache-write tokens.
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import yaml

from dwight import config

PER = 1_000_000


@dataclass(frozen=True)
class ModelPrice:
    model: str
    tier: str
    input: float       # USD per 1M uncached input tokens
    cache_read: float  # USD per 1M cache-read input tokens
    cache_write: float # USD per 1M cache-write input tokens
    output: float      # USD per 1M output tokens


class UnknownModel(KeyError):
    pass


@lru_cache(maxsize=4)
def _table(path: str) -> dict:
    return yaml.safe_load(Path(path).read_text())


def table(path: Path | None = None) -> dict:
    return _table(str(path or config.PRICES_PATH))


def normalise_model(model: str) -> str:
    """Lower-case, apply aliases, and reduce a provider path such as Sciforium's
    '/deployments/<id>/deepseek-ai/DeepSeek-V4.1-Flash' to its last segment."""
    m = model.strip().lower()
    aliases = table().get("aliases") or {}
    m = aliases.get(m, m)
    if m not in (table().get("models") or {}) and "/" in m:
        tail = m.rsplit("/", 1)[1]
        m = aliases.get(tail, tail)
    return m


def price(model: str) -> ModelPrice:
    m = normalise_model(model)
    entry = (table().get("models") or {}).get(m)
    if entry is None:
        raise UnknownModel(f"model {model!r} is not in {config.PRICES_PATH}; add its list price")
    return ModelPrice(model=m, tier=entry["tier"], input=entry["input"],
                      cache_read=entry["cache_read"], cache_write=entry["cache_write"],
                      output=entry["output"])


def call_spend(model: str, input_tokens: int, output_tokens: int,
               cache_read_tokens: int = 0, cache_write_tokens: int = 0) -> float:
    """USD Spend of one Call. Measured."""
    p = price(model)
    uncached = max(input_tokens - cache_read_tokens - cache_write_tokens, 0)
    return (uncached * p.input + cache_read_tokens * p.cache_read
            + cache_write_tokens * p.cache_write + output_tokens * p.output) / PER


def input_rate(model: str, cached: bool) -> float:
    """USD per single input token, uncached or cache-read. For detectors / common paths
    that price 'the input rate that Call actually paid'."""
    p = price(model)
    return (p.cache_read if cached else p.input) / PER


def cheaper_model(model: str) -> str | None:
    """Model a Session on `model` is re-priced at for Model Overkill (None if already cheapest)."""
    p = price(model)
    return (table().get("cheaper_tier_model") or {}).get(p.tier)
