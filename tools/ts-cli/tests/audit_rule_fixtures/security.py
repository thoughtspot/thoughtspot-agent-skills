"""S (Security): the inputs the legacy S-check tests use, and S_INPUTS."""
from __future__ import annotations

import copy

from ts_cli.audit.context import AuditContext, make_context

from .ai import demo_corpus_models
from .common import registry_empty_context, registry_populated_context
from .rls import (P14_FUNCTION_EXPRS, P15_UNICODE_TYPES, SEC_TABLE_FQN, TRIP_FUNC_RULE,
                  TRIP_TABLE_FQN, build_index_col, build_index_model, build_rls_column_type,
                  build_rls_expr, build_sec_rls, build_sec_table, build_trip_table,
                  build_trip_varchar, perf_rls_friendly_column_name, perf_rls_function_rule,
                  perf_rls_integer_column, perf_rls_plain_rule, perf_rls_type_on_model_ignored,
                  perf_table_without_rls, sec_rls_cased_varchar, sec_rls_uncased_varchar,
                  sec_rls_upper_function)


# ── S: Security ─────────────────────────────────────────────────────────────
# The inputs the legacy S-check tests exercised checks_security.py (deleted when the rule catalog replaced them) with:
# test_checks_security.py, test_checks_security_trip.py, and the S halves of
# test_alias_and_join_names.py, test_index_type_sense.py and test_checks_registry.py.
# Those tests build their contexts here, so the S rules' examples and the pinned-findings
# test (tests/test_audit_pinned_findings.py) run over the very same inputs.

# test_checks_security.py's shapes

def build_sec_model(name="Sales", guid="m-1", columns=None, formulas=None,
                    properties=None) -> dict:
    """A model document as test_checks_security.py has always built it."""
    columns, formulas, properties = copy.deepcopy((columns, formulas, properties))
    return {"guid": guid, "model": {
        "name": name, "model_tables": [{"name": "T1"}], "columns": columns or [],
        "formulas": formulas or [], "properties": properties or {}}}


def build_sec_col(name="Amount", column_id=None, index_type=None) -> dict:
    col = {"name": name, "column_id": column_id or f"T1::{name}", "properties": {},
           "db_column_properties": {"data_type": "VARCHAR"}}
    if index_type:
        col["properties"]["index_type"] = index_type
    return col


def sec_model_email_column() -> AuditContext:
    """customer_email reads as PII (email); Amount does not."""
    return make_context(models=[build_sec_model(
        columns=[build_sec_col("customer_email"), build_sec_col("Amount")])])


def sec_model_without_pii() -> AuditContext:
    return make_context(models=[build_sec_model(
        columns=[build_sec_col("Amount"), build_sec_col("Revenue")])])


def sec_password_column() -> AuditContext:
    return make_context(models=[build_sec_model(
        columns=[build_sec_col("password"), build_sec_col("Amount")])])


def sec_bypass_with_pii() -> AuditContext:
    return make_context(models=[build_sec_model(
        columns=[build_sec_col("customer_email")], properties={"is_bypass_rls": True})])


def sec_bypass_without_pii() -> AuditContext:
    """RLS bypassed on a model with no columns: S10 fires, S4 does not."""
    return make_context(models=[build_sec_model(properties={"is_bypass_rls": True})])


def sec_model_without_bypass() -> AuditContext:
    return make_context(models=[build_sec_model(properties={})])


# test_checks_security_trip.py's shapes (the Table/RLS builders are in rls.py)

def build_sec_mcol(name, column_id=None, index_type=None) -> dict:
    """A model column on CUSTOMERS (model columns carry no data type)."""
    props = {"column_type": "ATTRIBUTE"}
    if index_type:
        props["index_type"] = index_type
    return {"name": name, "column_id": column_id or f"CUSTOMERS::{name}",
            "properties": props}


def build_sec_trip_model(columns, formulas=None, alias=None) -> dict:
    """Customer 360 over the CUSTOMERS table (aliased when `alias` is given)."""
    mt = {"name": "CUSTOMERS", "fqn": SEC_TABLE_FQN}
    if alias:
        mt["alias"] = alias
    columns, formulas = copy.deepcopy((columns, formulas))
    return {"guid": "m-1", "model": {
        "name": "Customer 360", "model_tables": [mt],
        "columns": columns, "formulas": formulas or [],
    }}


