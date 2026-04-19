#!/usr/bin/env python3
"""
check_secrets.py — scan staged files for accidental credential exposure.

Checks staged content (not full history) for:
  1. Credential files force-added despite being gitignored
     (*.env, *-profiles.json, *.pem, *.p8, *.key, *token*.txt, etc.)
  2. PEM / private key headers in any file
  3. JWT tokens (three base64url segments separated by dots — eyJ...eyJ...sig)
  4. Long Bearer tokens (64+ chars of base64/hex not in a template line)
  5. Hardcoded credential assignments (password=, secret=, api_key= followed by a
     non-placeholder value of 12+ chars)
  6. URLs with embedded credentials (https://user:pass@host)

False-positive mitigations:
  - Lines containing {variable} template placeholders are skipped
  - Values that look like placeholder text (YOUR_, REPLACE_, <...>, example) are skipped
  - Lines inside gitignored patterns (already blocked by check 1) are not double-counted

Usage:
    python tools/validate/check_secrets.py           # scan staged files (pre-commit mode)
    python tools/validate/check_secrets.py --all     # scan all tracked files (full repo)
    python tools/validate/check_secrets.py --root .
"""
from __future__ import annotations

import argparse
import fnmatch
import re
import subprocess
import sys
from pathlib import Path


# ---------------------------------------------------------------------------
# Credential filename patterns (mirrors .gitignore)
# ---------------------------------------------------------------------------

CREDENTIAL_FILENAME_PATTERNS = [
    "*.env",
    ".env.*",
    "*-profiles.json",
    "*_profiles.json",
    "*.pem",
    "*.p8",
    "*.key",
    "*.pfx",
    "*.p12",
    "*token*.txt",
    "*secret*.txt",
    "*credentials*.json",
    "*credentials*.yaml",
]


# ---------------------------------------------------------------------------
# Content patterns
# ---------------------------------------------------------------------------

# PEM private key header — any variant
_PEM_HEADER = re.compile(
    r"-----BEGIN\s+(RSA |EC |OPENSSH |DSA |ENCRYPTED |)PRIVATE KEY-----"
)

# JWT: three base64url segments (header.payload.signature), first two starting with eyJ
_JWT = re.compile(
    r"eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"
)

# Bearer token: Bearer followed by 64+ chars of base64/hex (not a template)
_BEARER = re.compile(r"Bearer\s+([A-Za-z0-9+/=_-]{64,})")

# Hardcoded credential assignment:
#   (password|secret|token|api_key|apikey) followed by = or : then a quoted or unquoted
#   value of 12+ chars that doesn't look like a placeholder
_CRED_ASSIGN = re.compile(
    r'(?i)\b(password|secret|token|api[_\-]?key|auth[_\-]?key)\s*[:=]\s*'
    r'["\']?([A-Za-z0-9+/=$@!#%^&*_\-]{12,})["\']?'
)

# URL with embedded credentials: scheme://user:pass@host
# Minimum 8 chars for the credential portion to avoid matching short example values like "pass"
_URL_CREDS = re.compile(r"https?://[A-Za-z0-9._~\-]+:[A-Za-z0-9._~\-!$&'()*+,;=@%]{8,}@")


# ---------------------------------------------------------------------------
# Placeholder heuristics — skip lines that look like documentation examples
# ---------------------------------------------------------------------------

# Template variable placeholder in the same line (e.g. Bearer {ts_token})
_TEMPLATE_VAR = re.compile(r"\{[A-Za-z_][A-Za-z0-9_]*\}")

# Common placeholder markers in values
_PLACEHOLDER_MARKERS = (
    "YOUR_", "your_", "REPLACE", "replace", "EXAMPLE", "example",
    "PLACEHOLDER", "placeholder", "xxx", "XXX", "<", "[",
    "INSERT_", "insert_", "MY_", "my_", "test", "TEST",
    "dummy", "DUMMY", "fake", "FAKE",
)


_IDENTIFIER_RE = re.compile(r'^[A-Za-z_][A-Za-z0-9_]*$')


def _is_placeholder_value(value: str) -> bool:
    if len(value) < 4:
        return True
    # Pure Python/shell identifier (variable name, not a literal string value)
    # e.g. password=passphrase_bytes — 'passphrase_bytes' is a variable, not a secret
    if _IDENTIFIER_RE.match(value):
        return True
    return any(value.startswith(m) or m in value for m in _PLACEHOLDER_MARKERS)


def _line_has_template(line: str) -> bool:
    return bool(_TEMPLATE_VAR.search(line))


