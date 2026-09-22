# Validation Scripts

Lightweight validation tools for the thoughtspot-agent-skills repo. Run before every commit
to catch integration problems, anti-patterns, and consistency issues without needing
a live ThoughtSpot or Snowflake instance.

---

## Scripts

### `check_references.py`

Verifies every file path referenced in `SKILL.md` files actually exists in the repo.
Resolves runtime-specific path prefixes back to repo paths before checking:

- `~/.claude/shared/` → `agents/shared/`
- `~/.claude/mappings/` → `agents/shared/mappings/`
- `~/.claude/skills/` → `agents/cli/` (Claude-only skills like ts-profile-snowflake remain under `agents/claude/`)
- `../../shared/` (CoCo) → `agents/shared/`

```bash
python tools/validate/check_references.py
```

### `check_patterns.py`

Grep-based anti-pattern detector. Catches known bad patterns from real incidents:

| Pattern | Why it's wrong |
|---|---|
| `fqn:` inside a `connection:` block | Table TML connection must use `name:` only |
| `aggregation:` inside `formulas[]` | `aggregation:` belongs in `columns[]` only |
| `connection_fqn` in Python | CLI uses string name, not GUID |
| `%%` in Python help strings | Typer escapes `%` — `%%` shows literally to users |

```bash
python tools/validate/check_patterns.py
```

### `check_yaml.py`

Validates all fenced ` ```yaml ``` ` code blocks in `.md` files parse without error.
Run after editing any schema, mapping, or worked-example file.

```bash
python tools/validate/check_yaml.py

# Check a single file
python tools/validate/check_yaml.py --path agents/shared/schemas/thoughtspot-table-tml.md
```

### `check_version_sync.py`

Verifies `ts_cli/__init__.py __version__` matches `pyproject.toml version`.
Both must be bumped together — this script enforces it. It also rejects a
`CHANGELOG.md` that marks the same ts-cli release twice.

```bash
python tools/validate/check_version_sync.py
```

With `--base`, it additionally requires the version to be **unreleased** (BL-274):
if the branch changes `tools/ts-cli/ts_cli`, its version must not be the base's
version, nor any release already marked in the base's `CHANGELOG.md`.

```bash
python tools/validate/check_version_sync.py --base origin/main   # CI
```

`--base` is opt-in because it needs the base ref, which pre-commit and a
`git archive` export do not have. CI passes it and checks out with
`fetch-depth: 0`. When `--base` **is** passed and the ref cannot be resolved,
that is a FAIL, not a skip — a gate that no-ops when it cannot see its input is
decorative.

Why this needs its own rule: two branches bumping to the *same* version change
the same two lines to the same value, so git auto-merges with no conflict and the
`__init__.py`/`pyproject.toml` invariant still holds. Consistency cannot see a
collision; only novelty can. Two branches open at once still both pass — the
second is caught when it updates from `main`, which branch protection's
`strict: true` requires before merge.

---

## Run all at once

```bash
python tools/validate/check_references.py && \
python tools/validate/check_patterns.py && \
python tools/validate/check_yaml.py && \
python tools/validate/check_version_sync.py && \
echo "All checks passed."
```

---

## When to run

- **Before every commit** — catch issues before they reach GitHub
- **After editing any SKILL.md** — run `check_references.py`
- **After editing any mapping or schema file** — run `check_yaml.py` and `check_patterns.py`
- **After bumping the ts-cli version** — run `check_version_sync.py`
- **In CI** — add the "run all at once" block above as a workflow step

---

## Requirements

Standard library only, except:
- `check_yaml.py` requires `PyYAML` (already a ts-cli dependency: `pip install -e tools/ts-cli`)
- `check_version_sync.py` uses `tomllib` (Python 3.11+) or falls back to regex parsing