def build_sec_trip_ctx(columns, formulas=None, rls_rules=None) -> AuditContext:
    """The model over CUSTOMERS, with the CUSTOMERS Table TML (RLS when given)."""
    return make_context(models=[build_sec_trip_model(columns, formulas)],
                        tables={SEC_TABLE_FQN: build_sec_table(rls_rules)})


def sec_pii_indexed_without_rls() -> AuditContext:
    """An indexed PII column whose table has no RLS: S2 HIGH."""
    return build_sec_trip_ctx([build_sec_mcol("customer_email",
                                              index_type="PREFIX_AND_SUBSTRING")])


def sec_pii_indexed_with_rls() -> AuditContext:
    """The same column, its table under RLS: S2 INFO."""
    return build_sec_trip_ctx(
        [build_sec_mcol("customer_email", index_type="PREFIX_AND_SUBSTRING")],
        rls_rules=build_sec_rls("ts_groups = [T_1::COUNTRY]"))


def sec_indexed_without_pii() -> AuditContext:
    return build_sec_trip_ctx([build_sec_mcol("Revenue", index_type="DEFAULT"),
                               build_sec_mcol("Order Count", index_type="DEFAULT")])


def sec_pii_default_indexed() -> AuditContext:
    """No `index_type`: indexed by default, the risk S2 reports (BL-299)."""
    return build_sec_trip_ctx([build_sec_mcol("customer_email")])


def sec_pii_not_indexed() -> AuditContext:
    """`DONT_INDEX` is the mitigation: S2 silent (S1 and S3 still fire)."""
    return build_sec_trip_ctx([build_sec_mcol("customer_email", index_type="DONT_INDEX")])


def sec_pii_unmasked() -> AuditContext:
    return build_sec_trip_ctx([build_sec_mcol("customer_email"), build_sec_mcol("Revenue")])


def sec_non_pii_columns() -> AuditContext:
    return build_sec_trip_ctx([build_sec_mcol("Revenue"), build_sec_mcol("Order Count")])


SEC_MASKING_FORMULA = {"id": "f1", "name": "Masked Email",
                       "expr": "if (is_group_member('PII_VIEWERS')) then [customer_email] "
                               "else 'REDACTED'"}


def sec_pii_masked() -> AuditContext:
    """A masking formula naming the column: S3 silent."""
    return build_sec_trip_ctx([build_sec_mcol("customer_email")],
                              formulas=[SEC_MASKING_FORMULA])


def sec_mask_elsewhere_raw_projection() -> AuditContext:
    """The masking guards Salary; the email is projected raw — legacy S3 is still
    silent (the formulas are searched as one blob, a known defect)."""
    return build_sec_trip_ctx([build_sec_mcol("customer_email")], formulas=[
        {"id": "f1", "name": "Masked Salary",
         "expr": "if (is_group_member('HR')) then [Salary] else 0"},
        {"id": "f2", "name": "Contact", "expr": "[customer_email]"}])


def sec_rls_varchar_beside_a_model() -> AuditContext:
    """A model column with no type beside the Table's VARCHAR RLS column: S8 reads the
    Table, not the model."""
    return make_context(models=[build_sec_trip_model([build_sec_mcol("Country")])],
                        tables={SEC_TABLE_FQN: build_sec_table(
                            build_sec_rls("ts_groups = [T_1::COUNTRY]"))})


def sec_rls_integer_column() -> AuditContext:
    return make_context(tables={SEC_TABLE_FQN: build_sec_table(
        build_sec_rls("ts_groups_int = [T_1::REGION_ID]", path_column="REGION_ID"))})


def sec_table_without_rls() -> AuditContext:
    return make_context(tables={SEC_TABLE_FQN: build_sec_table()})


def sec_rls_unresolved_ref() -> AuditContext:
    """A ref to a column the Table TML does not hold: unknown type, not reported."""
    return make_context(tables={SEC_TABLE_FQN: build_sec_table(
        build_sec_rls("ts_groups = [T_2::TENANT_NAME]"))})


