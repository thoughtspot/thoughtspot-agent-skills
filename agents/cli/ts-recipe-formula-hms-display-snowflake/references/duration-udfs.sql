-- Duration-display UDFs for ThoughtSpot + Snowflake.
-- Deployed by ts-recipe-formula-hms-display-snowflake via:
--   ts snowflake exec -f references/duration-udfs.sql --sf-profile <name> \
--     --var target_db=<DB> --var target_schema=<SCHEMA>
--
-- {target_db} / {target_schema} are filled by `ts snowflake exec --var`.
-- All four UDFs are independent — no creation-order constraint. Statements run
-- in file order and stop at the first error.

CREATE OR REPLACE FUNCTION {target_db}.{target_schema}.format_seconds_to_hms(seconds INT)
RETURNS STRING
AS
$$
    LPAD(TRUNC(seconds / 3600)::STRING, 2, '0') || ':' ||
    LPAD(TRUNC(MOD(seconds, 3600) / 60)::STRING, 2, '0') || ':' ||
    LPAD(MOD(seconds, 60)::STRING, 2, '0')
$$;

CREATE OR REPLACE FUNCTION {target_db}.{target_schema}.format_seconds_to_dhms(seconds INT)
RETURNS STRING
AS
$$
    LPAD(TRUNC(seconds / 86400)::STRING, 2, '0') || ':' ||
    LPAD(TRUNC(MOD(seconds, 86400) / 3600)::STRING, 2, '0') || ':' ||
    LPAD(TRUNC(MOD(seconds, 3600) / 60)::STRING, 2, '0') || ':' ||
    LPAD(MOD(seconds, 60)::STRING, 2, '0')
$$;

CREATE OR REPLACE FUNCTION {target_db}.{target_schema}.format_minutes_to_hm(minutes INT)
RETURNS STRING
AS
$$
    LPAD(TRUNC(minutes / 60)::STRING, 2, '0') || ':' ||
    LPAD(MOD(minutes, 60)::STRING, 2, '0')
$$;

CREATE OR REPLACE FUNCTION {target_db}.{target_schema}.format_minutes_to_dhm(minutes INT)
RETURNS STRING
AS
$$
    LPAD(TRUNC(minutes / 1440)::STRING, 2, '0') || ':' ||
    LPAD(TRUNC(MOD(minutes, 1440) / 60)::STRING, 2, '0') || ':' ||
    LPAD(MOD(minutes, 60)::STRING, 2, '0')
$$;
