"""Confirm ZAI glm-4.5-flash works with proper max_tokens.

Key findings from previous probes:
  1. glm-4.5-flash IS a reasoning model — it emits chain-of-thought into
     `reasoning_content` and the final answer into `content`.
  2. With small max_tokens (e.g. 30), ALL tokens get consumed by reasoning
     and content comes back empty (finish_reason='length').
  3. Need max_tokens >= ~500 to leave room for actual content.

This script tests the exact prompt that the LLM hooks use (Karpathy
hypothesis proposal), to make sure production traffic will work.
"""

from __future__ import annotations

import json
import os
import sys
import time

from openai import OpenAI

ZAI_BASE_URL = "https://api.z.ai/api/paas/v4/"
KEY = os.environ.get("ZAI_API_KEY", "")

PROMPT = """You are a quantitative researcher running a Karpathy-style autonomous \
experiment loop on a Polymarket weather trading bot.

Parent hypothesis (current best):
{
  "description": "baseline uniform weights",
  "model_weights": {
    "ecmwf_ifs04": 0.125, "gfs_seamless": 0.125, "icon_seamless": 0.125,
    "gem_global": 0.125, "jma_seamless": 0.125, "ncep_gefs": 0.125,
    "ukmo_global_deterministic_10km": 0.125,
    "meteofrance_arpege_world": 0.125
  },
  "min_edge": 0.05,
  "kelly_fraction": 0.15,
  "max_bet_pct": 0.05,
  "tail_filter_enabled": false
}

Recent test-window stats: {"sharpe": 0.10, "brier": 0.035, "roi_pct": 350.0, "n_trades": 442}

Propose ONE mutation as a JSON object with these fields:
  description (string), model_weights (object model->weight),
  min_edge (float 0.02-0.15), kelly_fraction (float 0.05-0.30),
  max_bet_pct (float 0.01-0.10), tail_filter_enabled (bool)

Return ONLY the JSON object, no prose."""


def main() -> int:
    if not KEY:
        print("ERROR: set ZAI_API_KEY in env", file=sys.stderr)
        return 2

    print(f"Using key: {KEY[:10]}...{KEY[-4:]} (len={len(KEY)})")

    # Use the openai SDK — it has built-in retries on transient errors.
    client = OpenAI(
        api_key=KEY,
        base_url=ZAI_BASE_URL,
        max_retries=5,
        timeout=120.0,
    )

    # Try the production-style call 3 times to confirm stability.
    print()
    print("=" * 72)
    print("Production-style Karpathy hypothesis call x 3")
    print("=" * 72)
    successes = 0
    for i in range(3):
        t0 = time.perf_counter()
        try:
            resp = client.chat.completions.create(
                model="glm-4.5-flash",
                messages=[{"role": "user", "content": PROMPT}],
                temperature=0.7,
                max_tokens=2000,
                response_format={"type": "json_object"},
            )
            dt = time.perf_counter() - t0
            content = resp.choices[0].message.content or ""
            reasoning = getattr(resp.choices[0].message, "reasoning_content", "") or ""
            finish = resp.choices[0].finish_reason
            usage = resp.usage
            print(f"\n[{i}] HTTP OK | {dt:.2f}s | finish_reason={finish}")
            print(
                f"    prompt_tokens={usage.prompt_tokens} "
                f"completion_tokens={usage.completion_tokens} "
                f"total_tokens={usage.total_tokens}"
            )
            print(f"    reasoning_content (first 150 chars): {reasoning[:150]!r}")
            print(f"    content (first 400 chars): {content[:400]!r}")
            # Try to parse content as JSON
            if content.strip():
                try:
                    data = json.loads(content)
                    print(f"    PARSED OK: keys={list(data.keys())}")
                    print(f"    description: {data.get('description')!r}")
                    print(f"    min_edge: {data.get('min_edge')!r}")
                    print(f"    kelly_fraction: {data.get('kelly_fraction')!r}")
                    print(f"    max_bet_pct: {data.get('max_bet_pct')!r}")
                    successes += 1
                except json.JSONDecodeError as e:
                    print(f"    JSON parse FAILED: {e}")
            else:
                print(
                    f"    content is empty (finish_reason={finish} suggests "
                    f"reasoning ate all the tokens — increase max_tokens)"
                )
        except Exception as e:  # noqa: BLE001
            dt = time.perf_counter() - t0
            print(f"\n[{i}] FAIL {dt:.2f}s {type(e).__name__}: {str(e)[:200]}")
        time.sleep(1.0)

    print()
    print("=" * 72)
    print(f"VERDICT: {successes}/3 calls produced parseable JSON")
    print("=" * 72)
    return 0 if successes >= 2 else 1


if __name__ == "__main__":
    sys.exit(main())
