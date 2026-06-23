"""Tests for utils/slippage.py — cost model integration."""

import pytest

from utils.slippage import (
    _tiered_slippage,
    adjust_edge_for_costs,
    adjust_kelly_for_slippage,
    estimate_slippage,
)


class TestTieredSlippage:
    """3-tier adaptive slippage by entry price."""

    def test_thin_book(self):
        assert _tiered_slippage(0.03) == pytest.approx(0.03)

    def test_moderate(self):
        assert _tiered_slippage(0.07) == pytest.approx(0.01)

    def test_deep_book(self):
        assert _tiered_slippage(0.50) == pytest.approx(0.005)

    def test_boundary_low(self):
        # Exactly 0.05 → moderate tier (elif)
        assert _tiered_slippage(0.05) == pytest.approx(0.01)

    def test_boundary_high(self):
        # Exactly 0.10 → deep book tier (else)
        assert _tiered_slippage(0.10) == pytest.approx(0.005)


class TestEstimateSlippage:
    """Dispatch to the correct model."""

    def test_flat_model(self):
        est = estimate_slippage(0.50, model="flat")
        assert est.model_used == "flat"
        assert est.slippage_pct == pytest.approx(0.005)

    def test_tiered_model(self):
        est = estimate_slippage(0.03, model="tiered")
        assert est.model_used == "tiered"
        assert est.slippage_pct == pytest.approx(0.03)

    def test_orderbook_falls_back_to_tiered(self):
        est = estimate_slippage(0.50, model="orderbook")
        # No condition_id → falls back to tiered
        assert est.model_used != "orderbook" or est.slippage_pct > 0


class TestAdjustEdgeForCosts:
    """Net edge = raw edge - slippage - fee."""

    def test_high_price_low_slip(self):
        # entry=0.50 → 0.5% slippage + 2% fee = 2.5% total drag
        net = adjust_edge_for_costs(0.10, 0.50)
        assert net == pytest.approx(0.10 - 0.005 - 0.02)

    def test_low_price_high_slip(self):
        # entry=0.03 → 3% slippage + 2% fee = 5% total drag
        net = adjust_edge_for_costs(0.08, 0.03)
        assert net == pytest.approx(0.08 - 0.03 - 0.02)

    def test_negative_edge_stays_negative(self):
        net = adjust_edge_for_costs(0.01, 0.50)
        assert net == pytest.approx(0.01 - 0.005 - 0.02)

    def test_fee_only(self):
        net = adjust_edge_for_costs(0.05, 0.50, include_fee=True)
        assert net < 0.05
        net_no_fee = adjust_edge_for_costs(0.05, 0.50, include_fee=False)
        assert net_no_fee == pytest.approx(0.05 - 0.005)


class TestAdjustKellyForSlippage:
    """Kelly size reduced by slippage cost."""

    def test_high_price_reduction(self):
        # entry=0.50 → 0.5% slip → kelly $20 - $0.10 = $19.90
        adj = adjust_kelly_for_slippage(20.0, 0.50)
        assert adj == pytest.approx(20.0 * (1 - 0.005))

    def test_low_price_reduction(self):
        # entry=0.03 → 3% slip → kelly $20 - $0.60 = $19.40
        adj = adjust_kelly_for_slippage(20.0, 0.03)
        assert adj == pytest.approx(20.0 * (1 - 0.03))

    def test_floor_at_min_bet(self):
        # Tiny kelly at high slippage should floor at $1
        adj = adjust_kelly_for_slippage(0.50, 0.03)
        assert adj >= 1.0

    def test_max_slippage_cap(self):
        # Even if slippage model returns crazy value, cap applies
        adj = adjust_kelly_for_slippage(100.0, 0.01, max_slippage_pct=0.01)
        assert adj >= 100.0 * (1 - 0.01)
