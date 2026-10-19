# Suggested review sequence

1. `config/settings.py`: JSON connection selection, required fields/defaults,
   source-specific validation and shared paths. No file download/upload occurs.
2. `connections/postgres.py`, `connections/snowflake.py`, `connections/obs.py`:
   one connection responsibility each; Snowflake also loads its private key.
3. `utils/database.py` and `dbqueries/snowflake.py`: small metadata results via
   `select_data`; business-table exports use Arrow batches instead of fetchall.
4. `services/postgres_backup.py`: identify server version, select matching tools,
   run a full-database custom-format dump, then read-check it with pg_restore.
5. `services/snowflake_export.py`: type mapping, SELECT conversion expressions,
   schema metadata, GET_DDL, temporary Parquet writing and finalization.
6. `storage/obs.py`: inspect object existence, choose a suffix, upload, download
   and verify SHA-256, publish completion receipt, and only then remove local files.
7. `services/snowflake_backup.py`: list tables, process SQL/Parquet pairs, continue
   after per-table failures and persist unit results. PostgreSQL runner applies
   the equivalent behavior per database rather than per table.
8. `main.py`: choose mode/source, acquire shared run lock, connect OBS only when
   needed, open/close source, and return correct final exit status.
9. `tests/test_backup.py`: verify failure paths and expected output before looking
   at the Dockerfile and deployment/restore examples.

Operational choices to confirm for the target: PostgreSQL client majors, names and
permissions of target Snowflake databases, warehouse capacity, source policies,
backup window, OBS single-writer arrangement, disk capacity for verification,
remote retention, alerting in the actual scheduler, and isolated restore results.
