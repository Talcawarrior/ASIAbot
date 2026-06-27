#!/usr/bin/env python3
"""Comprehensive review findings verification - tests every M1-M14 claim."""

import json
import os
import sqlite3
import sys
import io

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

DB = "data/bot.db"
conn = sqlite3.connect(DB)
c = conn.cursor()

print("=" * 70)
print("ASIAbot COMPREHENSIVE REVIEW AUDIT")
print("=" * 70)

# ── M1: NO bet current_price ──────────────────────────────────────────────────
print("\n[M1] NO bet'ler için current_price kontrolü")
print("-" * 50)
c.execute("""
    SELECT b.id, b.side, b.entry_price, b.current_price, b.unrealized_pnl,
           b.shares, m.yes_price
    FROM bets b
    JOIN weather_markets m ON b.market_id = m.id
    WHERE b.side = 'NO' AND b.status IN ('active', 'open', 'placed', 'pending')
    ORDER BY b.id DESC LIMIT 5
""")
for r in c.fetchall():
    bet_id, side, entry, current, unrealized, shares, yes_price = r
    expected_no_price = round(1.0 - yes_price, 4)
    expected_unrealized = round(shares * (expected_no_price - entry), 2)
    ok = "✓" if abs(current - expected_no_price) < 0.001 else "✗ WRONG"
    print(
        f"  bet#{bet_id}: entry={entry}, current={current}, expected_no={expected_no_price} {ok}"
    )
    print(f"    unrealized={unrealized}, expected={expected_unrealized}")
    if abs(current - expected_no_price) >= 0.001:
        print(
            f"    *** BUG: current_price={current} but should be {expected_no_price} (1-{yes_price})"
        )

# ── M2: Portfolio.total_realized_pnl ──────────────────────────────────────────
print("\n[M2] Portfolio.total_realized_pnl senkronizasyonu")
print("-" * 50)
c.execute("SELECT total_realized_pnl, total_won, total_lost FROM portfolio WHERE id=1")
p_realized, p_won, p_lost = c.fetchone()

c.execute("""
    SELECT COALESCE(SUM(pnl), 0), COUNT(CASE WHEN pnl > 0 THEN 1 END),
           COUNT(CASE WHEN pnl <= 0 THEN 1 END)
    FROM bets WHERE status IN ('won', 'lost', 'settled', 'closed_early')
""")
db_pnl, db_won, db_lost = c.fetchone()

realized_ok = "✓" if abs(p_realized - db_pnl) < 1.0 else "✗ MISMATCH"
won_ok = "✓" if p_won == db_won else "✗ MISMATCH"
print(f"  Portfolio realized_pnl: {p_realized}, DB sum: {db_pnl} {realized_ok}")
print(f"  Portfolio won: {p_won}, DB won: {db_won} {won_ok}")
print(f"  Portfolio lost: {p_lost}, DB lost: {db_lost}")

# ── M3: /api/history stats (closed_early dahil) ──────────────────────────────
print("\n[M3] History stats — closed_early WIN kayıtları")
print("-" * 50)
c.execute("""
    SELECT status, COUNT(*), SUM(pnl)
    FROM bets WHERE status IN ('won', 'lost', 'settled', 'closed_early')
    GROUP BY status
""")
for r in c.fetchall():
    print(f"  {r[0]}: count={r[1]}, total_pnl={r[2]}")

c.execute("""
    SELECT COUNT(*), SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END)
    FROM bets WHERE status = 'closed_early'
""")
ce_count, ce_wins = c.fetchone()
print(f"  closed_early toplam: {ce_count}, kazanan: {ce_wins}")
if ce_wins and ce_wins > 0:
    print(f"  → {ce_wins} kazanan closed_early bet stats'a dahil edilmeli")

# ── M4: UI Brier/Accuracy — model_performance tablosu ────────────────────────
print("\n[M4] model_performance tablosu (Brier/Accuracy)")
print("-" * 50)
c.execute("""
    SELECT model_name, brier_score, accuracy, num_predictions, recorded_at
    FROM model_performance
    ORDER BY recorded_at DESC LIMIT 20
""")
rows = c.fetchall()
if not rows:
    print("  ❌ TABLO BOŞ — hiçbir tahmin kaydedilmemiş!")
