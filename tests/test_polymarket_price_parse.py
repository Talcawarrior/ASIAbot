"""Regression tests for YES/NO price parsing (binary-market invariant).

Background: a bug let ``_parse_market`` store impossible price pairs such as
yes=0.75 / no=0.75 (sum 1.5) for binary markets, because it trusted stale /
illiquid token quotes over Polymarket's canonical ``outcomePrices`` feed and
never enforced YES + NO ~= 1.0. That corrupted ~668/681 open markets and made
the bot skip or misprice trades. These tests lock the corrected behaviour so
the regression is caught automatically if it ever slips back in.
"""

import pytest

from scrapers.polymarket import PolymarketScraper


@pytest.fixture
def scraper():
    return PolymarketScraper()


def _binary(outcome_prices=None, tokens=None, outcomes=("Yes", "No")):
    raw = {
        "id": "2968832",
        "question": "Will the highest temperature in Madrid be 36C on July 20?",
        "outcomes": list(outcomes),
    }
    if outcome_prices is not None:
        raw["outcomePrices"] = outcome_prices
    if tokens is not None:
        raw["tokens"] = tokens
    return raw


def test_outcome_prices_preferred_over_stale_token_quotes(scraper):
    """Canonical outcomePrices must win over illiquid token mid-quotes."""
    raw = _binary(
        outcome_prices='["0.72", "0.28"]',
        tokens=[
            {"outcome": "YES", "price": 0.75},
            {"outcome": "NO", "price": 0.75},
        ],
    )
    p = scraper._parse_market(raw)
    assert p["yes_price"] == pytest.approx(0.72)
    assert p["no_price"] == pytest.approx(0.28)


def test_binary_invariant_corrects_impossible_pair(scraper):
    """When YES+NO != ~1 (e.g. 0.75/0.75), NO must be derived as 1-YES."""
    raw = _binary(
        tokens=[
            {"outcome": "YES", "price": 0.75},
            {"outcome": "NO", "price": 0.75},
        ],
    )
    p = scraper._parse_market(raw)
    assert p["yes_price"] == pytest.approx(0.75)
    assert p["no_price"] == pytest.approx(0.25)
    assert abs(p["yes_price"] + p["no_price"] - 1.0) <= 0.02


def test_valid_pair_passthrough(scraper):
    raw = _binary(outcome_prices='["0.40", "0.60"]')
    p = scraper._parse_market(raw)
    assert p["yes_price"] == pytest.approx(0.40)
    assert p["no_price"] == pytest.approx(0.60)


def test_empty_tokens_fall_back_to_outcome_prices(scraper):
    """Reproduces market 2968832: tokens empty, only outcomePrices present."""
    raw = _binary(outcome_prices='["0.72", "0.28"]', tokens=[])
    p = scraper._parse_market(raw)
    assert p["yes_price"] == pytest.approx(0.72)
    assert p["no_price"] == pytest.approx(0.28)


@pytest.mark.parametrize(
    "yes,no",
    [
        (0.75, 0.75),
        (0.002, 0.001),
        (0.979, 0.963),
        (0.50, 0.70),
    ],
)
def test_binary_parser_never_returns_invalid_pair(scraper, yes, no):
    """Invariant lock: a binary market must always parse to YES+NO~=1."""
    raw = _binary(
        tokens=[
            {"outcome": "YES", "price": yes},
            {"outcome": "NO", "price": no},
        ],
    )
    p = scraper._parse_market(raw)
    assert abs(p["yes_price"] + p["no_price"] - 1.0) <= 0.02
