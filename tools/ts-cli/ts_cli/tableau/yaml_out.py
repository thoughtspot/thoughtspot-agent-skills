"""Shim — dump_tml_yaml moved to ts_cli.tml_common (BL-063 PR 5).

Kept so existing imports (tableau_translate re-export, older callers) keep
resolving. New code imports from ts_cli.tml_common directly.
"""
from ts_cli.tml_common import dump_tml_yaml  # noqa: F401
