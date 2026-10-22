"""Named fixture builders for audit catalog rules, one module per category.

Each public function not named `build_*` takes no arguments and returns an
`AuditContext` (`build_*` helpers take arguments and build families of inputs). A rule's
`examples.fires.fixture` / `examples.silent.fixture` names one of them, and the engine
tests (`test_audit_engine.py`) build their inputs from them too. Everything here is
synthetic: invented names and guids, never exported TML from a real cluster.

Add a builder per shape a rule needs rather than parameterising an existing one — the
catalog refers to fixtures by name, so a name must keep meaning one input.

Layout — every public name is re-exported here, so `import audit_rule_fixtures as fx`
and a rule's `fixture:` name resolve without knowing the module:

    common.py    generic engine inputs (one per mode / engine behaviour), and the
                 all-category contexts test_checks_registry.py runs every check over
    ai.py        A — the legacy A-check tests' inputs, and AI_INPUTS
    rls.py       shapes P and S share: the Table/RLS shapes of S8/S9 and their P15/P14
                 clones, and the index-type shapes of P9/P11 and S2
    perf.py      P — the legacy P-check tests' inputs, and P_INPUTS
    security.py  S — the legacy S-check tests' inputs, and S_INPUTS
    data.py      D — the legacy D-check tests' inputs, and D_INPUTS
    human.py     H — the legacy H-check tests' inputs (contexts `build_context`
                 assembles with Set lookups patched among them), and H_INPUTS

Each category module keeps its builders beside its explicit input list (the
equivalence test's inputs, `<CAT>_INPUTS`). Builders deep-copy any shared constant they
place in a context, so no test can mutate another's input through it. A module imports
only from modules above it in the list, never back.
"""
from __future__ import annotations

from .common import *  # noqa: F401,F403
from .ai import *  # noqa: F401,F403
from .rls import *  # noqa: F401,F403
from .perf import *  # noqa: F401,F403
from .security import *  # noqa: F401,F403
from .data import *  # noqa: F401,F403
from .human import *  # noqa: F401,F403
