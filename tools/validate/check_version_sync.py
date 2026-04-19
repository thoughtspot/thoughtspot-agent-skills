#!/usr/bin/env python3
"""
check_version_sync.py — verify __init__.py version matches pyproject.toml.

ts_cli/__init__.py __version__ and pyproject.toml version must always be in sync.
Bump both together when releasing a new version.

Usage:
    python tools/validate/check_version_sync.py
    python tools/validate/check_version_sync.py --root /path/to/repo
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

try:
    import tomllib  # Python 3.11+
except ImportError:
    try:
        import tomli as tomllib  # type: ignore[no-redef]
    except ImportError:
        tomllib = None  # type: ignore[assignment]


def read_init_version(init_file: Path) -> str | None:
    content = init_file.read_text(encoding="utf-8")
    m = re.search(r'^__version__\s*=\s*["\']([^"\']+)["\']', content, re.MULTILINE)
    return m.group(1) if m else None


def read_pyproject_version(pyproject_file: Path) -> str | None:
    content = pyproject_file.read_text(encoding="utf-8")
    if tomllib is not None:
        try:
            data = tomllib.loads(content)
            return data.get("project", {}).get("version")
        except Exception:
            pass
    # Fallback: regex parse
    m = re.search(r'^version\s*=\s*["\']([^"\']+)["\']', content, re.MULTILINE)
    return m.group(1) if m else None


def main() -> int:
    parser = argparse.ArgumentParser(description="Check ts-cli version sync.")
    parser.add_argument("--root", default=".", help="Repo root directory (default: current dir)")
    args = parser.parse_args()

    repo_root = Path(args.root).resolve()
    init_file = repo_root / "tools/ts-cli/ts_cli/__init__.py"
    pyproject_file = repo_root / "tools/ts-cli/pyproject.toml"

    if not init_file.exists():
        print(f"ERROR: {init_file} not found")
        return 1
    if not pyproject_file.exists():
        print(f"ERROR: {pyproject_file} not found")
        return 1

    init_ver = read_init_version(init_file)
    pyproject_ver = read_pyproject_version(pyproject_file)

    if init_ver is None:
        print(f"ERROR: could not parse __version__ from {init_file.relative_to(repo_root)}")
        return 1
    if pyproject_ver is None:
        print(f"ERROR: could not parse version from {pyproject_file.relative_to(repo_root)}")
        return 1

    if init_ver == pyproject_ver:
        print(f"PASS  version sync: {init_ver}")
        return 0
    else:
        print(f"FAIL  version mismatch:")
        print(f"        ts_cli/__init__.py  : {init_ver}")
        print(f"        pyproject.toml      : {pyproject_ver}")
        print()
        print("Bump both to the same version before committing.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
