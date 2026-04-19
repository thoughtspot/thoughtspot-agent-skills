"""
fixtures.py — parse worked-example .md files into test fixtures.

Provides helpers that extract input/output YAML blocks from the documented,
live-verified worked examples in agents/shared/worked-examples/snowflake/.

Used by test_worked_examples.py. Not a test file itself.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

try:
    import yaml
except ImportError:
    raise ImportError("PyYAML is required: pip install PyYAML")

# Path anchors
_TESTS_DIR = Path(__file__).resolve().parent        # tools/ts-cli/tests/
_REPO_ROOT = _TESTS_DIR.parent.parent.parent         # repo root
WORKED_EXAMPLES_DIR = _REPO_ROOT / "agents" / "shared" / "worked-examples" / "snowflake"

_FENCE_YAML_START = re.compile(r"^```ya?ml\s*$", re.IGNORECASE)
_FENCE_SQL_START = re.compile(r"^```sql\s*$", re.IGNORECASE)
_FENCE_END = re.compile(r"^```\s*$")
_H2 = re.compile(r"^## (.+)$")


def _iter_blocks(content: str):
    """
    Yield (last_h2_heading, language, block_content) for every fenced code block.
    language is 'yaml', 'sql', or 'other'.
    """
    lines = content.splitlines()
    current_heading = ""
    in_block = False
    lang = "other"
    block_lines: list[str] = []

    for line in lines:
        if not in_block:
            h2 = _H2.match(line)
            if h2:
                current_heading = h2.group(1).strip()
            elif _FENCE_YAML_START.match(line):
                in_block = True
                lang = "yaml"
                block_lines = []
            elif _FENCE_SQL_START.match(line):
                in_block = True
                lang = "sql"
                block_lines = []
            elif line.strip().startswith("```"):
                in_block = True
                lang = "other"
                block_lines = []
        else:
            if _FENCE_END.match(line):
                yield current_heading, lang, "\n".join(block_lines)
                in_block = False
                block_lines = []
            else:
                block_lines.append(line)


def _safe_load(content: str) -> Optional[dict]:
    """Parse YAML safely; return None if not a dict."""
    try:
        parsed = yaml.safe_load(content)
        return parsed if isinstance(parsed, dict) else None
    except yaml.YAMLError:
        return None


# ---------------------------------------------------------------------------
# Public loaders
# ---------------------------------------------------------------------------

def load_ts_to_snowflake_example_1() -> dict:
    """
    Load Example 1 from ts-to-snowflake.md (Retail Sales worksheet).

    Returns:
        {
            "input_tml":  dict — the worksheet TML (has 'worksheet' or 'guid' key)
            "output_sv":  dict — the Semantic View YAML (has 'name' and 'tables' keys)
        }
    """
    path = WORKED_EXAMPLES_DIR / "ts-to-snowflake.md"
    content = path.read_text(encoding="utf-8")

    input_tml: Optional[dict] = None
    output_sv: Optional[dict] = None

    # The first example ends at the second '---' divider line in the file.
    # We stop collecting after we find the output SV block.
    for heading, lang, block in _iter_blocks(content):
        if lang != "yaml":
            continue
        parsed = _safe_load(block)
        if parsed is None:
            continue

        if input_tml is None and ("worksheet" in parsed or ("guid" in parsed and "worksheet" in str(parsed))):
            input_tml = parsed

        if output_sv is None and "tables" in parsed and "name" in parsed:
            output_sv = parsed

        # Stop once we have both (don't load example 2)
        if input_tml and output_sv:
            break

    return {"input_tml": input_tml, "output_sv": output_sv}


def load_ts_to_snowflake_example_2() -> dict:
    """
    Load Example 2 from ts-to-snowflake.md (Dunder Mifflin advanced model).

    Returns:
        {
            "input_tml":  dict — the model TML
            "output_sv":  dict — the Semantic View YAML
        }
    """
    path = WORKED_EXAMPLES_DIR / "ts-to-snowflake.md"
    content = path.read_text(encoding="utf-8")

    # Example 2 starts at the second '## Input' section
    input_blocks: list[dict] = []
    output_blocks: list[dict] = []

    for heading, lang, block in _iter_blocks(content):
        if lang != "yaml":
            continue
        parsed = _safe_load(block)
        if parsed is None:
            continue

        if "Input" in heading and ("worksheet" in parsed or "model" in parsed):
            input_blocks.append(parsed)
        if ("Output" in heading or "Step 7" in heading) and "tables" in parsed and "name" in parsed:
            output_blocks.append(parsed)

    # Take the second occurrence of each (example 2)
    input_tml = input_blocks[1] if len(input_blocks) > 1 else (input_blocks[0] if input_blocks else None)
    output_sv = output_blocks[-1] if output_blocks else None

    return {"input_tml": input_tml, "output_sv": output_sv}


def load_ts_from_snowflake_example() -> dict:
    """
    Load ts-from-snowflake.md (BIRD Superhero example).

    Returns:
        {
            "input_ddl":       str  — CREATE OR REPLACE SEMANTIC VIEW DDL
            "output_model_tml": dict — the ThoughtSpot Model TML
        }
    """
    path = WORKED_EXAMPLES_DIR / "ts-from-snowflake.md"
    content = path.read_text(encoding="utf-8")

    input_ddl = ""
    output_model: Optional[dict] = None

    for heading, lang, block in _iter_blocks(content):
        if lang == "sql" and not input_ddl:
            # First SQL block is the semantic view DDL
            input_ddl = block.strip()
        if lang == "yaml":
            parsed = _safe_load(block)
            if parsed and "model" in parsed:
                output_model = parsed  # take the last model TML block

    return {"input_ddl": input_ddl, "output_model_tml": output_model}
