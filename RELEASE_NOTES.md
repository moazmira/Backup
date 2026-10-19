# Complete database backup workflow

## Change

Adds full PostgreSQL database dumps and Snowflake table exports to a shared Huawei
OBS upload/verification workflow. The default command now performs a complete
backup; `--mode check` and `--mode local` support connection/local-file validation.

## Implementation

- Named JSON connections for multiple PostgreSQL hosts and Snowflake accounts.
- PostgreSQL server/client major validation, full custom-format dumps and archive
  reading with pg_restore before upload.
- Snowflake GET_DDL and Arrow-batch Parquet export with explicit type conversion.
- Shared OBS normal/multipart upload, downloaded SHA-256 verification, completion
  receipts, same-day filename suffixes and cleanup only after the unit is verified.
- Per-unit error isolation, Cairo logs, incremental run summaries and shared local
  filesystem lock; no automatic remote deletion or old-backup resumption.
- Source-independent metadata select helper, Dockerfile, examples and deployment/
  restore documentation. Secrets and runtime artifacts excluded from the image.

## Validation and deployment

See VALIDATION.md for checks performed and limits. Configure real credentials and
install dependencies. Start with check/local modes and an isolated restore test.
Schedule one writer per shared destination; multi-host distributed locking is not
implemented. Docker build/live service/restore validation remains to be completed
in the target environment.
