# Validation record

Date: 2026-10-19. Runtime: Linux x86_64, Python 3.12.

## Completed

- Installed both connectors, Arrow, OBS SDK and filelock in the validation runtime.
- 26 unittest tests passed:
  - Real Parquet files: large Decimal(38), Arabic text, nulls, schema metadata,
    batch appends, empty tables and interrupted-write cleanup.
  - SQL DDL saving and refusal to overwrite local files.
  - Full Snowflake CLI workflow with actual generated files and simulated source/
    OBS byte transfers, including completion receipt, cleanup and run summary.
  - Shared object naming/suffixes, existing-object refusal, permission errors,
    corruption detection, verification retry without re-upload, multipart branch,
    pair/receipt failures retaining local originals, and keep-local behavior.
  - PostgreSQL full-database command construction without table/schema filters,
    password passed through environment only, archive-validation invocation,
    partial cleanup, mismatched-client rejection and continuation after DB failure.
  - Failed-unit summary/exit status, source connection cleanup, unique run folders,
    safe path encoding, old-style JSON compatibility and no OBS access in local mode.
- Python source compile checks passed.
- CLI --help passed.
- Real installed OBS SDK method signatures matched the implemented calls:
  putFile, uploadFile (multipart), getObject(downloadPath), getObjectMetadata.
- Deliverable ZIP excludes credentials, keys, logs, backups, caches, virtual
  environments and dependency install directories.

Tested primary dependencies:

| Package | Version |
| --- | --- |
| snowflake-connector-python | 4.8.0 |
| esdk-obs-python | 3.26.6 |
| pyarrow | 21.0.0 |
| psycopg2-binary | 2.9.13 |
| filelock | 3.32.7 |

`requirements.lock.txt` records the exact resolved validation dependencies on
Linux/Python 3.12. `requirements.txt` gives compatible dependency ranges for
installation on the target runtime. Do not claim other combinations were tested.

## Not performed in this environment

- Real PostgreSQL connection, pg_dump, pg_restore, or restore into a live test DB.
  Tool invocations were simulated; no PostgreSQL server/client is available here.
- Real Snowflake export or source-vs-restored data reconciliation.
- Real OBS uploads/downloads/permissions/multipart assembly, network interruption
  or large-file load tests. The in-memory test double is not an OBS service.
- Docker build/run (Docker unavailable), cron installation, remote deployment,
  registry push, or edits to any external application's configuration.

Before scheduling, run --mode check, then --mode local with your configured
credentials and matching pg_dump version. Validate restore in isolated targets,
then run backup with --keep-local to inspect the first real upload. Confirm the
receipt and its hashes before relying on cleanup. The restore guide documents
conversion of timestamps and JSON back to their original Snowflake types.