#: test_checks_security_trip.py's S9 expressions (one function call each).
S9_TRIP_EXPRS = [
    "UPPER([T_1::COUNTRY]) = ts_groups",
    "trim([T_1::COUNTRY]) = ts_groups",
    "if ([T_1::COUNTRY] = 'AU') then true else false",
    "contains([T_1::COUNTRY], ts_groups)",
]


def build_sec_rls_expr(expr) -> AuditContext:
    return make_context(tables={SEC_TABLE_FQN: build_sec_table(build_sec_rls(expr))})


# test_alias_and_join_names.py's S2 shapes (BL-305)

def build_alias_rls_ctx(with_rls: bool) -> AuditContext:
    """customer_email on CUSTOMERS joined under the alias SHIP_TO."""
    table = {"guid": "t-1", "table": {"name": "CUSTOMERS", "columns": []}}
    if with_rls:
        table["table"]["rls_rules"] = {"rules": [{"expr": "x = ts_groups"}]}
    model = {"guid": "m-1", "model": {"name": "S", "columns": [
        {"name": "customer_email", "column_id": "SHIP_TO::customer_email"}],
        "model_tables": [{"name": "CUSTOMERS", "alias": "SHIP_TO", "fqn": "t-1"}]}}
    return make_context(models=[model], tables={"t-1": table})


def sec_alias_table_with_rls() -> AuditContext:
    return build_alias_rls_ctx(True)


def sec_alias_table_without_rls() -> AuditContext:
    return build_alias_rls_ctx(False)


# test_index_type_sense.py's S2 shapes (BL-299)

#: Every documented `index_type`, and the key absent (None).
INDEX_TYPES = [None, "DEFAULT", "PREFIX_ONLY", "PREFIX_AND_SUBSTRING",
               "PREFIX_AND_WORD_SUBSTRING", "DONT_INDEX"]


def build_index_pii_ctx(index_type) -> AuditContext:
    return make_context(models=[build_index_model(
        [build_index_col("customer_email", "ATTRIBUTE", index_type)])])


# Name heuristics swept: each PII category, word-boundary and first-match edges, and
# the credential words in every spelling the pattern allows (or refuses).

#: Column names around the PII patterns — matches, near misses, and first-match order.
PII_NAMES = [
    "customer_email", "E-Mail", "emailaddr", "Phone", "mobile", "cell_phone", "Fax",
    "telephone", "Hotel", "SSN", "social-sec", "national_id", "tax-id", "nin", "NIN Code",
    "Basin", "Cousin", "sin", "Single", "DOB", "Doberman", "birth_date", "date-of-birth",
    "Birthday", "credit_card", "cardnum", "account-num", "IBAN", "routing_num",
    "first_name", "LastName", "Surname", "full-name", "given_name", "street_addr",
    "Postal Code", "postal_code", "zip_code", "Zip Code", "email_phone", "phone_email",
    "Amount", "", "Eſmail",
]

#: Column names around the credential pattern: whole words only, any case.
CREDENTIAL_NAMES = [
    "password", "Password", "PASSWD", "passwords", "my_password", "user password",
    "secret_key", "Secret-Key", "secretkey", "SECRET KEY", "api_key", "API-KEY", "apikey",
    "api key", "token", "TOKEN", "Access Token", "tokens", "token_id",
    # U+212A KELVIN SIGN in place of the K: it lower-cases to "k", so the (?i) pattern
    # matches it as a whole-word "token".
    "TO\u212aEN",
    "password token",
]


def build_named_columns(names, index_type=None) -> AuditContext:
    """One model column per name, on CUSTOMERS (indexed unless `index_type` says)."""
    return build_sec_trip_ctx([build_sec_mcol(n, column_id=f"CUSTOMERS::C{i}",
                                              index_type=index_type)
                               for i, n in enumerate(names)])


def build_bypass_ctx(value) -> AuditContext:
    """A model with one PII column whose `is_bypass_rls` is `value`."""
    return make_context(models=[build_sec_model(
        columns=[build_sec_col("customer_email")], properties={"is_bypass_rls": value})])


