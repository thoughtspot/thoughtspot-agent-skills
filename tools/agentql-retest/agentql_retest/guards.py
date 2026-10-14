"""The `guards` suite: what AgentQL must ALWAYS refuse. Unlike a limitation, none of these
should ever start working. A guard that compiles to anything other than one read-only
SELECT is a BREACH, which outranks every other verdict.

Two kinds:
- GEN_ERROR guards: writes, DDL, admin commands, a second statement, reaching past the Model
  (physical tables, information_schema). Any rejection passes; only a SUCCESS is a breach.
- SQL_OK guards: inputs that compile but must be neutralised. Comments, `SELECT … INTO` and
  a `'; DROP` inside a string literal all compile to ONE regenerated SELECT, with nothing
  from the original text passed through. `classify.read_only_problem` checks that.

Guards only ever call `generate-sql`, which compiles and does not touch the warehouse. They
are never fetched, so even a breach sends nothing to the warehouse. They run on
"(Sample) Retail - Apparel" so any cluster can run them.
"""
from __future__ import annotations

from .classify import GEN_ERROR, SQL_OK, Case
from .lessons import SAMPLE_MODEL

T = f'"{SAMPLE_MODEL}"'
S = f'SELECT SUM("t1"."sales") AS s FROM {T} AS "t1"'
G = "🛡 "


def _g(cid, sql, row, expect=GEN_ERROR, **kw):
    return Case(cid, sql, expect, G + row, model="apparel", guard=True, **kw)


GUARD_CASES = [
    # ---- writes ----------------------------------------------------------------------------------
    _g("g_delete_all", f"DELETE FROM {T}", "Writes are rejected: DELETE"),
    _g("g_delete_where", f"DELETE FROM {T} AS \"t1\" WHERE \"t1\".\"region\" = 'West'", "Writes are rejected: DELETE"),
    _g("g_update", f'UPDATE {T} SET "sales" = 0', "Writes are rejected: UPDATE"),
    _g("g_insert_values", f"INSERT INTO {T} (\"region\") VALUES ('X')", "Writes are rejected: INSERT"),
    _g("g_insert_select", f"INSERT INTO {T} SELECT * FROM {T}", "Writes are rejected: INSERT"),
    _g("g_merge", f'MERGE INTO {T} AS t USING {T} AS s ON t."region" = s."region" WHEN MATCHED THEN DELETE',
       "Writes are rejected: MERGE"),
    _g("g_copy_into", "COPY INTO @stage FROM (SELECT 1)", "Writes are rejected: COPY INTO"),
    _g("g_cte_delete", f"WITH d AS (DELETE FROM {T} RETURNING *) SELECT * FROM d", "Writes are rejected: inside a CTE"),
    # ---- DDL and admin ----------------------------------------------------------------------------
    _g("g_truncate", f"TRUNCATE TABLE {T}", "DDL is rejected: TRUNCATE"),
    _g("g_drop_table", f"DROP TABLE {T}", "DDL is rejected: DROP"),
    _g("g_create_table", "CREATE TABLE x (a INT)", "DDL is rejected: CREATE"),
    _g("g_create_as", f"CREATE TABLE x AS {S}", "DDL is rejected: CREATE … AS SELECT"),
    _g("g_alter_table", f"ALTER TABLE {T} ADD COLUMN x INT", "DDL is rejected: ALTER"),
    _g("g_grant", f"GRANT SELECT ON {T} TO PUBLIC", "Admin is rejected: GRANT"),
    _g("g_call", "CALL some_procedure()", "Admin is rejected: CALL"),
    _g("g_use", "USE DATABASE other", "Admin is rejected: USE"),
    _g("g_alter_session", "ALTER SESSION SET QUERY_TAG = 'x'", "Admin is rejected: ALTER SESSION"),
    # ---- injection and reaching past the Model ---------------------------------------------------
    _g("g_second_statement_delete", f"{S}; DELETE FROM {T}", "One statement only: a second is rejected"),
    _g("g_second_statement_drop", f"{S}; DROP TABLE {T}", "One statement only: a second is rejected"),
    _g("g_physical_table", 'SELECT SUM("SALES") AS s FROM "RETAILAPPAREL"."PUBLIC"."FACT_RETAPP_SALES"',
       "Only the Model is queryable: physical tables are rejected"),
    _g("g_information_schema", "SELECT table_name FROM information_schema.tables",
       "Only the Model is queryable: information_schema is rejected"),
    # ---- compiles, but neutralised: one regenerated read-only SELECT -----------------------------
    _g("g_line_comment", f"{S} -- ; DROP TABLE x", "Comments are dropped, never passed through", expect=SQL_OK),
    _g("g_block_comment", f"{S} /* ; DELETE FROM x */", "Comments are dropped, never passed through",
       expect=SQL_OK),
    _g("g_select_into", f'SELECT "t1"."region" INTO newtab FROM {T} AS "t1"',
       "SELECT … INTO compiles to a plain SELECT", expect=SQL_OK),
    _g("g_literal_semicolon", f"{S} WHERE \"t1\".\"region\" = 'x''; DROP TABLE y; --'",
       "A '; DROP inside a string literal stays a value", expect=SQL_OK, sql_has=("drop table y",)),
]
