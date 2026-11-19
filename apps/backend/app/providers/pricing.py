"""API price table (plan §4.3). Costs are estimates from `pricing.yaml`; a model missing from the
table gets no cost (None), never a guessed one."""

from collections.abc import Callable
from decimal import Decimal
from pathlib import Path
from typing import Any

import yaml

PRICING_FILE = Path(__file__).with_name("pricing.yaml")
_PER_MILLION = Decimal(1_000_000)


class Pricing:
    def __init__(self, data: dict[str, Any]) -> None:
        self.last_verified: str | None = data.get("last_verified")
        self._models: dict[str, dict[str, Any]] = data.get("models") or {}
        # For models missing from the table: (input, output) USD per million tokens from the
        # models.dev catalog. Still None (no cost) when the catalog does not know the model.
        self.fallback: Callable[[str, str], tuple[Decimal, Decimal] | None] | None = None

    @classmethod
    def load(cls, path: Path = PRICING_FILE) -> "Pricing":
        return cls(yaml.safe_load(path.read_text(encoding="utf-8")) or {})

    def cost(
        self, provider: str, model: str, input_tokens: int | None, output_tokens: int | None
    ) -> Decimal | None:
        if input_tokens is None or output_tokens is None:
            return None
        price = self._models.get(f"{provider}/{model}")
        if price is None:
            found = self.fallback(provider, model) if self.fallback else None
            if found is None:
                return None
            return (found[0] * input_tokens + found[1] * output_tokens) / _PER_MILLION
        return (
            Decimal(str(price["input_per_mtok"])) * input_tokens
            + Decimal(str(price["output_per_mtok"])) * output_tokens
        ) / _PER_MILLION
