"""Shapes the P and S rules share — imported by both perf.py and security.py, so
neither category module imports the other:

- the Table and RLS shapes S8/S9 and their P clones P15/P14 run over
  (test_checks_security_trip.py and test_checks_perf_trip.py);
- the index-type shapes P9/P11 and S2 run over (test_index_type_sense.py)."""
from __future__ import annotations

import copy

from ts_cli.audit.context import AuditContext, make_context


# test_checks_security_trip.py's shapes (S2/S3/S8/S9; P14 and P15 on the clones)

SEC_TABLE_FQN = "AGENT_SKILLS.PUBLIC.CUSTOMERS"
# A table column carries its warehouse type; a model column does not.
SEC_TABLE_COLS = [
    {"name": "COUNTRY", "db_column_name": "COUNTRY",
     "properties": {"column_type": "ATTRIBUTE"},
     "db_column_properties": {"data_type": "VARCHAR"}},
    {"name": "REGION_ID", "db_column_name": "REGION_ID",
     "properties": {"column_type": "ATTRIBUTE"},
     "db_column_properties": {"data_type": "INT64"}},
]


def build_sec_rls(expr, path_column="COUNTRY") -> dict:
    """`rls_rules` in the nested mapping form the table schema documents."""
    return {
        "tables": [{"name": "CUSTOMERS"}],
        "table_paths": [{"id": "T_1", "table": "CUSTOMERS", "column": [path_column]}],
        "rules": [{"name": "tenant filter", "expr": expr}],
    }


def build_sec_table(rls_rules=None, columns=None, name="CUSTOMERS", guid="t-1") -> dict:
    t = {
        "name": name, "db": "AGENT_SKILLS", "schema": "PUBLIC",
        "db_table": "CUSTOMERS", "connection": {"name": "se-snowflake"},
        "columns": copy.deepcopy(SEC_TABLE_COLS if columns is None else columns),
    }
    if rls_rules:
        t["rls_rules"] = copy.deepcopy(rls_rules)
    return {"guid": guid, "table": t}


def sec_rls_cased_varchar() -> AuditContext:
    """An RLS column that is VARCHAR with value_casing: S8 fires, P15 does not."""
    cased = [{"name": "COUNTRY", "db_column_name": "COUNTRY",
              "properties": {"column_type": "ATTRIBUTE", "value_casing": "UPPER"},
              "db_column_properties": {"data_type": "VARCHAR"}}]
    return make_context(tables={SEC_TABLE_FQN: build_sec_table(
        build_sec_rls("ts_groups = [T_1::COUNTRY]"), columns=cased)})


def sec_rls_uncased_varchar() -> AuditContext:
    return make_context(tables={SEC_TABLE_FQN: build_sec_table(
        build_sec_rls("ts_groups = [T_1::COUNTRY]"))})


def sec_rls_upper_function() -> AuditContext:
    return make_context(tables={SEC_TABLE_FQN: build_sec_table(
        build_sec_rls("UPPER([T_1::COUNTRY]) = ts_groups"))})


# test_checks_perf_trip.py's Table shapes (P14/P15, and S8/S9 on the same inputs)

def build_trip_model(**model_body) -> dict:
    """A model TML document: `guid` at the root, everything else under `model:`.
    The body is deep-copied, so shared constants are never mutated through it (one
    deepcopy: an object listed twice stays one object)."""
    body = {"name": "Sales"}
    body.update(copy.deepcopy(model_body))
    return {"guid": "m-1", "model": body}


TRIP_TABLE_FQN = "DUNDERMIFFLIN.PUBLIC.BANK_EMPLOYEES"


def build_trip_table(columns, rules=None) -> dict:
    columns, rules = copy.deepcopy((columns, rules))
    t = {"name": "BANK_EMPLOYEES", "db": "DUNDERMIFFLIN", "schema": "PUBLIC",
         "db_table": "BANK_EMPLOYEES", "columns": columns}
    if rules is not None:
        t["rls_rules"] = {
            "tables": [{"name": "BANK_EMPLOYEES"}],
            "table_paths": [{"id": "BANK_EMPLOYEES_1", "table": "BANK_EMPLOYEES",
                             "column": ["COUNTRY"]}],
            "rules": rules,
        }
    return {"guid": "t-1", "table": t}


def build_trip_table_ctx(columns, rules) -> AuditContext:
    return make_context(tables={TRIP_TABLE_FQN: build_trip_table(columns, rules)})


def build_trip_varchar(name, **props) -> dict:
    return {"name": name, "db_column_name": name,
            "properties": {"column_type": "ATTRIBUTE", **props},
            "db_column_properties": {"data_type": "VARCHAR"}}