else:
    for r in rows:
        print(f"  {r[0]}: brier={r[1]}, acc={r[2]}, n={r[3]}, at={r[4]}")

# ── M5: VWAP slippage ────────────────────────────────────────────────────────
print("\n[M5] VWAP slippage - edge verileri")
print("-" * 50)
c.execute("""
    SELECT slippage_pct, COUNT(*)
    FROM analyses
    WHERE slippage_pct IS NOT NULL
    GROUP BY slippage_pct
    ORDER BY COUNT(*) DESC LIMIT 10
""")
rows = c.fetchall()
if not rows:
    print("  Hicbir slippage kaydi yok")
else:
    for r in rows:
        print(f"  slip={r[0]}, count={r[1]}")

# ── M6: Gas cost ─────────────────────────────────────────────────────────────
print("\n[M6] Gas cost - edge hesabi")
print("-" * 50)
c.execute(
    "SELECT raw_edge, edge, slippage_pct FROM analyses WHERE raw_edge IS NOT NULL LIMIT 5"
)
rows = c.fetchall()
if not rows:
    print("  Hicbir raw_edge kaydi yok")
else:
    for r in rows:
        diff = round(r[0] - r[1], 4) if r[0] and r[1] else 0
        print(
            f"  raw_edge={r[0]}, edge={r[1]}, slip={r[2]}, diff={diff} (slippage+fee+gas)"
        )

# ── M7: Portfolio total_value vs cash + exposure ─────────────────────────────
print("\n[M7] Portfolio total_value = cash + exposure?")
print("-" * 50)
c.execute("SELECT cash_balance, total_value FROM portfolio WHERE id=1")
cash, total = c.fetchone()
c.execute(
    "SELECT COALESCE(SUM(amount), 0) FROM bets WHERE status IN ('active','open','placed','pending')"
)
open_exp = c.fetchone()[0]
expected = round(cash + open_exp, 2)
gap = round(total - expected, 2)
print(f"  cash={cash}, open_exposure={open_exp}")
print(f"  expected total={expected}, actual total={total}")
print(f"  gap={gap} {'✓' if abs(gap) < 1.0 else '✗ MISMATCH'}")

# ── M8: SIA frozen mod ───────────────────────────────────────────────────────
print("\n[M8] SIA — model_performance neden boş?")
print("-" * 50)
c.execute("SELECT COUNT(*) FROM bets WHERE status IN ('won', 'lost')")
settled_normal = c.fetchone()[0]
c.execute("SELECT COUNT(*) FROM bets WHERE status = 'closed_early'")
settled_early = c.fetchone()[0]
c.execute("""
    SELECT COUNT(*) FROM bets b
    JOIN analyses a ON b.analysis_id = a.id
    WHERE b.status IN ('won', 'lost', 'closed_early')
    AND a.model_predictions IS NOT NULL
""")
with_predictions = c.fetchone()[0]
print(f"  won/lost bet: {settled_normal}")
print(f"  closed_early bet: {settled_early}")
print(f"  analysis ile model_predictions olan bet: {with_predictions}")
if with_predictions == 0:
    print("  ❌ Hiçbir settled bet'te model_predictions yok — SIA veri bulamaz!")

# ── M9: Karpathy search ──────────────────────────────────────────────────────
print("\n[M9] Karpathy search — historical_calibrations tablosu")
print("-" * 50)
c.execute(
    "SELECT name FROM sqlite_master WHERE type='table' AND name='historical_calibrations'"
)
exists = c.fetchone()
if exists:
    c.execute("SELECT COUNT(*) FROM historical_calibrations")
    count = c.fetchone()[0]
    print(f"  Tablo var, {count} kayıt")
else:
    print("  ❌ historical_calibrations tablosu YOK — backfill çalıştırılmalı")

# ── M10: /api/asi/trades ─────────────────────────────────────────────────────
print("\n[M10] /api/asi/trades — mock veri kontrolü")
print("-" * 50)
try:
    import requests

    r = requests.get("http://localhost:8091/api/asi/trades", timeout=10)
    data = r.json()
    if data:
        print(f"  {len(data)} trade döndü")
        if data:
            first = data[0]
            print(f"  İlk trade: {json.dumps(first, indent=2, default=str)[:300]}")
    else:
        print("  Boş döndü")
