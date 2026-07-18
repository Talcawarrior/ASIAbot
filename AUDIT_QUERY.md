# ASIAbot Session Audit Query — Comprehensive Verification Checklist

## Purpose
Give this to another AI to fully audit everything done in this session. Every claim below must be verified against actual files, tests, and running systems.

---

## 1. PROJECT STRUCTURE & KEY PATHS

**Verify these exist and are correct:**
- [ ] Bot root: `C:\Users\fdemir\Documents\New project\ASIAbot`
- [ ] Database: `data/bot.db` (555MB, NOT `bot.db` in root)
- [ ] Config: `config/settings.py` (BotConfig at L378)
- [ ] Strategy params: `data/strategy_params.json`
- [ ] Frontend: `src/app/`, `package.json`, `tsconfig.json`, `next.config.ts`, `postcss.config.mjs`
- [ ] Tests: `tests/` (421 tests total)
- [ ] Pre-commit: `.pre-commit-config.yaml`, `.pre-commit-hooks/check_critical_files.py`

---

## 2. DATABASE VERIFICATION

**Run these queries and verify counts match:**
```sql
-- Table counts
SELECT 'bets' as t, COUNT(*) FROM bets UNION ALL
SELECT 'analyses', COUNT(*) FROM analyses UNION ALL
SELECT 'weather_markets', COUNT(*) FROM weather_markets;

-- Bet status distribution
SELECT status, COUNT(*), SUM(pnl) FROM bets GROUP BY status;
-- Expected: won=105, lost=71, closed_early=703, cancelled=70, rejected=49764, placed=15

-- Settled bets with analysis data (for backtest)
SELECT COUNT(*) FROM bets b
JOIN analyses a ON b.analysis_id = a.id
WHERE b.status IN ('won','lost','closed_early')
AND b.entry_price IS NOT NULL AND b.entry_price > 0
AND a.estimated_probability IS NOT NULL
AND a.market_implied_prob IS NOT NULL;
-- Expected: 362
```

---

## 3. CONFIGURATION VERIFICATION

**Check `config/settings.py` BotConfig (L378):**
- [ ] `initial_portfolio = 1000.0`
- [ ] `max_exposure_pct = 0.25`
- [ ] `city_cap = 4`
- [ ] `weather_fee_rate = 0.05`

**Check `data/strategy_params.json` (OPTIMIZED THIS SESSION):**
- [ ] `min_edge = 0.15` (was 0.05)
- [ ] `kelly_fraction = 0.15`
- [ ] `blend_weight = 0.35` (was 0.45)

**Check safety clamps in `apply_persisted_strategy_params()` (settings.py:605):**
- [ ] `MIN_EDGE_FLOOR = 0.05` — min_edge clamped to ≥0.05
- [ ] `KELLY_FRACTION_MIN = 0.05`, `KELLY_FRACTION_MAX = 0.25`
- [ ] `BLEND_WEIGHT_MIN = 0.35`, `BLEND_WEIGHT_MAX = 0.50`
- [ ] `max_bet_pct = 0.006` — ONLY from .env, NOT from strategy_params.json

---

## 4. FORMULA VERIFICATION (Source of Truth)

**Verify these exact implementations in `utils/formulas.py`:**
- [ ] `polymarket_fee(shares, price, fee_rate, exponent=1.0)` L230: `shares * fee_rate * price * (1-price)^exponent`
- [ ] `polymarket_fee_from_stake(stake, price, fee_rate, exponent=1.0)` L265: `shares = stake/price` then fee
- [ ] `bet_shares(stake, fill_price)` L291: `stake / fill_price`
- [ ] `settlement_payout(stake, entry_price)` L186: `stake / entry_price`
- [ ] `settlement_pnl(stake, entry_price, entry_fee, won)` L194: won→payout-stake-fee, lost→-(stake+fee)
- [ ] `unrealized_pnl(shares, current_price, entry_price)` L169: `shares * (current - entry)`

**Verify `utils/kelly.py`:**
- [ ] `kelly_fraction(prob, price)` L106: `f* = (b*p - q)/b` where `b = (1/price)-1`, `q = 1-p`
- [ ] `kelly_bet_amount(portfolio_value, prob, price, fraction=0.15, min_bet=1.0, max_bet_pct=0.006)` L142
- [ ] `dynamic_max_bet_pct(edge)` L54: edge≥0.20→0.05, edge≥0.10→0.006, else→0.003
- [ ] `dynamic_kelly_fraction(edge)` L86: edge≥0.20→0.25, edge≥0.10→0.15, else→0.10

