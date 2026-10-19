# Apply the update

1. Wait for the current backup to finish before replacing code.
2. Save your existing configuration privately. Copy the supplied code into your
   project, retaining the private-key file and existing logs/backups.
3. Create/update `.env` from the example using your actual settings. Do not copy
   placeholder values over a working .env. JSON configuration is no longer used.
4. Install `requirements.txt` (adds python-dotenv; uses Connector 4.8+).
5. Run the ordinary source/connection command. It always performs the complete
   upload/verify/cleanup workflow. Removed flags are no longer accepted.

| Old setting | New .env key (connection production) |
| --- | --- |
| postgres production.host | PG_PRODUCTION_HOST |
| postgres production.port | PG_PRODUCTION_PORT |
| postgres production.user | PG_PRODUCTION_USER |
| postgres production.password | PG_PRODUCTION_PASSWORD |
| postgres production.databases list | PG_PRODUCTION_DATABASES=db1,db2 |
| postgres production.sslmode | PG_PRODUCTION_SSLMODE (optional) |
| postgres production.pg_dump_path | PG_PRODUCTION_PG_DUMP_PATH (optional), or PG_DUMP_PATH |
| snowflake production.account | SNOWFLAKE_PRODUCTION_ACCOUNT |
| snowflake production.user | SNOWFLAKE_PRODUCTION_USER |
| snowflake production.warehouse | SNOWFLAKE_PRODUCTION_WAREHOUSE |
| snowflake production.role | SNOWFLAKE_PRODUCTION_ROLE |
| snowflake production.private_key_file | SNOWFLAKE_PRODUCTION_PRIVATE_KEY_FILE=secret/rsa_key.p8 |
| snowflake production.private_key_password | SNOWFLAKE_PRODUCTION_PRIVATE_KEY_PASSWORD |
| snowflake production.databases list | SNOWFLAKE_PRODUCTION_DATABASES=BRONZE,SILVER |
| obs.endpoint | OBS_ENDPOINT |
| obs.bucket | OBS_BUCKET |
| obs.access_key_id | OBS_ACCESS_KEY_ID |
| obs.secret_access_key | OBS_SECRET_ACCESS_KEY |
| obs.multipart_threshold_mb | OBS_MULTIPART_THRESHOLD_MB (optional) |
| obs.part_size_mb | OBS_PART_SIZE_MB (optional) |
| obs.upload_threads | OBS_UPLOAD_THREADS (optional) |
| obs.attempts | OBS_ATTEMPTS (optional) |

Other optional environment variables: PG_<NAME>_CONNECT_TIMEOUT,
PG_<NAME>_DUMP_TIMEOUT, SNOWFLAKE_<NAME>_CONNECT_TIMEOUT,
SNOWFLAKE_<NAME>_QUERY_TIMEOUT, OBS_TIMEOUT, BACKUP_OUTPUT_DIR and BACKUP_LOG_DIR.
Default timeouts/paths remain as in the earlier version. With Docker, env vars
supplied directly by Docker override .env; e.g. image PG_DUMP_PATH selects its
included PostgreSQL 18 client unless a connection-specific path is supplied.

## Remove these obsolete source files after updating an existing checkout

- services/checks.py
- utils/database.py
- requirements.lock.txt

The full clean archive does not contain these files. Old summary.json files and
old OBS paths are not modified; the new code simply stops producing summaries.
Old examples/*.json and old documentation may be archived/deleted if desired,
but do not delete your only copy of real credentials before verifying .env.

New Snowflake uploads use:

```
Snowflake/BRONZE/PUBLIC/YYYY/MM/DD/BRONZE_PUBLIC_USERS_YYYYMMDD.parquet
```

Existing remote backups remain at their old paths. PostgreSQL path layout is
unchanged. Timestamp/JSON restore handling is different from the earlier version:
DATE/TIME/NTZ/LTZ now use native Arrow types; TIMESTAMP_TZ still needs explicit text
parsing. Review SQL source types when restoring. No mode, JSON settings or summary
are required for the new runtime.
