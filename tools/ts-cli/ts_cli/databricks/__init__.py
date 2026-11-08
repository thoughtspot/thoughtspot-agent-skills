"""Databricks Metric View conversion substrate (BL-063 Phase 2).

Pure-function modules — stdlib + PyYAML only (no requests/typer/keyring) — whose
top-level names are unique across the set (hence the ``mvc_`` prefix in
mv_sql_calls.py, the ``_EMITTED_*`` / ``_FORMULA_TOKEN_RE`` / ``tokenize_formula``
spellings, and ``UntranslatableError`` living once in formula_common.py).

Both constraints originated in the Databricks Genie runtime, which vendored these
modules — with formula_common, formula_text, formula_week, sql_forms, tml_common and
tml_lint — into one notebook namespace via ``%run``, where the CLI's HTTP/auth deps did
not exist and two definitions of one name would collide. That runtime was retired on
2026-11-08 (archived at git tag ``runtimes-archive-2026-11-08``), so neither constraint
is required any more. The code still meets both; nothing enforces them now.
"""
