"""Build the vendored Genie notebook and exec it end-to-end — parse → translate
→ build model TML → lint — proving the concatenated closure is self-contained."""
import pathlib
import sys

TS_CLI_ROOT = pathlib.Path(__file__).resolve().parents[1]
REPO_ROOT = TS_CLI_ROOT.parents[1]
sys.path.insert(0, str(REPO_ROOT / "agents" / "databricks"))

from build_mv_lib import build_source  # noqa: E402

MV_YAML = """
version: 1.1
source: cat.sch.sales
dimensions:
  - name: region
    expr: region
measures:
  - name: total_amount
    expr: SUM(amount)
"""

TABLES = {"source": {"name": "SALES", "fqn": None, "create": False}}


def _load_namespace() -> dict:
    src = build_source(TS_CLI_ROOT)
    ns: dict = {}
    exec(compile(src, "databricks_mv_lib", "exec"), ns)
    return ns


def test_source_is_self_contained():
    src = build_source(TS_CLI_ROOT)
    assert src.startswith("# Databricks notebook source")
    # Every internal *import statement* must be stripped. Anchored on line
    # prefix (mirrors build_mv_lib.strip_internal_imports's own check) rather
    # than a blind substring search — several vendored modules carry provenance
    # docstrings that legitimately read "Relocated from ts_cli/..." in prose;
    # those are not import statements and must survive.
    assert not any(
        line.lstrip().startswith(("from ts_cli", "import ts_cli"))
        for line in src.splitlines())


def test_end_to_end_parse_translate_build_lint():
    ns = _load_namespace()
    parsed = ns["parse_metric_view"](MV_YAML)
    assert parsed["unsupported"] == []
    translated_doc = ns["translate_metric_view"](parsed, TABLES)
    assert translated_doc["skipped"] == []
    model_doc, build_info = ns["build_model_tml_dbx"](
        model_name="Vendored Smoke", parsed=parsed,
        translated_doc=translated_doc, tables=TABLES)
    assert ns["lint_tml"](model_doc) == []
    assert ns["validate_tml_invariants"](model_doc) == []
    yaml_text = ns["dump_tml_yaml"](model_doc)
    assert "Vendored Smoke" in yaml_text
    # import-response parsing is vendored too
    assert ns["extract_imported_guid"](
        [{"response": {"header": {"id_guid": "g"}}}]) == "g"
