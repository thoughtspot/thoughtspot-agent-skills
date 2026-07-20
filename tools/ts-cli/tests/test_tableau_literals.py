"""Unit tests for ts_cli/tableau/literals.py — literal masking/unmasking."""
from __future__ import annotations

from ts_cli.tableau.literals import (
    PLACEHOLDER_RE,
    is_string_placeholder,
    literal_value,
    mask_literals,
    unmask_literals,
)


class TestMaskLiterals:
    def test_single_quoted_string_masked(self):
        masked, registry = mask_literals("[Status] = 'END'")
        assert "'END'" not in masked
        assert "[Status] = " in masked
        assert len(registry) == 1
        (entry,) = registry.values()
        assert entry == {"kind": "str", "raw": "'END'"}

    def test_double_quoted_string_masked(self):
        masked, registry = mask_literals('[Status] = "END"')
        assert '"END"' not in masked
        (entry,) = registry.values()
        assert entry == {"kind": "str", "raw": '"END"'}

    def test_date_literal_masked(self):
        masked, registry = mask_literals("[Date] > #2024-01-01#")
        assert "#" not in masked
        (entry,) = registry.values()
        assert entry == {"kind": "date", "raw": "#2024-01-01#"}

    def test_multiple_literals_get_distinct_tokens(self):
        masked, registry = mask_literals("[A] = 'x' or [B] = 'y'")
        assert len(registry) == 2
        # Two distinct placeholder tokens present in the masked text.
        import re
        tokens = re.findall(PLACEHOLDER_RE, masked)
        assert len(tokens) == 2
        assert tokens[0] != tokens[1]

    def test_placeholder_survives_whitespace_collapse(self):
        import re
        masked, registry = mask_literals("[A]   =    'x'")
        collapsed = re.sub(r"\s+", " ", masked).strip()
        # The placeholder token itself must come through the collapse intact —
        # re-extracting it must still resolve in the registry.
        token = re.search(PLACEHOLDER_RE, collapsed).group(0)
        assert token in registry

    def test_no_literals_no_op(self):
        masked, registry = mask_literals("[A] + [B]")
        assert masked == "[A] + [B]"
        assert registry == {}


class TestUnmaskLiterals:
    def test_round_trip_single_quoted(self):
        masked, registry = mask_literals("[Status] = 'END'")
        assert unmask_literals(masked, registry) == "[Status] = 'END'"

    def test_double_quoted_converted_to_single_quoted(self):
        masked, registry = mask_literals('[Status] = "END"')
        assert unmask_literals(masked, registry) == "[Status] = 'END'"

    def test_escaped_single_quote_round_trips(self):
        # Tableau escapes an embedded quote by doubling it: 'it''s'
        masked, registry = mask_literals("[Name] = 'it''s'")
        assert unmask_literals(masked, registry) == "[Name] = 'it''s'"

    def test_escaped_double_quote_converts_cleanly(self):
        # "she said ""hi""" -> unescape to `she said "hi"`, no need to escape
        # a double quote inside a single-quoted TS string.
        masked, registry = mask_literals('[X] = "she said ""hi"""')
        assert unmask_literals(masked, registry) == "[X] = 'she said \"hi\"'"

    def test_double_quoted_containing_apostrophe_gets_escaped(self):
        # A double-quoted source literal containing a bare apostrophe must be
        # escaped (doubled) when re-emitted as a single-quoted TS string.
        masked, registry = mask_literals('[X] = "it\'s fine"')
        assert unmask_literals(masked, registry) == "[X] = 'it''s fine'"

    def test_hash_inside_string_not_treated_as_date(self):
        masked, registry = mask_literals("[ID] = 'ID#123'")
        (entry,) = registry.values()
        assert entry["kind"] == "str"
        assert unmask_literals(masked, registry) == "[ID] = 'ID#123'"

    def test_date_literal_no_time(self):
        masked, registry = mask_literals("[Date] > #2024-01-01#")
        out = unmask_literals(masked, registry)
        assert out == "[Date] > to_date ( '2024-01-01' , 'yyyy-MM-dd' )"

    def test_date_literal_with_time(self):
        masked, registry = mask_literals("[Date] > #2024-01-01 12:30:00#")
        out = unmask_literals(masked, registry)
        assert out == "[Date] > to_date ( '2024-01-01 12:30:00' , 'yyyy-MM-dd HH:mm:ss' )"

    def test_unknown_placeholder_left_untouched(self):
        # Defensive: a token not present in the registry (shouldn't happen in
        # practice) is passed through rather than raising.
        assert unmask_literals("\x01L0\x01", {}) == "\x01L0\x01"

    def test_empty_string_literal_round_trips(self):
        masked, registry = mask_literals("[A] = ''")
        assert unmask_literals(masked, registry) == "[A] = ''"


class TestIsStringPlaceholder:
    def test_true_for_string_literal(self):
        masked, registry = mask_literals("'x'")
        token = masked.strip()
        assert is_string_placeholder(token, registry) is True

    def test_false_for_date_literal(self):
        masked, registry = mask_literals("#2024-01-01#")
        token = masked.strip()
        assert is_string_placeholder(token, registry) is False

    def test_false_for_non_placeholder_text(self):
        _, registry = mask_literals("'x'")
        assert is_string_placeholder("[Column]", registry) is False

    def test_tolerates_surrounding_whitespace(self):
        masked, registry = mask_literals("'x'")
        assert is_string_placeholder(f"  {masked.strip()}  ", registry) is True


class TestLiteralValue:
    def test_resolves_single_quoted_value(self):
        masked, registry = mask_literals("'month'")
        assert literal_value(masked.strip(), registry) == "month"

    def test_resolves_double_quoted_value(self):
        masked, registry = mask_literals('"month"')
        assert literal_value(masked.strip(), registry) == "month"

    def test_none_for_date_placeholder(self):
        masked, registry = mask_literals("#2024-01-01#")
        assert literal_value(masked.strip(), registry) is None

    def test_none_for_non_placeholder(self):
        _, registry = mask_literals("'x'")
        assert literal_value("[Column]", registry) is None

    def test_unescapes_doubled_quote(self):
        masked, registry = mask_literals("'it''s'")
        assert literal_value(masked.strip(), registry) == "it's"
