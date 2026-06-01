# tools/ts-cli/tests/test_report_walker.py
"""Tests for report.walker — per-source-type dep walk."""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock

from ts_cli.report.walker import (
    dependents_query_type_for,
    walk_dependents,
)
from ts_cli.report.schema import SourceDescriptor


class TestDependentsQueryTypeFor:
    def test_table_uses_logical_table(self):
        src = SourceDescriptor(input="x", guid="g", type="LOGICAL_TABLE", name="x", parent=None)
        assert dependents_query_type_for(src) == "LOGICAL_TABLE"

    def test_column_uses_logical_column(self):
        src = SourceDescriptor(input="x", guid="g", type="LOGICAL_COLUMN", name="x",
                               parent={"guid": "t", "name": "T", "type": "LOGICAL_TABLE"})
        assert dependents_query_type_for(src) == "LOGICAL_COLUMN"

    def test_set_uses_logical_column(self):
        """Sets are queried as LOGICAL_COLUMN — see open-items.md #11."""
        src = SourceDescriptor(input="x", guid="g", type="LOGICAL_COLUMN", name="x", parent=None)
        assert dependents_query_type_for(src) == "LOGICAL_COLUMN"
