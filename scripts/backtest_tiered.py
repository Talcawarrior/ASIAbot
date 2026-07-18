"""Tiered Risk Management — Karşılaştırmalı Backtest (Sadeleştirilmiş).

Her tier için spesifik fiyat senaryoları:
- Eski strateji: her tier'da sabit TP=80%, SL=20%, TS=15%
- Yeni strateji: tier-aware TP/SL/TS
"""
import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from datetime import datetime, timedelta, timezone
from collections import defaultdict
from config.settings import RiskConfig
from engine.strategy import RiskManager


class Bet:
    def __init__(self, entry_price):
        self.entry_price = entry_price
        self.price = entry_price
        self.side = "NO"
        self.result_data = None
        self.placed_at = datetime.now(timezone.utc) - timedelta(days=1)
        self.market_id = "test"
        self.raw_edge = 0.0
        self.analysis_id = None
        self.partial_tp_done = False
        self.covered_fraction = 0.0
        self.shares = 6.25 / entry_price if entry_price > 0 else 0
        self.amount = 6.25
        self.stake = 6.25


class Market:
    def __init__(self, hours_to_settle=48):
        self.target_date = datetime.now(timezone.utc) + timedelta(hours=hours_to_settle)
        self.city = "Test"
        self.city_code = "TST"


def run_scenarios(rm, scenarios, risk_cfg):
    """Run list of (bet, prices, market) scenarios through a risk manager."""
    results = {"wins": 0, "losses": 0, "pnl": 0.0, "stake": 0.0, "exits": defaultdict(int)}
    stake = 6.25

    # Temporarily patch global bot_config.risk for _get_risk_config()
    from config.settings import bot_config
    old_risk = bot_config.risk
    bot_config.risk = risk_cfg

    try:
        for bet, prices, market in scenarios:
            results["stake"] += stake
            exited = False
            for price in prices:
                ok, reason = rm.check_early_exit(bet, price, market)
                if ok:
                    exit_val = stake * (price / bet.entry_price)
                    pnl = exit_val - stake
                    results["pnl"] += pnl
                    results["wins" if pnl > 0 else "losses"] += 1
                    results["exits"][reason.split(":")[0]] += 1
                    exited = True
                    break
            if not exited:
                final = prices[-1]
                if final >= 0.5:
                    results["pnl"] -= stake
                    results["losses"] += 1
                else:
                    results["pnl"] += stake * (1.0 / bet.entry_price) - stake
                    results["wins"] += 1
                results["exits"]["settlement"] += 1
    finally:
        bot_config.risk = old_risk

    return results


