"""New audit rules, set 1 (audit v2 roadmap PR 4.3): A7, A8, H11, H12, D14, D15, D16."""
from __future__ import annotations

from audit_rule_fixtures.ai import build_tml_col, build_tml_ctx
from audit_run_rule import run_rule


def _sev(ctx, rid):
    return sorted(f.severity for f in run_rule(ctx, rid))


def _measures(blank, total):
    return [build_tml_col(f"M{i}", "MEASURE", desc=None if i < blank else "described")
            for i in range(total)]


# ── A7: visible measures without a description ──────────────────────────────

def test_a7_bands():
    assert _sev(build_tml_ctx(*_measures(1, 4)), "A7") == ["LOW"]
    assert _sev(build_tml_ctx(*_measures(4, 4)), "A7") == ["MEDIUM"]
    assert _sev(build_tml_ctx(*_measures(3, 4)), "A7") == ["LOW"]        # 75%: not above
    assert _sev(build_tml_ctx(*_measures(0, 4)), "A7") == []
    hidden = [build_tml_col("H", "MEASURE", hidden=True)]
    assert _sev(build_tml_ctx(*hidden, build_tml_col("A", desc="d")), "A7") == []  # none visible


# ── H11: many hidden ordinary columns ───────────────────────────────────────

def _h11_ctx(hidden, visible, referenced=0):
    cols = [build_tml_col(f"H{i}", hidden=True) for i in range(hidden)]
    cols += [build_tml_col(f"V{i}") for i in range(visible)]
    ctx = build_tml_ctx(*cols)
    model = ctx.models[0]["model"]
    model["formulas"] = [{"id": f"f{i}", "name": f"F{i}", "expr": f"[H{i}] * 2"}
                         for i in range(referenced)]
    return ctx


def test_h11_bands_and_what_h3_excuses():
    assert _sev(_h11_ctx(3, 1), "H11") == ["MEDIUM"]       # 75% hidden
    assert _sev(_h11_ctx(1, 2), "H11") == ["LOW"]          # 33%
    assert _sev(_h11_ctx(1, 3), "H11") == []               # 25%: not above
    assert _sev(_h11_ctx(3, 1, referenced=3), "H11") == [] # all three feed formulas
    assert _sev(_h11_ctx(0, 0), "H11") == []
