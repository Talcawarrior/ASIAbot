"""
Structural integrity tests — verify critical files and build capability.

These tests catch "accidental deletion" regressions like the one in commit 2f7ddde
where git add -A accidentally deleted 56 frontend files + 3 config files.
"""

import os
import subprocess
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# ── Critical files that must always exist ──────────────────────────────────────

CRITICAL_FILES = [
    # Frontend config
    ("package.json", "npm package manifest"),
    ("tsconfig.json", "TypeScript configuration"),
    ("next.config.ts", "Next.js configuration"),
    ("postcss.config.mjs", "PostCSS configuration"),
    # Frontend source
    ("src/app/page.tsx", "Dashboard main page"),
    ("src/app/layout.tsx", "Dashboard layout"),
    ("src/app/globals.css", "Global styles"),
    ("src/lib/api.ts", "API client library"),
    # Python core
    ("main.py", "Bot entry point"),
    ("api.py", "FastAPI application"),
    ("config/settings.py", "Configuration settings"),
    ("database/models.py", "Database models"),
    ("engine/calculator.py", "Weather engine calculator"),
    ("executor/bet_placer.py", "Bet placement logic"),
    # Build output
    ("out/index.html", "Built dashboard (run: npx next build)"),
]


@pytest.mark.parametrize("relpath,description", CRITICAL_FILES, ids=[f[0] for f in CRITICAL_FILES])
def test_critical_file_exists(relpath: str, description: str):
    """Every critical file must exist for the project to build and run."""
    full = os.path.join(ROOT, relpath)
    assert os.path.isfile(full), (
        f"CRITICAL FILE MISSING: {relpath} ({description})\n"
        f"This file was likely accidentally deleted.\n"
        f"Recover with: git checkout HEAD~1 -- {relpath}"
    )


# ── Critical directories ───────────────────────────────────────────────────────

CRITICAL_DIRS = [
    ("src/components/ui", "Shadcn UI components"),
    ("src/hooks", "React hooks"),
    ("src/lib", "Shared libraries"),
    ("asi_engine", "ASI engine modules"),
    ("config", "Configuration modules"),
    ("database", "Database modules"),
    ("engine", "Core engine modules"),
    ("executor", "Execution modules"),
    ("scrapers", "Data scrapers"),
    ("utils", "Utility modules"),
    ("tests", "Test suite"),
]


@pytest.mark.parametrize("reldir,description", CRITICAL_DIRS, ids=[d[0] for d in CRITICAL_DIRS])
def test_critical_dir_exists(reldir: str, description: str):
    """Every critical directory must exist."""
    full = os.path.join(ROOT, reldir)
    assert os.path.isdir(full), f"CRITICAL DIR MISSING: {reldir} ({description})"


# ── Frontend build capability ──────────────────────────────────────────────────


def test_dashboard_can_build():
    """Verify `npx next build` succeeds. Catches broken imports, missing deps, etc."""
    npx = "npx.cmd" if sys.platform == "win32" else "npx"
    result = subprocess.run(
        [npx, "next", "build"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, (
        f"Dashboard build FAILED (exit code {result.returncode})\n"
        f"STDOUT:\n{result.stdout[-2000:]}\n"
        f"STDERR:\n{result.stderr[-2000:]}"
    )


# ── package.json integrity ─────────────────────────────────────────────────────


def test_package_json_has_required_deps():
    """Verify package.json includes all critical dependencies."""
    import json

    pkg_path = os.path.join(ROOT, "package.json")
    if not os.path.isfile(pkg_path):
        pytest.skip("package.json not found")

    with open(pkg_path) as f:
        pkg = json.load(f)

    required_deps = ["next", "react", "react-dom", "recharts"]
    all_deps = {**pkg.get("dependencies", {}), **pkg.get("devDependencies", {})}

    missing = [d for d in required_deps if d not in all_deps]
    assert not missing, f"Missing dependencies in package.json: {missing}"


# ── .env.example exists ────────────────────────────────────────────────────────


def test_env_example_exists():
    """Verify .env.example exists so new developers know what env vars are needed."""
    env_example = os.path.join(ROOT, ".env.example")
    assert os.path.isfile(env_example), ".env.example is missing — new devs won't know what env vars to set"