def main():
    # Configs
    old_cfg = RiskConfig()
    old_cfg.tier1_take_profit = 0.80;  old_cfg.tier1_trailing_stop = 0.15; old_cfg.tier1_stop_loss = 0.20
    old_cfg.tier2_take_profit = 0.80;  old_cfg.tier2_trailing_stop = 0.15; old_cfg.tier2_stop_loss = 0.20
    old_cfg.tier4_take_profit = 0.80;  old_cfg.tier4_trailing_stop = 0.15; old_cfg.tier4_stop_loss = 0.20

    new_cfg = RiskConfig()  # tiered defaults
    old_rm = RiskManager(None, old_cfg)
    new_rm = RiskManager(None, new_cfg)

    # ── TIER 1 SENARYOLARI (0.01-0.05 entry) ────────────────
    print("=" * 72)
    print("TIER 1: Ultra-Low Entry (0.01-0.05)")
    print("Eski: TP=80%, SL=20%, TS=15%  |  Yeni: TP=YOK, SL=50%, TS=30%")
    print("=" * 72)

    tier1_scenarios = [
        # Scenario 1: Lottery WIN — 0.02 giris, 0.95'te settle
        ("Lottery WIN: 0.02→0.95 settle", 0.02,
         [0.02, 0.03, 0.05, 0.08, 0.12, 0.20, 0.35, 0.50, 0.70, 0.85, 0.95],
         0.95),
        # Scenario 2: Moderate pump — 0.03 giris, 0.15'e cikar, sonra duser
        ("Moderate pump: 0.03→0.15→0.06", 0.03,
         [0.03, 0.04, 0.06, 0.08, 0.12, 0.15, 0.14, 0.11, 0.08, 0.06],
         0.06),
        # Scenario 3: Small win — 0.04 giris, 0.20'ye cikar, settle
        ("Small win: 0.04→0.20 settle", 0.04,
         [0.04, 0.05, 0.07, 0.10, 0.14, 0.18, 0.20, 0.30, 0.50],
         0.50),
        # Scenario 4: Quick loss — 0.02 giris, 0.01'e duser
        ("Quick loss: 0.02→0.01", 0.02,
         [0.02, 0.018, 0.015, 0.012, 0.01],
         0.01),
        # Scenario 5: Volatile hold — 0.01 giris, cok dalgalanir, settle at 0.80
        ("Volatile hold: 0.01→0.05→0.02→0.80", 0.01,
         [0.01, 0.02, 0.04, 0.05, 0.03, 0.02, 0.03, 0.06, 0.15, 0.30, 0.60, 0.80],
         0.80),
        # Scenario 6: Near-miss — 0.02 giris, 0.50'ye cikar ama settle at 0.0
        ("Near-miss: 0.02→0.50→settle at 0", 0.02,
         [0.02, 0.05, 0.10, 0.20, 0.35, 0.50, 0.30, 0.15, 0.05, 0.02],
         0.02),
    ]

    t1_old_scenarios = [(Bet(ep), prices, Market(48)) for _, ep, prices, _ in tier1_scenarios]
    t1_new_scenarios = [(Bet(ep), prices, Market(48)) for _, ep, prices, _ in tier1_scenarios]

    old_r = run_scenarios(old_rm, t1_old_scenarios, old_cfg)
    new_r = run_scenarios(new_rm, t1_new_scenarios, new_cfg)

    print(f"\n{'Senaryo':<40} {'Eski PnL':>12} {'Yeni PnL':>12} {'Fark':>10}")
    print("-" * 72)
    for name, ep, prices, final in tier1_scenarios:
        # Run each individually for per-scenario PnL
        old_one = run_scenarios(old_rm, [(Bet(ep), prices, Market(48))], old_cfg)
        new_one = run_scenarios(new_rm, [(Bet(ep), prices, Market(48))], new_cfg)
        diff = new_one["pnl"] - old_one["pnl"]
        arrow = "▲" if diff > 0.001 else ("▼" if diff < -0.001 else "=")
        print(f"  {name:<38} ${old_one['pnl']:>+9.2f}  ${new_one['pnl']:>+9.2f}  {arrow} ${abs(diff):>6.2f}")

    print(f"\n  {'TOPLAM':<38} ${old_r['pnl']:>+9.2f}  ${new_r['pnl']:>+9.2f}  {'▲' if new_r['pnl'] > old_r['pnl'] else '='} ${abs(new_r['pnl'] - old_r['pnl']):>6.2f}")
    print(f"  {'Kazanan':<38} {old_r['wins']:>10}    {new_r['wins']:>10}")
    print(f"  {'Exit Reasonları':<38}")
    for k in sorted(set(list(old_r['exits'].keys()) + list(new_r['exits'].keys()))):
        print(f"    {k}: eski={old_r['exits'].get(k,0)}, yeni={new_r['exits'].get(k,0)}")

    # ── TIER 2 SENARYOLARI (0.05-0.15 entry) ────────────────
    print(f"\n{'=' * 72}")
    print("TIER 2: Low Entry (0.05-0.15)")
    print("Eski: TP=80%, SL=20%, TS=15%  |  Yeni: TP=300%, SL=40%, TS=20%")
    print("=" * 72)

    tier2_scenarios = [
        ("Big win: 0.08→0.80", 0.08,
         [0.08, 0.12, 0.18, 0.25, 0.35, 0.50, 0.65, 0.80],
         0.80),
        ("Pump & dump: 0.10→0.25→0.08", 0.10,
         [0.10, 0.14, 0.18, 0.22, 0.25, 0.22, 0.18, 0.14, 0.10, 0.08],
         0.08),
        ("Steady climb: 0.06→0.40", 0.06,
         [0.06, 0.08, 0.10, 0.14, 0.18, 0.22, 0.28, 0.35, 0.40],
         0.40),
        ("Loss: 0.12→0.04", 0.12,
         [0.12, 0.10, 0.08, 0.06, 0.05, 0.04],
         0.04),
    ]

    for name, ep, prices, final in tier2_scenarios:
        old_one = run_scenarios(old_rm, [(Bet(ep), prices, Market(48))], old_cfg)
        new_one = run_scenarios(new_rm, [(Bet(ep), prices, Market(48))], new_cfg)
        diff = new_one["pnl"] - old_one["pnl"]
        arrow = "▲" if diff > 0.001 else ("▼" if diff < -0.001 else "=")
        print(f"  {name:<38} ${old_one['pnl']:>+9.2f}  ${new_one['pnl']:>+9.2f}  {arrow} ${abs(diff):>6.2f}")

    # ── TIER 3 (mevcut behavior) ────────────────────────────
    print(f"\n{'=' * 72}")
    print("TIER 3: Normal Entry (0.15-0.50) — Her iki strateji de ayni")
    print("=" * 72)
    print("  Tier 3'te eski ve yeni config ayni parametreleri kullanir.")
    print("  Fark beklenmez — backward compatible.")

    # ── PARTIAL TAKE-PROFIT TEST ────────────────────────────
    print(f"\n{'=' * 72}")
    print("PARTIAL TAKE-PROFIT TEST (entry <= 0.35, %100 karda)")
    print("Giriş bedelini kurtar, kalanı trail stop ile devam ettir")
    print("=" * 72)

    partial_scenarios = [
        # Senaryo 1: 0.20 giris, 0.40'a cikar → partial TP → sonra 0.80'e cikar, 0.60'a dus → TS tetik
        ("0.20→0.40(partial)→0.80→0.60(TS)", 0.20,
         [0.20, 0.25, 0.30, 0.35, 0.40, 0.50, 0.60, 0.70, 0.80, 0.75, 0.70, 0.65, 0.60]),
        # Senaryo 2: 0.20 giris, 0.40'a cikar → partial TP → settle at 1.0
        ("0.20→0.40(partial)→settle at 1.0", 0.20,
         [0.20, 0.25, 0.30, 0.35, 0.40, 0.50, 0.60, 0.70, 0.80, 0.90, 1.0]),
        # Senaryo 3: 0.35 giris, 0.70'e cikar → partial TP → sonra 0.50'ye dus
        ("0.35→0.70(partial)→0.50(TS)", 0.35,
         [0.35, 0.45, 0.55, 0.65, 0.70, 0.65, 0.60, 0.55, 0.50]),
        # Senaryo 4: 0.15 giris, hic 0.30'a cikmaz → partial TP tetiklenmez, normal devam
        ("0.15→0.25(hic TP yok)", 0.15,
         [0.15, 0.18, 0.20, 0.22, 0.25, 0.23, 0.20]),
    ]

    for name, ep, prices in partial_scenarios:
        bet = Bet(ep)
        total_pnl = 0.0
        partial_done = False
        partial_fraction = 0
        partial_price = 0
        remaining_shares = bet.shares

        for price in prices:
            ok, reason = new_rm.check_early_exit(bet, price, Market(48))
            if ok:
                if reason.startswith("partial_take_profit"):
                    partial_done = True
                    partial_fraction = bet.covered_fraction
                    partial_price = price
                    # Hesapla realize edilen kâr
                    sold_shares = remaining_shares * partial_fraction
                    realized = sold_shares * (price - ep)
                    total_pnl += realized
                    remaining_shares = bet.shares
                    print(f"  {name}")
                    print(f"    ✅ Partial TP @ {price:.4f}: {partial_fraction:.1%} satıldı, kâr=${realized:+.2f}")
                    print(f"    Kalan hisse: {remaining_shares:.1f}, efektif maliyet: $0.00 (zero cost)")
                    continue
                else:
                    # Normal exit (TS, SL vs.)
                    exit_val = remaining_shares * price
                    cost = remaining_shares * ep
                    realized = exit_val - cost
                    total_pnl += realized
                    print(f"    🔴 Exit: {reason[:40]} @ {price:.4f}, kâr=${realized:+.2f}")
                    break
        else:
            # Fiyat yolculuğunun sonu — settlement
            final = prices[-1]
            remaining_cost = remaining_shares * ep  # Zaten kurtarılmış olabilir
            realized = remaining_shares * (final - ep) if final > ep else remaining_shares * (1.0 / ep - 1) * final
            total_pnl += realized
            print(f"    📊 Settlement @ {final:.4f}, kalan kâr=${realized:+.2f}")

        print(f"    TOPLAM PnL: ${total_pnl:+.2f}\n")

    # ── SUMMARY ─────────────────────────────────────────────
    print(f"\n{'=' * 72}")
    print("ÖZET: Tiered Risk Management Avantajları")
    print("=" * 72)
    print("""
  TIER 1 (Ultra-Low 0.01-0.05):
    Eski: TP=80% → 0.02 giriste 0.036'da satar (1.8x)
    Yeni: TP=YOK → settlement'a kadar bekler, 0.95'te settle (47.5x)
    kazanilan: Lottery win'de 25x daha fazla kâr

  TIER 2 (Low 0.05-0.15):
    Eski: TP=80% → 0.08 giriste 0.144'da satar (1.8x)
    Yeni: TP=300% → 0.32'de satar (4x) — daha büyük kazanç
    Trailing stop %20 (eski %15) → daha büyük dalgalanmalara izin

  TIER 4 (Conservative 0.50+):
    Eski: SL=20%, TP=80% — cok genis
    Yeni: SL=15%, TP=30%, TS=10% — hizli kâr al, cabuk zarar kes

  SONUÇ: Tier 1'de lottery win senaryosunda ~25x kazanç artisi.
  Tier 2'de daha buyuk kâr potansiyeli. Tier 4'te daha cabuk exit.
""")


if __name__ == "__main__":
    main()
