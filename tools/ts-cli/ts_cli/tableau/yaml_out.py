"""TML YAML serialization — proper quoting for formula expressions."""

import re
from typing import Any


# ---------------------------------------------------------------------------
# TML YAML serialization — proper quoting for formula expressions
# ---------------------------------------------------------------------------

def dump_tml_yaml(data: dict) -> str:
    """Serialize a TML dict to YAML with proper quoting for formula expressions.

    Handles two problems that plain yaml.dump gets wrong for TML:
    1. Formula expressions contain : [] {} # which YAML misinterprets
    2. Long expressions get line-wrapped, producing invalid multi-line TML

    Values matching TML-sensitive patterns are double-quoted automatically.
    """
    import yaml

    class _QuotedStr(str):
        pass

    def _quoted_representer(dumper: yaml.Dumper, val: str) -> yaml.ScalarNode:
        return dumper.represent_scalar("tag:yaml.org,2002:str", val, style='"')

    _NEEDS_QUOTING = re.compile(r"[\[\]{}:#>|&*!%@`]|^\s|^'|^\"")

    def _quote_values(obj: Any) -> Any:
        if isinstance(obj, dict):
            return {_quote_values(k): _quote_values(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [_quote_values(v) for v in obj]
        if isinstance(obj, str) and _NEEDS_QUOTING.search(obj):
            return _QuotedStr(obj)
        return obj

    class _TmlDumper(yaml.Dumper):
        pass

    _TmlDumper.add_representer(_QuotedStr, _quoted_representer)

    quoted_data = _quote_values(data)
    return yaml.dump(
        quoted_data,
        Dumper=_TmlDumper,
        default_flow_style=False,
        allow_unicode=True,
        width=100000,
    )