# P14 / P15 — RLS expressions and columns

TRIP_PLAIN_RULE = {"name": "Country rule", "expr": "ts_groups = [BANK_EMPLOYEES_1::COUNTRY]"}
TRIP_FUNC_RULE = {"name": "Country rule",
                  "expr": "upper ( [BANK_EMPLOYEES_1::COUNTRY] ) = ts_groups"}
P14_FUNCTION_EXPRS = [
    "trim ( [BANK_EMPLOYEES_1::COUNTRY] ) = ts_groups",
    "cast ( [BANK_EMPLOYEES_1::COUNTRY] as varchar ) = ts_groups",
    "concat ( [BANK_EMPLOYEES_1::COUNTRY] , 'x' ) = ts_groups",
    "if ( ts_groups = 'admin' , true , [BANK_EMPLOYEES_1::COUNTRY] = ts_groups )",
]


def build_rls_expr(expr) -> AuditContext:
    return build_trip_table_ctx([build_trip_varchar("COUNTRY")], [{"name": "R", "expr": expr}])


def perf_rls_function_rule() -> AuditContext:
    """upper(...) around the RLS column (P14 fires); COUNTRY is uncased VARCHAR (P15)."""
    return build_trip_table_ctx([build_trip_varchar("COUNTRY")], [TRIP_FUNC_RULE])


def perf_rls_plain_rule() -> AuditContext:
    """A bare comparison on an uncased VARCHAR column: P15 fires, P14 does not."""
    return build_trip_table_ctx([build_trip_varchar("COUNTRY")], [TRIP_PLAIN_RULE])


def perf_table_without_rls() -> AuditContext:
    return make_context(tables={TRIP_TABLE_FQN: build_trip_table([build_trip_varchar("COUNTRY")])})


def perf_rls_cased_varchar() -> AuditContext:
    return build_trip_table_ctx([build_trip_varchar("COUNTRY", value_casing="UPPER")],
                                [TRIP_PLAIN_RULE])


def perf_rls_integer_column() -> AuditContext:
    int_col = {"name": "COUNTRY_ID", "db_column_name": "COUNTRY_ID",
               "properties": {"column_type": "ATTRIBUTE"},
               "db_column_properties": {"data_type": "INT64"}}
    rule = {"name": "R", "expr": "ts_groups_int = [BANK_EMPLOYEES_1::COUNTRY_ID]"}
    return build_trip_table_ctx([int_col], [rule])


def perf_rls_type_on_model_ignored() -> AuditContext:
    """A model column claims INT64; the TABLE's VARCHAR is what counts."""
    lying_model = build_trip_model(columns=[
        {"name": "COUNTRY", "column_id": "BANK_EMPLOYEES::COUNTRY",
         "properties": {"column_type": "ATTRIBUTE"},
         "db_column_properties": {"data_type": "INT64"}}])
    return make_context(models=[lying_model], tables={
        TRIP_TABLE_FQN: build_trip_table([build_trip_varchar("COUNTRY")], [TRIP_PLAIN_RULE])})


#: Data types where `.upper()` and a case-insensitive match disagree: two ligatures
#: whose upper case is "ST" (legacy reads STRING), and a dotted capital I (not STRING).
P15_UNICODE_TYPES = ["\ufb06RING", "\ufb05RING", "STR\u0130NG"]


def build_rls_column_type(data_type) -> AuditContext:
    """An RLS rule on COUNTRY, an uncased column of `data_type`."""
    col = {"name": "COUNTRY", "db_column_name": "COUNTRY",
           "properties": {"column_type": "ATTRIBUTE"},
           "db_column_properties": {"data_type": data_type}}
    return build_trip_table_ctx([col], [TRIP_PLAIN_RULE])


def perf_rls_friendly_column_name() -> AuditContext:
    """Display name "Country" vs physical COUNTRY: the lookup misses (no P15)."""
    friendly = {"name": "Country", "db_column_name": "COUNTRY",
                "properties": {"column_type": "ATTRIBUTE"},
                "db_column_properties": {"data_type": "VARCHAR"}}
    return build_trip_table_ctx([friendly], [TRIP_PLAIN_RULE])


# test_index_type_sense.py's shapes (P9, P11, S2)

def build_index_col(name, ctype, index_type, column_id=None) -> dict:
    props = {"column_type": ctype}
    if index_type is not None:
        props["index_type"] = index_type
    return {"name": name, "column_id": column_id or f"T::{name}", "properties": props}


def build_index_model(cols, **model) -> dict:
    base = {"name": "M", "columns": cols}
    base.update(model)
    return {"guid": "m-1", "model": base}
