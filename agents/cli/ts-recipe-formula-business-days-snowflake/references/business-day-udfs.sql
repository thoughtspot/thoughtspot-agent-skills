-- Business-day (weekday-only) UDFs for ThoughtSpot + Snowflake.
-- Deployed by ts-recipe-formula-business-days-snowflake via:
--   ts snowflake exec -f references/business-day-udfs.sql --sf-profile <name> \
--     --var target_db=<DB> --var target_schema=<SCHEMA>
--
-- {target_db} / {target_schema} are filled by `ts snowflake exec --var`.
-- Creation ORDER MATTERS: get_business_duration_str calls
-- get_business_minutes_clamped by fully qualified name, so minutes must exist
-- first. Statements run in file order and stop at the first error.
-- All three clamp weekend boundaries to the nearest weekday.

CREATE OR REPLACE FUNCTION {target_db}.{target_schema}.get_business_minutes_clamped(
    start_ts TIMESTAMP, end_ts TIMESTAMP
)
RETURNS INT
AS
$$
    DATEDIFF('minute',
        CASE
            WHEN DAYNAME(start_ts) = 'Sat' THEN DATEADD('day', 2, DATE_TRUNC('day', start_ts))
            WHEN DAYNAME(start_ts) = 'Sun' THEN DATEADD('day', 1, DATE_TRUNC('day', start_ts))
            ELSE start_ts
        END,
        CASE
            WHEN DAYNAME(end_ts) = 'Sat' THEN DATEADD('second', -1, DATE_TRUNC('day', end_ts))
            WHEN DAYNAME(end_ts) = 'Sun' THEN DATEADD('second', -1, DATEADD('day', -1, DATE_TRUNC('day', end_ts)))
            ELSE end_ts
        END
    )
    - (DATEDIFF('week',
        CASE
            WHEN DAYNAME(start_ts) = 'Sat' THEN DATEADD('day', 2, DATE_TRUNC('day', start_ts))
            WHEN DAYNAME(start_ts) = 'Sun' THEN DATEADD('day', 1, DATE_TRUNC('day', start_ts))
            ELSE start_ts
        END,
        CASE
            WHEN DAYNAME(end_ts) = 'Sat' THEN DATEADD('second', -1, DATE_TRUNC('day', end_ts))
            WHEN DAYNAME(end_ts) = 'Sun' THEN DATEADD('second', -1, DATEADD('day', -1, DATE_TRUNC('day', end_ts)))
            ELSE end_ts
        END
    ) * 2 * 1440)
$$;

CREATE OR REPLACE FUNCTION {target_db}.{target_schema}.get_business_days_clamped(
    start_ts TIMESTAMP, end_ts TIMESTAMP, inclusive BOOLEAN
)
RETURNS INT
AS
$$
    (DATEDIFF('day',
        CASE
            WHEN DAYNAME(start_ts) = 'Sat' THEN DATEADD('day', 2, DATE_TRUNC('day', start_ts))
            WHEN DAYNAME(start_ts) = 'Sun' THEN DATEADD('day', 1, DATE_TRUNC('day', start_ts))
            ELSE start_ts
        END,
        CASE
            WHEN DAYNAME(end_ts) = 'Sat' THEN DATEADD('day', -1, DATE_TRUNC('day', end_ts))
            WHEN DAYNAME(end_ts) = 'Sun' THEN DATEADD('day', -2, DATE_TRUNC('day', end_ts))
            ELSE end_ts
        END
    ) + CASE WHEN inclusive THEN 1 ELSE 0 END)
    - (DATEDIFF('week',
        CASE
            WHEN DAYNAME(start_ts) = 'Sat' THEN DATEADD('day', 2, DATE_TRUNC('day', start_ts))
            WHEN DAYNAME(start_ts) = 'Sun' THEN DATEADD('day', 1, DATE_TRUNC('day', start_ts))
            ELSE start_ts
        END,
        CASE
            WHEN DAYNAME(end_ts) = 'Sat' THEN DATEADD('day', -1, DATE_TRUNC('day', end_ts))
            WHEN DAYNAME(end_ts) = 'Sun' THEN DATEADD('day', -2, DATE_TRUNC('day', end_ts))
            ELSE end_ts
        END
    ) * 2)
$$;

CREATE OR REPLACE FUNCTION {target_db}.{target_schema}.get_business_duration_str(
    start_ts TIMESTAMP, end_ts TIMESTAMP
)
RETURNS STRING
AS
$$
    FLOOR({target_db}.{target_schema}.get_business_minutes_clamped(start_ts, end_ts) / 60)
    || ':'
    || LPAD(MOD({target_db}.{target_schema}.get_business_minutes_clamped(start_ts, end_ts), 60), 2, '0')
$$;
