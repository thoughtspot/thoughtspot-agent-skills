"""ts-convert-to-dbt Case B — reading and writing an existing dbt project safely.

Three rules `ts dbt-export sync` depends on, kept in one place:

- **Every property file counts.** dbt reads `*.yml` and `*.yaml` alike, so a
  `schema.yaml` project is not an empty one (`property_files`).
- **A file that cannot be parsed stops the run.** dbt renders Jinja in property
  files before parsing YAML, so `{% for %}` blocks or an unquoted
  `{{ doc('x') }}` are valid dbt and invalid YAML. Reading such a file as empty
  made `sync` rewrite it with only the generated models (PR #506 review,
  blocker 4); `unreadable_property_files` lets the caller refuse first.
- **Writes are all or nothing.** `commit_writes` stages every file beside its
  target and only then swaps them in, so a failure part-way leaves the project
  as it was rather than half-written.
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

import yaml

PROPERTY_SUFFIXES = (".yml", ".yaml")


def property_files(models_dir: Path, stem: "str | None" = None) -> list[Path]:
    """Every dbt property file under `models_dir` (both suffixes), sorted;
    only those named `<stem>.yml` / `<stem>.yaml` when `stem` is given."""
    if not models_dir.is_dir():
        return []
    return sorted(p for p in models_dir.rglob("*")
                  if p.is_file() and p.suffix in PROPERTY_SUFFIXES
                  and (stem is None or p.stem == stem))


def unreadable_property_files(project_dir: Path) -> list[dict]:
    """`[{"path", "reason"}]` for each property file under models/ that does not
    parse to a mapping. Empty files are fine (dbt ignores them)."""
    out = []
    for path in property_files(project_dir / "models"):
        rel = str(path.relative_to(project_dir))
        try:
            text = path.read_text(encoding="utf-8")
            doc = yaml.safe_load(text)
        except (OSError, UnicodeDecodeError) as exc:
            out.append({"path": rel, "reason": f"cannot be read: {exc}"})
            continue
        except yaml.YAMLError as exc:
            jinja = "{{" in text or "{%" in text
            first = str(exc).splitlines()[0] if str(exc) else type(exc).__name__
            out.append({"path": rel, "reason": (
                "contains dbt Jinja, which is not plain YAML" if jinja
                else f"is not valid YAML ({first})")})
            continue
        if doc is not None and not isinstance(doc, dict):
            out.append({"path": rel, "reason": "does not hold a YAML mapping at the top level"})
    return out


def commit_writes(writes: "dict[Path, str]") -> None:
    """Write every file, or none of them.

    Each new content is first written to a temp file in its target's own
    directory (so the final rename stays on one filesystem and is atomic). Only
    once ALL of them are staged are they renamed into place; if staging fails,
    the temp files are removed and nothing in the project has changed.
    """
    staged: list[tuple[str, Path]] = []
    try:
        for target, content in writes.items():
            target.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=target.parent)
            staged.append((tmp, target))
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(content)
    except BaseException:
        for tmp, _ in staged:
            try:
                os.unlink(tmp)
            except OSError:
                pass
        raise
    for tmp, target in staged:
        os.replace(tmp, target)