# ---------------------------------------------------------------------------
# Git helpers
# ---------------------------------------------------------------------------

def _get_staged_files(repo_root: Path) -> list[Path]:
    result = subprocess.run(
        ["git", "diff", "--cached", "--name-only", "--diff-filter=ACM"],
        capture_output=True, text=True, cwd=repo_root,
    )
    return [
        repo_root / f
        for f in result.stdout.splitlines()
        if (repo_root / f).exists()
    ]


def _get_all_tracked_files(repo_root: Path) -> list[Path]:
    result = subprocess.run(
        ["git", "ls-files"],
        capture_output=True, text=True, cwd=repo_root,
    )
    return [
        repo_root / f
        for f in result.stdout.splitlines()
        if (repo_root / f).exists()
    ]


# ---------------------------------------------------------------------------
# Check 1: credential filename patterns
# ---------------------------------------------------------------------------

def check_credential_filenames(files: list[Path], repo_root: Path) -> list[str]:
    hits = []
    for path in files:
        name = path.name
        for pattern in CREDENTIAL_FILENAME_PATTERNS:
            if fnmatch.fnmatch(name, pattern):
                rel = path.relative_to(repo_root)
                hits.append(
                    f"{rel}: filename matches credential pattern '{pattern}' — "
                    "this file should be gitignored, not committed. "
                    "Remove it: git rm --cached {rel}"
                )
                break
    return hits


# ---------------------------------------------------------------------------
# Check 2–6: content scanning
# ---------------------------------------------------------------------------

# File extensions to skip entirely for content scanning
_SKIP_SUFFIXES = {
    ".png", ".jpg", ".jpeg", ".gif", ".ico", ".svg",
    ".pdf", ".zip", ".tar", ".gz",
    ".pyc", ".pyo",
}


def _scan_file_content(path: Path, repo_root: Path) -> list[str]:
    if path.suffix.lower() in _SKIP_SUFFIXES:
        return []

    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []

    rel = path.relative_to(repo_root)
    hits = []

    for line_num, line in enumerate(text.splitlines(), 1):
        # Check 2: PEM private key header
        if _PEM_HEADER.search(line):
            hits.append(f"{rel}:{line_num}: PEM private key header found — never commit key material")

        # Skip template lines for remaining checks
        if _line_has_template(line):
            continue

        # Check 3: JWT token
        m = _JWT.search(line)
        if m:
            hits.append(
                f"{rel}:{line_num}: JWT token found — "
                "remove the credential before committing"
            )

        # Check 4: Long Bearer token
        m = _BEARER.search(line)
        if m:
            token = m.group(1)
            if not _is_placeholder_value(token):
                hits.append(
                    f"{rel}:{line_num}: Bearer token ({len(token)} chars) — "
                    "use a template placeholder like {{token}} in documentation"
                )

        # Check 5: Hardcoded credential assignment
        m = _CRED_ASSIGN.search(line)
        if m:
            value = m.group(2)
            if not _is_placeholder_value(value):
                field = m.group(1).lower()
                hits.append(
                    f"{rel}:{line_num}: hardcoded {field} value — "
                    "use an environment variable or template placeholder instead"
                )

        # Check 6: URL with embedded credentials
        if _URL_CREDS.search(line):
            hits.append(
                f"{rel}:{line_num}: URL with embedded credentials (user:pass@host) — "
                "remove the password from the URL"
            )

    return hits


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description="Scan for accidental credential exposure.")
    parser.add_argument("--root", default=".", help="Repo root (default: current dir)")
    parser.add_argument(
        "--all", action="store_true",
        help="Scan all tracked files (default: staged files only)",
    )
    args = parser.parse_args()

    repo_root = Path(args.root).resolve()

    if args.all:
        files = _get_all_tracked_files(repo_root)
        mode = "all tracked files"
    else:
        files = _get_staged_files(repo_root)
        mode = "staged files"

    if not files:
        print(f"No {mode} to scan.")
        return 0

    total_hits = 0

    # Check 1: filename patterns
    for msg in check_credential_filenames(files, repo_root):
        print(f"FAIL  {msg}")
        total_hits += 1

    # Checks 2–6: content
    for path in files:
        for msg in _scan_file_content(path, repo_root):
            print(f"FAIL  {msg}")
            total_hits += 1

    print()
    if total_hits:
        print(f"{total_hits} potential secret(s) found. Remove them before committing.")
        return 1

    print(f"No secrets detected in {len(files)} file(s).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
