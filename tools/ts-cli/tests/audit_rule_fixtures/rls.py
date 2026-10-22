"""Table and RLS shapes from tests/test_checks_security_trip.py, shared by the S rules
(S8, S9) and their P clones (P15, P14) — imported by both perf.py and security.py."""
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

