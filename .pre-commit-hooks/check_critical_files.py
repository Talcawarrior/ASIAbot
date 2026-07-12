#!/usr/bin/env python3
"""Pre-commit hook: Block commits that delete critical project files."""

import subprocess
import sys

# Files that MUST exist for the project to build/run
CRITICAL_FILES = [
    # Frontend
    "package.json",
    "tsconfig.json",
    "next.config.ts",
    "postcss.config.mjs",
    "src/app/page.tsx",
    "src/app/layout.tsx",
    "src/app/globals.css",
    "src/lib/api.ts",
    # Python core
    "main.py",
    "api.py",
    "config/settings.py",
    "database/models.py",
    "engine/calculator.py",
    "executor/bet_placer.py",
    # Config
    ".env.example",
    "requirements.txt",
    "pyproject.toml",
    "pytest.ini",
    "mypy.ini",
]


def get_deleted_files() -> set[str]:
    """Get files deleted in the current staging area."""
    result = subprocess.run(
        ["git", "diff", "--cached", "--name-only", "--diff-filter=D"],
        capture_output=True,
        text=True,
    )
    return set(result.stdout.strip().split("\n")) if result.stdout.strip() else set()


def main():
    deleted = get_deleted_files()
    violations = [f for f in CRITICAL_FILES if f in deleted]

    if violations:
        print("❌ BLOCKED: Critical files would be deleted:")
        for f in violations:
            print(f"   - {f}")
        print()
        print("These files are required for the project to build and run.")
        print("If you really need to delete them, use: git commit --no-verify")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
