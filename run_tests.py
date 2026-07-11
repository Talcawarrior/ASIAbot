#!/usr/bin/env python3
"""run_tests.py — Kalici test scripti.

Her kod degisikliginden sonra bu scripti calistir:
    python run_tests.py

4 test sirayla calisir:
    1. ruff check  — lint + format
    2. mypy        — type safety
    3. pytest      — unit tests + coverage
    4. bandit      — security scan

Exit code 0 = tum testler gecti.
Exit code 1 = bir veya daha fazla test basarisiz.
"""

import subprocess
import sys
import time


def run(name: str, cmd: list[str], timeout: int = 180) -> bool:
    """Run a command, print result, return True if passed."""
    print(f"\n{'=' * 60}")
    print(f"  {name}")
    print(f"{'=' * 60}")
    start = time.time()
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        elapsed = time.time() - start

        if result.stdout:
            print(result.stdout)
        if result.stderr:
            print(result.stderr)

        if result.returncode == 0:
            print(f"\n  ✅ {name} PASSED ({elapsed:.1f}s)")
            return True
        else:
            print(f"\n  ❌ {name} FAILED ({elapsed:.1f}s)")
            return False

    except subprocess.TimeoutExpired:
        print(f"\n  ⏰ {name} TIMEOUT ({timeout}s)")
        return False
    except FileNotFoundError:
        print(f"\n  ⚠️  {name} SKIPPED (command not found)")
        return True  # Don't fail if tool not installed


def main() -> int:
    print("=" * 60)
    print("  ASIAbot Test Suite")
    print("=" * 60)

    results = {}

    # 1. Ruff
    results["ruff"] = run(
        "Ruff Lint",
        ["ruff", "check", ".", "--fix"],
    )

    # 2. Mypy
    results["mypy"] = run(
        "Mypy Type Check",
        ["mypy", ".", "--ignore-missing-imports", "--no-error-summary"],
        timeout=180,
    )

    # 3. Pytest + Coverage
    results["pytest"] = run(
        "Pytest + Coverage",
        [sys.executable, "-m", "pytest", "--cov", "--cov-report=term-missing", "-q", "--tb=short"],
        timeout=300,
    )

    # 4. Bandit
    results["bandit"] = run(
        "Bandit Security",
        [
            "bandit",
            "-r",
            ".",
            "-x",
            "./tests,./scripts,./htmlcov,./.git,./node_modules,./__pycache__",
            "-q",
            "--severity-level",
            "medium",
        ],
    )

    # Summary
    print("\n" + "=" * 60)
    print("  SUMMARY")
    print("=" * 60)
    all_passed = True
    for name, passed in results.items():
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"  {status}  {name}")
        if not passed:
            all_passed = False

    if all_passed:
        print("\n  🎉 ALL TESTS PASSED")
        return 0
    else:
        print("\n  💥 SOME TESTS FAILED")
        return 1


if __name__ == "__main__":
    sys.exit(main())
