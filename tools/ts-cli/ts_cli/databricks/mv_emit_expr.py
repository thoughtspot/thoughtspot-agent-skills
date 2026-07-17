"""TS-formula tokenizer + recursive-descent parser → dict-AST (reverse direction).

Pure: stdlib only. No I/O. Vendored into the Genie notebook.
"""
from __future__ import annotations


class UntranslatableError(Exception):
    """A ThoughtSpot formula construct has no deterministic Databricks-SQL translation."""
