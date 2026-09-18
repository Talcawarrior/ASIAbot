"""Structured bet decision result — single return type for all gate checks."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("BET_DECISION")


@dataclass
class BetDecision:
    """Captures the full decision path for a single bet evaluation.

    Every gate in the bet pipeline populates this object so that:
    - A single JSON log line records WHY a bet was placed or rejected.
    - The dashboard/API can expose the decision tree for debugging.
    - Gate pass/fail history is available for analytics.

    Usage::

        d = BetDecision(market_id="nyc-temp")
        d.check("price_valid", is_valid_binary_price(yes, no))
        d.check("min_entry", price >= min_entry_price)
        d.check("exposure", exposure_ok)
        if not d.should_bet:
            d.log()  # single structured JSON log
    """

    market_id: str = ""
    should_bet: bool = True
    rejected_reason: str = ""
    city: str = ""
    gates: dict[str, bool] = field(default_factory=dict)
    params: dict[str, Any] = field(default_factory=dict)
    proposed_amount: float = 0.0
    final_amount: float = 0.0

    def check(self, gate_name: str, passed: bool, **kwargs: Any) -> None:
        """Record a gate check. If it fails, mark as rejected."""
        self.gates[gate_name] = passed
        for k, v in kwargs.items():
            self.params[f"{gate_name}.{k}"] = v
        if not passed and self.should_bet:
            self.should_bet = False
            self.rejected_reason = gate_name

    def set_param(self, key: str, value: Any) -> None:
        """Set a diagnostic parameter (not a gate)."""
        self.params[key] = value

    def log(self, level: int = logging.INFO) -> None:
        """Emit a single structured JSON log line."""
        data = {
            "event": "bet_decision",
            "market_id": self.market_id,
            "should_bet": self.should_bet,
            "rejected_reason": self.rejected_reason or None,
            "gates": self.gates,
            "params": self.params,
            "proposed_amount": self.proposed_amount,
            "final_amount": self.final_amount,
        }
        logger.log(level, json.dumps(data, default=str))
        # Dashboard aktivite akisi: her karar tek satir (bet_opened / bet_blocked).
        try:
            from utils.activity_log import log_event

            if self.should_bet:
                side = self.params.get("side", "")
                amt = self.final_amount or self.proposed_amount
                log_event("bet_opened", self.city or None, f"{self.market_id} | {side} ${amt:.2f}")
            else:
                log_event("bet_blocked", self.city or None, f"{self.market_id} | {self.rejected_reason}")
        except Exception:
            pass