#: is_bypass_rls values: legacy reads truthiness, not `is True`.
BYPASS_VALUES = [True, False, None, 1, 0, "yes", "", "false", [1], []]


# Owning-table RLS lookup (S2) and masking (S3) edges

def sec_owning_table_edges() -> AuditContext:
    """S2's table lookup, edge by edge: a column with no `column_id` (key "") and a
    model table with no name or alias whose Table has RLS (key "" -> True); a
    `column_id` without `::`; a later model table with the same alias overriding an
    earlier one's RLS; one whose Table TML is absent writing nothing; a model table
    with no fqn; a falsy Table document; a Table document with no `table` key."""
    rls = {"rules": [{"expr": "x = ts_groups"}]}
    tables = {
        "t-rls": {"guid": "t-rls", "table": {"name": "A", "rls_rules": rls}},
        "t-plain": {"guid": "t-plain", "table": {"name": "B"}},
        "t-empty": {},
        "t-headless": {"guid": "t-headless"},
    }
    model_tables = [
        {"fqn": "t-rls"},                                  # key "" -> True
        {"name": "DUP", "alias": "X", "fqn": "t-rls"},     # X -> True ...
        {"name": "DUP2", "alias": "X", "fqn": "t-plain"},  # ... then X -> False
        {"name": "Y", "fqn": "t-rls"},                     # Y -> True
        {"name": "Y", "fqn": "t-missing"},                 # absent: Y stays True
        {"name": "NOFQN"},
        {"name": "E", "fqn": "t-empty"},
        {"name": "H", "fqn": "t-headless"},
    ]
    cols = [{"name": "email_no_id"},
            {"name": "phone_no_sep", "column_id": "X"},
            {"name": "email_x", "column_id": "X::E"},
            {"name": "email_y", "column_id": "Y::E"},
            {"name": "email_nofqn", "column_id": "NOFQN::E"},
            {"name": "email_e", "column_id": "E::E"},
            {"name": "email_h", "column_id": "H::E"},
            {"name": "email_unknown", "column_id": "Q::E"}]
    return make_context(models=[{"guid": "m-1", "model": {
        "name": "Edges", "columns": cols, "model_tables": model_tables}}], tables=tables)


def sec_masking_edges() -> AuditContext:
    """S3's blob search: IS_GROUP_MEMBER in upper case, a column named in another
    case, a formula with no `expr`, and a PII column the blob never names."""
    return make_context(models=[{"guid": "m-1", "model": {
        "name": "Masks",
        "columns": [{"name": "Customer_Email"}, {"name": "home_phone"},
                    {"name": "ssn"}],
        "formulas": [{"name": "no expr"},
                     {"name": "m", "expr": "IF (IS_GROUP_MEMBER('x')) THEN [customer_email]"},
                     {"name": "n", "expr": "[SSN] + 0"}]}}])


def sec_masking_without_group_member() -> AuditContext:
    """A formula naming the PII column with no is_group_member anywhere: not masked."""
    return make_context(models=[{"guid": "m-1", "model": {
        "name": "NoMask", "columns": [{"name": "customer_email"}],
        "formulas": [{"name": "f", "expr": "[customer_email]"}]}}])


# Raw names and guids, and None where a list is expected

def sec_names_none() -> AuditContext:
    """Every S scope with `name: None` / `guid: None`, each firing."""
    model = build_sec_model(name=None, guid=None, columns=[
        build_sec_col("customer_email"), build_sec_col("api_key")],
        properties={"is_bypass_rls": True})
    table = build_trip_table([build_trip_varchar("COUNTRY")], [TRIP_FUNC_RULE])
    table["guid"] = None
    table["table"]["name"] = None
    return make_context(models=[model], tables={TRIP_TABLE_FQN: table})


def sec_names_absent() -> AuditContext:
    """Every S scope with no `name` / `guid` key, each firing; one column unnamed."""
    model = build_sec_model(columns=[build_sec_col("customer_email"), build_sec_col("token"),
                                     {"column_id": "T1::X", "properties": {}}],
                            properties={"is_bypass_rls": True})
    del model["guid"], model["model"]["name"]
    table = build_trip_table([build_trip_varchar("COUNTRY")], [TRIP_FUNC_RULE])
    del table["guid"], table["table"]["name"]
    return make_context(models=[model], tables={TRIP_TABLE_FQN: table})


