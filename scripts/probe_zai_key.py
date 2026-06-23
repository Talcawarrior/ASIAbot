"""Probe a ZAI (Zhipu / GLM) API key.

ZAI exposes an OpenAI-compatible endpoint at:
    https://api.z.ai/api/paas/v4/

Key format is the classic ZhipuAI "<id>.<secret>" form (e.g.
"3bd64c05ce1049fe874c1b2317ba9898.nvm8JMEkWsL1DG5r"). The OpenAI SDK
works directly with this key as a Bearer token — no JWT exchange needed
on the modern /api/paas/v4/ endpoint.

Usage:
    ZAI_API_KEY=3bd64c05... python scripts/probe_zai_key.py
"""

from __future__ import annotations

import os
import sys
import time

import requests
from openai import OpenAI

ZAI_BASE_URL = "https://api.z.ai/api/paas/v4/"

# Spread of ZAI / GLM models — covers the current production ladder.
CANDIDATE_MODELS = [
    "glm-4.5-flash",        # Cheap+fast newer flash tier
    "glm-4-flash",          # Original flash tier (free)
    "glm-4-flashx",         # Variant of flash
    "glm-4.5",              # Mid-tier 4.5
    "glm-4.6",              # Latest 4.6 flagship
    "glm-4-plus",           # Plus tier
    "glm-4-air",            # Air tier
    "glm-4-airx",           # AirX tier
    "glm-z1-flash",         # Reasoning flash
    "glm-4v-flash",         # Vision flash
]


def probe_with_sdk(api_key: str) -> list[str]:
    """Try the openai SDK against each candidate model."""
    print("=" * 72)
    print("Strategy 1: openai SDK -> ZAI /chat/completions")
    print("=" * 72)
    client = OpenAI(api_key=api_key, base_url=ZAI_BASE_URL)
    working = []
    for model in CANDIDATE_MODELS:
        t0 = time.perf_counter()
        try:
            resp = client.chat.completions.create(
                model=model,
                messages=[
                    {
                        "role": "system",
                        "content": "You are a terse JSON generator.",
                    },
                    {
                        "role": "user",
                        "content": (
                            'Reply with one JSON object: '
                            '{"source":"zai","model":"<your_model>","ok":true}'
                        ),
                    },
                ],
                max_tokens=60,
                temperature=0.0,
            )
            dt_ms = int((time.perf_counter() - t0) * 1000)
            content = resp.choices[0].message.content.strip()
            usage = resp.usage
            print(f"[OK] {model:24s} {dt_ms:5d}ms  tokens={usage.total_tokens:4d}")
            print(f"      -> {content!r}")
            working.append(model)
        except Exception as e:  # noqa: BLE001
            dt_ms = int((time.perf_counter() - t0) * 1000)
            msg = str(e)
            if len(msg) > 200:
                msg = msg[:200] + "..."
            print(f"[--] {model:24s} {dt_ms:5d}ms  {type(e).__name__}: {msg}")

    print()
    print(f"Working models: {len(working)}/{len(CANDIDATE_MODELS)}")
    for m in working:
        print(f"  - {m}")
    return working


def probe_with_raw_http(api_key: str) -> None:
    """Hit the raw REST endpoint and dump rate-limit headers."""
    print()
    print("=" * 72)
    print("Strategy 2: raw HTTP -> /chat/completions (with rate-limit headers)")
    print("=" * 72)
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": "glm-4-flash",
        "messages": [{"role": "user", "content": "ping"}],
        "max_tokens": 4,
    }
    try:
        r = requests.post(
            f"{ZAI_BASE_URL}chat/completions",
            headers=headers,
            json=payload,
            timeout=30,
        )
        print(f"HTTP {r.status_code}")
        # Dump all non-standard headers (rate-limit info etc.)
        for h, v in r.headers.items():
            if any(x in h.lower() for x in ["x-ratelimit", "x-tt", "x-zai", "x-request"]):
                print(f"  {h}: {v}")
        if r.status_code == 200:
            data = r.json()
            print(
                f"  model={data.get('model')} "
                f"content={data['choices'][0]['message']['content']!r}"
            )
            usage = data.get("usage", {})
            print(f"  usage: {usage}")
        else:
            print("  body:", r.text[:400])
    except Exception as e:  # noqa: BLE001
        print(f"RAW HTTP failed: {type(e).__name__}: {e}")


def probe_models_endpoint(api_key: str) -> None:
    """List available models via /models."""
    print()
    print("=" * 72)
    print("Strategy 3: GET /models")
    print("=" * 72)
    headers = {"Authorization": f"Bearer {api_key}"}
    try:
        r = requests.get(
            f"{ZAI_BASE_URL}models",
            headers=headers,
            timeout=30,
        )
        print(f"HTTP {r.status_code}")
        if r.status_code == 200:
            data = r.json()
            models = data.get("data", [])
            print(f"  {len(models)} models available")
            for m in models[:30]:
                owned = m.get("owned_by", "?")
                ctx = m.get("context_window", m.get("max_tokens", "?"))
                print(f"  - {m['id']:30s} ctx={ctx} owned_by={owned}")
            if len(models) > 30:
                print(f"  ... and {len(models) - 30} more")
        else:
            print("  body:", r.text[:400])
    except Exception as e:  # noqa: BLE001
        print(f"/models failed: {type(e).__name__}: {e}")


def main() -> int:
    api_key = os.environ.get("ZAI_API_KEY")
    if not api_key:
        env_path = "/home/z/my-project/asiabot/.env"
        if os.path.exists(env_path):
            with open(env_path) as f:
                for line in f:
                    line = line.strip()
                    if line.startswith("ZAI_API_KEY="):
                        api_key = line.split("=", 1)[1].strip().strip('"').strip("'")
                        break
    if not api_key:
        print("ERROR: no ZAI_API_KEY in env or .env", file=sys.stderr)
        return 2

    print(f"Using key: {api_key[:10]}...{api_key[-4:]} (len={len(api_key)})")
    print()

    working = probe_with_sdk(api_key)
    probe_with_raw_http(api_key)
    probe_models_endpoint(api_key)

    print()
    print("=" * 72)
    print("SUMMARY")
    print("=" * 72)
    if working:
        # Pick the cheapest working model as the default recommendation.
        preferred_order = [
            "glm-4.5-flash",
            "glm-4-flash",
            "glm-4-flashx",
            "glm-4-air",
            "glm-4-airx",
            "glm-4.5",
            "glm-4-plus",
            "glm-4.6",
            "glm-z1-flash",
            "glm-4v-flash",
        ]
        recommended = next((m for m in preferred_order if m in working), working[0])
        print(f"  ZAI key is ALIVE. {len(working)} models responded.")
        print(f"  Recommended (cheap+fast): {recommended}")
        print()
        print("  To activate, set in .env:")
        print(f"    ZAI_API_KEY={api_key}")
        print(f"    ZAI_BASE_URL={ZAI_BASE_URL}")
        print(f"    KARPATHY_LLM_MODEL={recommended}")
        print(f"    ASI_LLM_MODEL={recommended}")
        print(f"    SIA_LLM_MODEL={recommended}")
        return 0
    print("  ZAI key is NOT usable — all candidate models failed.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
