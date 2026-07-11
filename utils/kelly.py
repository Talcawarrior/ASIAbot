"""Kelly criterion math, shared by engine.calculator and engine.strategy.

Two callers existed with the same formula but different parameter names
and slightly different edges (calculator returned a raw fraction, strategy
returned a dollar amount with min/max clamps). That was a code-review
finding (#5) and a maintenance trap: if you ever wanted to add a "min
odds for Kelly" or a different fraction formula, you had to remember to
fix it in two places.

The math (William Poundstone / Kelly 1956):
    f* = (b p - q) / b
    where b = net odds (decimal-odds minus 1), p = model probability of
    winning, q = 1 - p.

For a Polymarket binary market at price `m` (between 0 and 1, where 1 - m
is the implied win payout), the decimal odds on the YES side are
1 / m, so the net odds are b = (1 / m) - 1 = (1 - m) / m. We expose
both shapes via two pure functions:

    kelly_fraction(prob, price)         -> float in [0, 1]
        The pure f* fraction (no bankroll scaling, no min/max).

    kelly_bet_amount(portfolio, prob,
                     price, *,
                     fraction=0.15,
                     min_bet=1.0,
                     max_bet_pct=0.03) -> float dollars
        The strategy helper: portfolio_value * kelly_fraction,
        floored at min_bet, capped at max_bet_pct * portfolio_value.

EV FIX ( yüksek EV'ye yüksek bet, düşük EV'ye düşük bet ):
    dynamic_max_bet_pct(edge) ve dynamic_kelly_fraction(edge) fonksiyonları
    eklendi. Edge band'ine göre cap ve fraction dinamik olarak ayarlanır,
    böylece yüksek EV'li (edge > %20) bet'ler daha büyük, düşük EV'li
    (edge ~ %5-10) bet'ler daha küçük açılır. Sabit %3 cap yüksek EV'yi
    sınırlamıyordu (örn. edge %30 ve edge %10 aynı $29.70'a yapışıyordu).

Both functions are pure (no DB, no logging) and are safe to call from
either sync (calculator.analyze_market) or async (risk manager) paths.
"""

from __future__ import annotations


# EV FIX: Edge band'ine göre dinamik max_bet_pct ve kelly_fraction.
# Eski sabit %3 cap yüksek EV'yi sınırlıyordu — edge %30 ile %10 aynı
# $29.70 bet'i açıyordu ($1000 portföyde). Artık yüksek EV daha büyük bet.
#
# Edge band'leri:
#   edge >= 0.20  → max_bet_pct=0.05, kelly_fraction=0.25 (quarter Kelly, agresif)
#   edge >= 0.10  → max_bet_pct=0.03, kelly_fraction=0.15 (sub-quarter, standart)
#   edge >= 0.05  → max_bet_pct=0.02, kelly_fraction=0.10 (daha保守)
#   edge < 0.05   → should_bet=False (zaten min_edge filtresi engeller)
def dynamic_max_bet_pct(edge: float, base_pct: float = 0.006) -> float:
    """EV FIX: Edge band'ine göre dinamik max_bet_pct döndür.

    Yüksek edge → yüksek cap, düşük edge → düşük cap.
    Bu sayede yüksek EV'li bahisler daha büyük, düşük EV'li bahisler
    daha küçük açılır. Sabit %3 cap yüksek EV'yi sınırlıyordu.

    Parameters
    ----------
    edge : float
        Net edge (model_prob - market_price), 0.0-1.0 arası.
    base_pct : float
        Base max_bet_pct (default 0.006 = %0.6). Yüksek edge band'inde
        bu değerin üstüne çıkılır.

    Returns
    -------
    float
        Dinamik max_bet_pct değeri.
    """
    if edge >= 0.20:
        return 0.05  # %5 — yüksek EV'ye izin ver
    if edge >= 0.10:
        return base_pct  # base_pct — standart
    return base_pct * 0.5  # %0.3 — düşük EV'de daha保守