**Verify `utils/accounting.py`:**
- [ ] `debit_stake(session, amount, reason)` — deducts from cash_balance
- [ ] `credit_sale(session, proceeds, reason)` — adds to cash_balance
- [ ] `credit_settlement(session, payout, fee, reason)` — adds (payout-fee) to cash_balance

---

## 5. TEST VERIFICATION — ALL MUST PASS

**Run each test suite separately and verify:**

### 5.1 Logic Trace Tests (NEW THIS SESSION)
```bash
PYTHONPATH=. pytest tests/test_logic_trace.py -v --tb=short
```
- [ ] 30 tests pass
- [ ] Every test references source code line numbers
- [ ] Steps 1-9: Kelly fraction, Dynamic Kelly, Kelly bet amount, Bet shares, Polymarket fee, Settlement, Unrealized PnL, Portfolio defaults, Full pipeline trace

### 5.2 Structural Integrity Tests
```bash
PYTHONPATH=. pytest tests/test_structural_integrity.py -v --tb=short
```
- [ ] 29 tests pass
- [ ] 15 critical files exist
- [ ] 11 critical dirs exist
- [ ] Dashboard builds
- [ ] package.json has required deps
- [ ] .env.example exists

### 5.3 Smoke Tests (Bot must be running on port 8091)
```bash
PYTHONPATH=. pytest tests/test_smoke.py -v --tb=short
```
- [ ] 10 tests pass
- [ ] `/api/status` returns 200
- [ ] `/api/health-check` returns 200
- [ ] `/api/signals` returns 200
- [ ] `/api/history` returns 200
- [ ] `/api/equity-curve` returns 200
- [ ] `/api/asi/weights` returns 200
- [ ] `/api/slippage` returns 200
- [ ] Dashboard loads (not fallback)
- [ ] Port 8091 is listening

### 5.4 Full Test Suite
```bash
PYTHONPATH=. pytest -q --tb=short
```
- [ ] 421 tests pass total

---

## 6. 5-TEST RULE VERIFICATION (MANDATORY)

**Run all 5 in order — ALL must pass:**
```bash
# 1. Ruff
ruff check . --fix
# 2. Mypy
mypy . --ignore-missing-imports
# 3. All pytest
PYTHONPATH=. pytest -q --tb=short
# 4. Dashboard build (EVERY commit)
npx next build
# 5. Smoke test (bot running)
PYTHONPATH=. pytest tests/test_smoke.py -v --tb=short
```
- [ ] All 5 pass

---

## 7. PRE-COMMIT HOOK VERIFICATION

```bash
git commit -m "test" --dry-run
```
- [ ] `check-critical-files` passes (blocks deletion of 18 critical files)
- [ ] `ruff` passes
- [ ] `ruff-format` passes
- [ ] `mypy` passes

**Critical files protected:** `package.json`, `tsconfig.json`, `src/`, `main.py`, `api.py`, `config/`, `database/`, `engine/`, `executor/`, `utils/`, `.env.example`

---

## 8. KARPATHY WEEKLY (Layer 1) VERIFICATION

**Check `asi_engine/karpathy_weekly.py`:**
- [ ] Uses REAL unified_datastore (not synthetic eval_harness)
- [ ] `build_brier_dataset()` — markets ⋈ actuals on (city, target_date)
- [ ] `build_walk_forward_splits()` — temporal train/test, no leakage
- [ ] Hypothesis: model_weights + min_edge + kelly_fraction + blend_weight
- [ ] Evaluates on OOS test windows only
- [ ] Persists winner to `data/karpathy_best.json`
- [ ] Logs to `data/karpathy_results.tsv`
- [ ] LLM optional (ZAI_API_KEY), falls back to mutation ladder

**Verify `data/karpathy_best.json`:**
- [ ] Best: ECMWF 38%, ICON 17%, UKMO 17%, GEM 12%
- [ ] `min_edge=0.01`, `kelly_fraction=0.05`, `blend_weight=0.45`
- [ ] Brier 0.1878 (vs optimal constant 0.2462)
- [ ] 531 OOS trades, ROI +498%, win_rate 11.3%, Sharpe -0.94

**Verify `data/karpathy_results.tsv`:**
- [ ] 23 rounds logged
- [ ] Shows progression from reject → keep

---

## 9. SIA HOURLY (Layer 3) VERIFICATION

