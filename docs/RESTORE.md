# Restore validation

Restore commands below are manual examples, not operations performed by this
project. Validate in an isolated empty target; the backup runner never executes
DDL against production or imports data.

## Choose a complete backup

Use a matching `.complete.json` receipt and the file keys/hash/bytes it lists.
Download the listed objects with your normal OBS SDK/console tool and verify
SHA-256 locally (e.g. `sha256sum file.parquet`). Files without a completion receipt
may be partial units left after an interrupted upload. Local-only runs are tracked
as `local_ready` in their run summary and have no remote completion receipt.

## PostgreSQL

Use a compatible pg_restore (normally the same major as the pg_dump used). Prepare
the required server extensions, target roles or ownership remapping. Example
restore into a new empty database, with password obtained through your normal
.pgpass or interactive mechanism:

```bash
createdb --host RESTORE_HOST --username RESTORE_USER restore_test
pg_restore --host RESTORE_HOST --username RESTORE_USER \
  --dbname restore_test --no-owner --no-privileges --exit-on-error backup.dump
```

Do not use `--clean` against a live database. The `--no-owner/--no-privileges`
options intentionally omit original ownership/grants for an isolated validation.
For a faithful restore prepare original roles and omit those flags as appropriate.
pg_dump does not include cluster-global role/tablespace definitions. Validate table
counts, sample content, constraints, sequences and application behavior after
restore; archive readability/checksum alone is not proof of a successful restore.

## Snowflake

1. Prepare an isolated restore database/schema and required dependencies.
2. Review the `.sql` file. GET_DDL may contain CREATE OR REPLACE, original qualified
   database names, policies, tags and other references. Change target namespaces
   deliberately; never execute it blindly against the original table.
3. Upload `.parquet` to a stage in the target environment (e.g. Snowsight or PUT
   through SnowSQL/CLI) and create a named PARQUET file format.
4. Load using explicit columns and conversion expressions. The exporter retains
   Snowflake source types in Arrow schema metadata (`snowflake_columns`).

Example for a source table with ID NUMBER, NAME VARCHAR, CREATED TIMESTAMP_NTZ,
EVENT_AT TIMESTAMP_TZ, WALL_TIME TIME, DETAILS VARIANT, PAYLOAD BINARY:

```sql
CREATE FILE FORMAT RESTORE_TEST.PUBLIC.BACKUP_PARQUET TYPE = PARQUET;
-- Stage and destination table must already exist in the isolated namespace.
COPY INTO RESTORE_TEST.PUBLIC.USERS
  (ID, NAME, CREATED, EVENT_AT, WALL_TIME, DETAILS, PAYLOAD)
FROM (
  SELECT
    $1:ID::NUMBER(38,0),
    $1:NAME::VARCHAR,
    TO_TIMESTAMP_NTZ($1:CREATED::VARCHAR, 'YYYY-MM-DD"T"HH24:MI:SS.FF9'),
    TO_TIMESTAMP_TZ($1:EVENT_AT::VARCHAR, 'YYYY-MM-DD"T"HH24:MI:SS.FF9 TZH:TZM'),
    TO_TIME($1:WALL_TIME::VARCHAR, 'HH24:MI:SS.FF9'),
    PARSE_JSON($1:DETAILS::VARCHAR),
    $1:PAYLOAD::BINARY
  FROM @RESTORE_TEST.PUBLIC.RESTORE_STAGE/users.parquet
)
FILE_FORMAT = (FORMAT_NAME = 'RESTORE_TEST.PUBLIC.BACKUP_PARQUET');
```

Use the actual case-sensitive Parquet column names and source type precision/scale.
TIMESTAMP_LTZ strings contain the UTC offset; parse with TO_TIMESTAMP_TZ then cast
to the destination TIMESTAMP_LTZ. DATE/Boolean/numeric/binary columns use their
corresponding native representations. JSON text needs PARSE_JSON to recreate
VARIANT; cast appropriately for OBJECT/ARRAY. SQL NULL and JSON null are distinct.
The backup deliberately keeps timestamp fractions even though operational log
messages have seconds precision.

Validate row counts and representative values, large decimals, nulls, Unicode,
TIME/TIMESTAMP precision and offsets, and JSON content after loading. Source row
access/masking policies may have limited the exported data. Multiple tables were
not captured as one transaction-wide snapshot. Unsupported types are logged as
failed and must not be counted as backed up. This workflow exports table data and
DDL; it is not an account-level backup of all Snowflake objects/permissions.