def dynamic_kelly_fraction(edge: float, base_fraction: float = 0.15) -> float:
    """EV FIX: Edge band'ine göre dinamik kelly_fraction döndür.

    Yüksek edge → daha agresif Kelly fraction (quarter Kelly),
    düşük edge → daha保守 fraction.

    Parameters
    ----------
    edge : float
        Net edge (model_prob - market_price), 0.0-1.0 arası.
    base_fraction : float
        Base kelly_fraction (default 0.15 = sub-quarter Kelly).

    Returns
    -------
    float
        Dinamik kelly_fraction değeri [0.05, 0.25] aralığında.
    """
    if edge >= 0.20:
        return 0.25  # quarter Kelly — yüksek conviction
    if edge >= 0.10:
        return base_fraction  # sub-quarter — standart
    return 0.10  # daha保守


def kelly_fraction(prob: float, price: float) -> float:
    """Return the pure Kelly fraction f* for a binary bet.

    Parameters
    ----------
    prob : float
        Model probability of the bet winning (0, 1).
    price : float
        Current market price of the bet (0, 1). For YES this is the YES
        price; for NO use the NO price (1 - yes_price). The decimal odds
        are taken as 1 / price.

    Returns
    -------
    float
        The f* fraction of bankroll recommended. Returns 0.0 for any
        nonsensical input (negative or out-of-range prob/price) or for
        bets where Kelly says "do not bet" (f* <= 0).
    """
    if prob <= 0 or prob >= 1:
        return 0.0
    if price <= 0 or price >= 1:
        return 0.0

    # Net decimal odds on a $1 stake.
    b = (1.0 / price) - 1.0
    if b <= 0:
        return 0.0

    q = 1.0 - prob
    f_star = (b * prob - q) / b
    if f_star <= 0:
        return 0.0
    return f_star


def kelly_bet_amount(
    portfolio_value: float,
    prob: float,
    price: float,
    *,
    fraction: float = 0.15,
    min_bet: float = 1.0,
    max_bet_pct: float = 0.006,
    edge: float | None = None,
) -> float:
    """Compute a Kelly-sized dollar bet for the given portfolio.

    Wraps :func:`kelly_fraction` with the safety bounds used by the
    engine (fractional Kelly + min bet + max bet cap). Returns 0.0 when
    Kelly says "no bet" or the input is invalid.

    EV FIX: Eğer `edge` parametresi verilirse, dinamik max_bet_pct ve
    kelly_fraction kullanılır. Yüksek edge → yüksek bet, düşük edge →
    düşük bet. Bu sayede EV'ye orantılı sizing restore edilir.

    Parameters
    ----------
    portfolio_value : float
        Current total portfolio value (cash + unrealized PnL) in dollars.
    prob, price, fraction, min_bet, max_bet_pct
        See :func:`kelly_fraction` plus the per-bet floor and cap.
    edge : float | None
        Net edge (model_prob - market_price). Verilirse dinamik sizing
        aktif olur; None ise eski sabit davranış korunur.
    """
    if portfolio_value <= 0:
        return 0.0

    # EV FIX: Edge verilirse dinamik sizing kullan
    if edge is not None and edge > 0:
        fraction = dynamic_kelly_fraction(edge, fraction)
        max_bet_pct = dynamic_max_bet_pct(edge, max_bet_pct)

    f_star = kelly_fraction(prob, price)
    if f_star <= 0:
        return 0.0

    fractional = f_star * fraction
    if fractional <= 0:
        return 0.0

    amount = portfolio_value * fractional
    # EV FIX: min_bet floor sadece Kelly zaten min_bet'e yakınsa uygulanır.
    # Eski davranış: Kelly $0.10 önerse bile $1.0'e yapışıyordu (over-betting).
    # Yeni: Kelly < min_bet/2 ise bet açma (return 0), yoksa min_bet uygula.
    if amount < min_bet * 0.5:
        return 0.0  # Kelly çok düşük — bet açma
    amount = max(amount, min_bet)

    max_amount = portfolio_value * max_bet_pct
    amount = min(amount, max_amount)
    # EV FIX: Final cap sonrası da min_bet/2 altındaysa bet açma
    if amount < min_bet * 0.5:
        return 0.0
    return round(amount, 2)