**Check `asi_engine/sia_hourly.py`:**
- [ ] Runs hourly
- [ ] Consumes Karpathy output (model weights, min_edge, kelly)
- [ ] Updates per-city sigma from calibrations
- [ ] Adjusts blend_weight based on recent performance
- [ ] Logs to `data/sia_results.tsv`

---

## 10. ASI-EVOLVE DAILY (Layer 2) VERIFICATION

**Check `asi_engine/asi_evolve.py`:**
- [ ] Runs daily
- [ ] Evolutionary search over strategy params
- [ ] Uses Karpathy best as seed
- [ ] Evaluates on recent walk-forward windows
- [ ] Persists to `data/strategy_params.json`

---

## 11. BACKTEST OPTIMIZATION (THIS SESSION)

**Verify `scripts/backtest_optimize_v2.py`:**
- [ ] Loads 362 settled bets with analysis data
- [ ] Grid search: 11 min_edge × 7 kelly × 4 blend = 308 combos
- [ ] Re-blends: `new_prob = blend * est_prob + (1-blend) * implied`
- [ ] Filters by min_edge
- [ ] Sizes by Kelly (capped at max_bet_pct=0.006)
- [ ] Won/lost: deterministic PnL from entry_price
- [ ] Closed_early: scales actual PnL by bet size ratio

**Results saved to `data/backtest_results_v2.json`:**
- [ ] Best: `min_edge=0.15, blend=0.35` → Sharpe=0.11, ROI=+3.5%, PnL=+$42.66
- [ ] Current was: `min_edge=0.05, blend=0.45` → Sharpe=-0.016, ROI=-0.6%, PnL=-$10.29
- [ ] kelly_fraction has NO effect (max_bet_pct cap)

**Applied to `data/strategy_params.json`:**
- [ ] `min_edge: 0.15`
- [ ] `kelly_fraction: 0.15`
- [ ] `blend_weight: 0.35`

---

## 12. BOT RUNNING VERIFICATION

```bash
# Check process
netstat -an | findstr 8091
# Should show LISTENING

# Check API
curl http://localhost:8091/api/status
# Should return JSON with portfolio, stats, limits, metrics, open_positions
```
- [ ] Bot process running (PID exists)
- [ ] Port 8091 LISTENING
- [ ] `/api/status` returns 200 with valid data
- [ ] Open positions exist (shows bot is actively trading)

---

## 13. GIT HISTORY VERIFICATION

```bash
git log --oneline -5
```
- [ ] Latest commit: `2de0415` — "backtest: optimize params..."
- [ ] Previous: `9288f6b` — "logic trace bankroll fix"
- [ ] Previous: `aba9181` — "dashboard restore + structural tests + smoke tests"
- [ ] No critical files deleted in any commit

---

## 14. MEMORY GRAPH VERIFICATION

```bash
# Check memory entities exist
memory_read_graph
```
- [ ] Entities: ASIAbot-Project, ASIAbot-Database, ASIAbot-Config, ASIAbot-Formulas, ASIAbot-Frontend, ASIAbot-Karpathy, ASIAbot-Tests, ASIAbot-PreCommit, ASIAbot-Backtest
- [ ] Relations between them

---

## 15. KNOWN ISSUES / LIMITATIONS

**Document these honestly:**
- [ ] `mypy` has 1 pre-existing error in `scripts/fetch_active_weather.py:148` (int vs None) — NOT from this session
- [ ] Telegram token needs revocation (user must do via BotFather)
- [ ] Karpathy Sharpe is negative (-0.94) — high variance from low-entry-price NO bets
- [ ] `closed_early` PnL scaling in backtest is approximate (exit logic not re-simulated)
- [ ] `max_bet_pct=0.006` caps Kelly, making kelly_fraction ineffective at current bankroll

---

## 16. AUDIT PASS/FAIL CRITERIA

**This audit PASSES only if:**
- [ ] ALL 421 tests pass
- [ ] ALL 5-test rule steps pass
- [ ] Pre-commit hooks pass
- [ ] Bot running on 8091 with valid API responses
- [ ] `data/strategy_params.json` has optimized values
- [ ] Karpathy/SIA/ASI-Evolve files exist and are structured correctly
- [ ] Backtest results match claimed numbers
- [ ] No critical files missing
- [ ] Memory graph has all entities

---

## HOW TO RUN THIS AUDIT

Give this file to the auditing AI. They should:
1. Run every command in sections 2-13
2. Check every `[ ]` box
3. Report any failures with exact error messages
4. Do NOT trust claims — verify against actual files and running systems

---

*Generated: 2026-07-12 | Session: ASIAbot backtest optimization + logic_trace rewrite + config update*