def sec_lists_none() -> AuditContext:
    """None (or another falsy value) wherever a list or mapping is expected."""
    return make_context(
        models=[{"guid": "m-1", "model": {"name": "Nones", "columns": None, "formulas": None,
                                          "model_tables": None, "properties": None}},
                {"guid": "m-2", "model": {"name": "Falsy", "columns": [], "formulas": 0,
                                          "model_tables": "", "properties": {}}},
                {"guid": "m-3", "model": {"name": "PII, no lists",
                                          "columns": [{"name": "email"}],
                                          "formulas": None, "model_tables": None,
                                          "properties": None}},
                {"guid": "m-4"}],
        tables={"t-1": {"guid": "t-1", "table": {"name": "T1", "columns": None,
                                                 "rls_rules": None}},
                "t-2": {"guid": "t-2", "table": {"name": "T2", "columns": None,
                                                 "rls_rules": {"rules": None}}},
                "t-3": {"guid": "t-3", "table": {"name": "T3", "rls_rules": {
                    "rules": [{"name": "no expr"}, {"expr": "UPPER([T3::C]) = 'x'"}]}}},
                "t-4": {"guid": "t-4"}})


def sec_long_rls_expression() -> AuditContext:
    """An RLS expression longer than 80 characters: the detail quotes the first 80."""
    expr = ("upper ( [BANK_EMPLOYEES_1::COUNTRY] ) = ts_groups or lower ( "
            "[BANK_EMPLOYEES_1::REGION] ) = ts_groups or trim ( [BANK_EMPLOYEES_1::CITY] )")
    return build_rls_expr(expr)


def sec_rls_many_refs() -> AuditContext:
    """Two rules, three refs (one without `::`, one repeated): S8 per reference."""
    cols = [build_trip_varchar("COUNTRY"), build_trip_varchar("CITY"),
            {"name": "ID", "db_column_properties": {"data_type": "INT64"}}]
    rules = [{"name": "a", "expr": "[BANK_EMPLOYEES_1::COUNTRY] = ts_groups and [CITY] = 'x'"},
             {"name": "b", "expr": "[COUNTRY] = ts_groups or [ID] = 1"}]
    return make_context(tables={TRIP_TABLE_FQN: build_trip_table(cols, rules)})


#: S9 expressions around the function regex: case, spacing, and word boundaries.
S9_EDGE_EXPRS = ["UPPER ([C]) = x", "lower(  [C]) = x", "endif ([C])", "Cast([C] as int)",
                 "concat_ws([C])", "CONTAINS ([C], 'x')", "uppercase([C])", "[C] = 'IF('"]


# Every S input, for the pinned-findings test — listed by hand (see AI_INPUTS).
S_INPUTS = {fn.__name__: fn for fn in (
    sec_model_email_column, sec_model_without_pii, sec_password_column,
    sec_bypass_with_pii, sec_bypass_without_pii, sec_model_without_bypass,
    sec_pii_indexed_without_rls, sec_pii_indexed_with_rls, sec_indexed_without_pii,
    sec_pii_default_indexed, sec_pii_not_indexed, sec_pii_unmasked, sec_non_pii_columns,
    sec_pii_masked, sec_mask_elsewhere_raw_projection,
    sec_rls_varchar_beside_a_model, sec_rls_integer_column, sec_table_without_rls,
    sec_rls_unresolved_ref, sec_rls_cased_varchar, sec_rls_uncased_varchar,
    sec_rls_upper_function,
    sec_alias_table_with_rls, sec_alias_table_without_rls,
    registry_empty_context, registry_populated_context,
    sec_owning_table_edges, sec_masking_edges, sec_masking_without_group_member,
    sec_names_none, sec_names_absent, sec_lists_none, sec_long_rls_expression,
    sec_rls_many_refs,
    perf_rls_function_rule, perf_rls_plain_rule, perf_table_without_rls,
    perf_rls_integer_column, perf_rls_type_on_model_ignored, perf_rls_friendly_column_name,
    demo_corpus_models,
)}
S_INPUTS.update({f"s9_trip_{i}": (lambda e=e: build_sec_rls_expr(e))
                 for i, e in enumerate(S9_TRIP_EXPRS)})