except Exception as e:
    print(f"  API erişilemedi: {e}")

# ── M11: ASI-Evolve ghost model ──────────────────────────────────────────────
print("\n[M11] ASI-Evolve — model ağırlıkları")
print("-" * 50)

weights_path = os.path.join("data", "model_weights.json")
if os.path.exists(weights_path):
    with open(weights_path) as f:
        weights = json.load(f)
    print(f"  {len(weights)} model ağırlığı kayıtlı:")
    for m, w in sorted(weights.items(), key=lambda x: -x[1]):
        print(f"    {m}: {w:.4f}")
else:
    print("  model_weights.json yok")

# ── M12: unrealized_pnl NO betlerde ──────────────────────────────────────────
print("\n[M12] unrealized_pnl NO bet detaylı kontrol")
print("-" * 50)
c.execute("""
    SELECT b.id, b.side, b.entry_price, b.current_price, b.unrealized_pnl,
           b.shares, m.yes_price,
           ROUND(1.0 - m.yes_price, 4) as expected_no,
           ROUND(b.shares * ((1.0 - m.yes_price) - b.entry_price), 2) as expected_unreal
    FROM bets b
    JOIN weather_markets m ON b.market_id = m.id
    WHERE b.side = 'NO' AND b.status IN ('active', 'open', 'placed', 'pending')
    ORDER BY ABS(b.unrealized_pnl - b.shares * ((1.0 - m.yes_price) - b.entry_price)) DESC
    LIMIT 5
""")
for r in c.fetchall():
    bet_id, side, entry, current, unreal, shares, yes_p, exp_no, exp_unreal = r
    diff = abs(unreal - exp_unreal) if unreal and exp_unreal else 0
    ok = "✓" if diff < 1.0 else "✗"
    print(f"  bet#{bet_id}: entry={entry}, current={current}, unrealized={unreal}")
    print(f"    expected_no={exp_no} (1-{yes_p}), expected_unreal={exp_unreal} {ok}")

# ── M13: Cash reconciliation ─────────────────────────────────────────────────
print("\n[M13] Cash reconciliation")
print("-" * 50)
c.execute("SELECT cash_balance, initial_value FROM portfolio WHERE id=1")
cash, initial = c.fetchone()
print(f"  initial={initial}, cash={cash}")

c.execute("""
    SELECT COALESCE(SUM(amount), 0) FROM bets
    WHERE status IN ('active', 'open', 'placed', 'pending')
""")
locked = c.fetchone()[0]
c.execute("""
    SELECT COALESCE(SUM(pnl), 0) FROM bets
    WHERE status IN ('won', 'lost', 'settled', 'closed_early')
""")
realized_pnl = c.fetchone()[0]
expected_cash = round(initial + realized_pnl - locked, 2)
print(f"  locked_in_positions={locked}")
print(f"  realized_pnl={realized_pnl}")
print(
    f"  expected_cash = initial + realized - locked = {initial} + {realized_pnl} - {locked} = {expected_cash}"
)
print(f"  actual_cash = {cash}")
print(
    f"  gap = {round(cash - expected_cash, 2)} {'✓' if abs(cash - expected_cash) < 1.0 else '✗'}"
)

# ── M14: model_performance 0 predictions ──────────────────────────────────────
print("\n[M14] model_performance — neden 0 predictions?")
print("-" * 50)
c.execute("""
    SELECT model_name, brier_score, accuracy, num_predictions
    FROM model_performance
""")
rows = c.fetchall()
if not rows:
    print("  ❌ Tablo tamamen boş")
else:
    total_pred = sum(r[3] for r in rows)
    print(f"  {len(rows)} model, toplam predictions: {total_pred}")
    if total_pred == 0:
        print("  ❌ Tüm modellerde 0 predictions — SIA optimize edemiyor")

conn.close()
print("\n" + "=" * 70)
print("COMPREHENSIVE AUDIT COMPLETE")
print("=" * 70)
