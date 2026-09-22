"""Unit tests for check_python_redefinitions.

The gate exists because this repo runs no Python linter at all, and Python keeps
the LAST binding silently. The merge shape that motivated it: two branches each
adding `def check_a6(...)` to the same module in different hunks, plus the
identical one-line append to `ALL_CHECKS`. Git merges both without a conflict,
the module defines the name twice, one function becomes dead code, and
`len(ALL_CHECKS)` still looks right.

The no-false-positive cases below matter as much as the detections. A gate that
flags `try: import tomllib / except ImportError: import tomli as tomllib` — real
code in `check_version_sync.py` — would be unmergeable on its first run and would
be deleted rather than fixed.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import check_python_redefinitions as cpr  # noqa: E402


def _names(src):
    return [(n, a, b) for n, a, b in cpr.duplicates_in(src)]


# --- detections ------------------------------------------------------------

def test_duplicate_def_is_flagged():
    # The audit-check collision, reduced.
    src = "def check_a6():\n    pass\n\n\ndef check_a6():\n    pass\n"
    assert _names(src) == [("check_a6", 1, 5)]


def test_name_listed_twice_in_one_import_list_is_flagged():
    # A real hit on the first run: `display_title` appeared twice in one
    # `from ... import (...)` list — the shape a two-person edit of a long
    # re-export list produces.
    src = "from m import (\n    a,\n    display_title,\n    display_title,\n)\n"
    assert _names(src) == [("display_title", 3, 4)]


def test_repeated_plain_import_is_flagged():
    src = "import sys\nimport os\nimport sys\n"
    assert _names(src) == [("sys", 1, 3)]


def test_duplicate_class_is_flagged():
    src = "class A:\n    pass\n\n\nclass A:\n    pass\n"
    assert _names(src) == [("A", 1, 5)]


def test_import_then_def_of_the_same_name_is_flagged():
    src = "from m import helper\n\n\ndef helper():\n    pass\n"
    assert _names(src) == [("helper", 1, 4)]


# --- deliberate non-detections ---------------------------------------------

def test_try_except_import_fallback_is_not_flagged():
    # Real code in check_version_sync.py. Both bindings are inside handlers, so
    # neither is a direct child of the module body.
    src = (
        "try:\n"
        "    import tomllib\n"
        "except ImportError:\n"
        "    import tomli as tomllib\n"
    )
    assert _names(src) == []


def test_rebinding_inside_a_function_is_not_flagged():
    src = "import json\n\n\ndef f():\n    import json\n    return json\n"
    assert _names(src) == []


def test_noqa_f811_suppresses():
    src = "import sys\nimport sys  # noqa: F811 — deliberate\n"
    assert _names(src) == []


def test_star_import_is_ignored():
    src = "from m import *\nfrom n import *\n"
    assert _names(src) == []


def test_aliases_are_distinct_names():
    # `import x as a` / `import x as b` binds two different names, not a rebind.
    src = "import collections as c1\nimport collections as c2\n"
    assert _names(src) == []


def test_dotted_import_binds_the_root_package():
    src = "import os.path\nimport os\n"
    assert _names(src) == [("os", 1, 2)]


def test_clean_module_reports_nothing():
    src = "import os\nimport sys\n\n\ndef f():\n    pass\n\n\nclass C:\n    pass\n"
    assert _names(src) == []