S_INPUTS.update({f"s9_function_{i}": (lambda e=e: build_rls_expr(e))
                 for i, e in enumerate(P14_FUNCTION_EXPRS + S9_EDGE_EXPRS)})
S_INPUTS.update({f"s8_column_type_{i}": (lambda t=t: build_rls_column_type(t))
                 for i, t in enumerate(P15_UNICODE_TYPES + ["varchar", "Text", "INT64", ""])})
S_INPUTS.update({f"index_pii_{t or 'omitted'}": (lambda t=t: build_index_pii_ctx(t))
                 for t in INDEX_TYPES})
S_INPUTS.update({f"bypass_{i}": (lambda v=v: build_bypass_ctx(v))
                 for i, v in enumerate(BYPASS_VALUES)})
S_INPUTS.update({
    "pii_names_indexed": lambda: build_named_columns(PII_NAMES),
    "pii_names_not_indexed": lambda: build_named_columns(PII_NAMES, "DONT_INDEX"),
    "credential_names": lambda: build_named_columns(CREDENTIAL_NAMES),
})


# S11 — an RLS rule's join closes a cycle with the Model's joins. Synthetic shapes; not
# in S_INPUTS (S11 is new, so it has no legacy findings to pin).

def build_rls_cycle_table(name, joins, paths, exprs) -> dict:
    """A Table body with `rls_rules`: `joins` (name, source, destination); `paths`
    (id, table, join name or None); `exprs` the rule expressions."""
    return {"name": name, "joins_with": [{"name": n, "destination": {"name": d}}
                                         for n, _s, d in joins],
            "rls_rules": {
                "tables": [{"name": name}],
                "joins": [{"name": n, "source": s, "destination": d, "type": "INNER"}
                          for n, s, d in joins],
                "table_paths": [{"id": pid, "table": tbl, "column": ["c"],
                                 **({"join_path": [{"join": [j]}]} if j else {})}
                                for pid, tbl, j in paths],
                "rules": [{"name": f"r{i}", "expr": e} for i, e in enumerate(exprs)]}}


def build_rls_cycle_ctx(users_rls: dict, users_fqn="g-users") -> AuditContext:
    """Activity over fact, bridge and users (fact -> bridge -> users, MANY_TO_ONE); the
    users Table TML (with `users_rls`) filed under `users_fqn`."""
    def mt(name, *targets):
        return {"name": name, "fqn": f"g-{name}",
                "joins": [{"with": t, "name": f"{name}_{t}", "cardinality": "MANY_TO_ONE",
                           "type": "LEFT_OUTER", "on": f"[{name}::k] = [{t}::k]"}
                          for t in targets]}
    model = {"guid": "m-rls", "model": {
        "name": "Activity", "columns": [],
        "model_tables": [mt("fact", "bridge"), mt("bridge", "users"), mt("users")]}}
    # The audit keeps each Table TML as the whole parsed document, keyed by its guid.
    return make_context(models=[model], tables={users_fqn: {
        "guid": users_fqn, "table": copy.deepcopy(users_rls)}})


def sec_rls_join_cycle() -> AuditContext:
    """The rule on users joins out to bridge, which the Model joins back to users: S11."""
    return build_rls_cycle_ctx(build_rls_cycle_table(
        "users", [("users_to_bridge", "users", "bridge")],
        [("bridge_1", "bridge", "users_to_bridge"), ("users_1", "users", None)],
        ["[users_1::c] in ts_var(a) and [bridge_1::c] in ts_var(b)"]))


def sec_rls_same_direction() -> AuditContext:
    """The rule on bridge walks bridge -> users, the same way the Model joins them: a
    path, not a loop — no S11."""
    return build_rls_cycle_ctx(build_rls_cycle_table(
        "bridge", [("bridge_to_users", "bridge", "users")],
        [("users_1", "users", "bridge_to_users")], ["[users_1::c] = 1"]),
        users_fqn="g-bridge")
