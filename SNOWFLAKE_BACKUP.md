# Snowflake tables to Huawei OBS

Windows or Linux / Python 3.10+; no Snowflake stage is created. Each visible ordinary base table is read using one SELECT and Arrow batches written into ONE Snappy Parquet file, plus a GET_DDL SQL file. Empty tables produce a valid empty Parquet with column schema. Views and non-base tables are excluded. Unsupported column types fail that table explicitly.

## Install and run

```bash
unzip Backup-snowflake.zip
cd Backup
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
chmod 600 .env
nano .env
python main.py --source snowflake
```

Set SNOWFLAKE_DATABASES as comma-separated exact names in .env. Set the real OBS bucket name, endpoint and credentials. The existing OBS_BUCKET / OBS_ENDPOINT example values are metadata-daily-backups / af-north-1; change if necessary. No literal `bucket` directory is added.

Example object path:
`obs://metadata-daily-backups/Snowflake/BRONZE/2026/10/05/BRONZE_PROD_USERDB_USERS_20261005.parquet`

The DDL has the same stem and `.sql` extension. Existing names are skipped using `_2`, `_3`, etc. The date is the run start date in Africa/Cairo. Each table is read at its own query time; no cross-table snapshot is promised.

## Verification and failure handling

Upload uses multipart for large files but produces ONE OBS object. Both the Parquet and SQL objects are downloaded to a temporary verification file and SHA-256 compared against their originals. Both originals are deleted only after BOTH objects verify. This verification adds a complete download and can incur network charges. Allow disk for roughly twice the largest compressed table plus files retained from failures. RAM contains result batches rather than the whole table, but wide rows or large batches still need memory.

Logs are under logs/; failed complete exports remain under work/<run>/. Incomplete Parquet exports are removed. Run continues with the next table/database and returns exit code 1 if anything failed. A later run re-exports failed tables with a new suffix; automatic resume is not implemented. Partial remote backups may remain after a failure; logs identify completed tables. One local process is allowed at a time. Do not run other writers from other machines against the same object naming scheme: existence-check plus upload is not a distributed atomic reservation.

## Permissions and scope

Snowflake role needs USAGE on warehouses/databases/schemas and SELECT on all intended tables. Discovery sees only objects visible to that role: ensure grants cover your intended backup, otherwise a successful run does not prove every database table was included. GET_DDL may require additional visibility for policies/tags. DDL includes fully-qualified source names: review it before restore. The role must be able to see required policy definitions; masking policies can affect exported data. Avoid schema changes while exporting.

OBS credentials need bucket metadata access, object metadata reads, upload/multipart permissions, and GetObject for verification. The script does not delete remote objects or create a bucket. Keep .env and private keys out of git.

## Types and restoration

NUMBER is stored as Decimal128 with declared precision/scale. TIMESTAMP_NTZ is nanosecond timestamp. TIMESTAMP_TZ/LTZ and TIME are explicit strings to preserve fractional precision/offset (LTZ is exported in UTC). VARIANT/OBJECT/ARRAY use JSON strings, preserving nested JSON and distinguishing SQL NULL from JSON null. Original Snowflake types are included in Parquet schema metadata and DDL. Restoration therefore requires conversions for JSON and time/TZ text; do not assume a blind load recreates every type automatically. The SQL file creates the original table definition; it is not a full database backup of views, procedures, grants, tasks or integrations.

## Validation status

Syntax and isolated local export/upload-failure tests are checked with simulated clients. Live Snowflake/OBS execution is not tested because credentials were not supplied. Test a small database first, inspect Parquet types and row counts, then perform a restore trial before relying on this for recovery.

## Existing PostgreSQL commands

`python main.py` and `python main.py --source postgres` execute the original PostgreSQL path. Snowflake dependencies are loaded only for Snowflake runs. Both use the existing OBS_BUCKET, OBS_ENDPOINT, OBS_ACCESS_KEY_ID and OBS_SECRET_ACCESS_KEY settings. No separate bucket name setting was added. Existing PostgreSQL upload logic and paths are unchanged.

Windows setup: activate with `.\.venv\Scripts\Activate.ps1`, use `Copy-Item .env.example .env`, and set the key path to a Windows path. File locking uses filelock and tzdata supplies Cairo timezone on Windows. Linux activation is shown above.

Existing Dockerfile installs the combined requirements. Run Snowflake with:

```bash
docker build -t database-backup .
docker run --rm --env-file .env -v "$PWD/logs:/app/logs" -v "$PWD/work:/app/work" database-backup /opt/backup-venv/bin/python main.py --source snowflake
```

Mount the private key separately and set SNOWFLAKE_PRIVATE_KEY_PATH to its container path. Retain the work mount so failed exports survive container deletion.

### Existing connection compatibility
The loader accepts SNOWFLAKE_PRIVATE_KEY_PATH and SNOWFLAKE_BRONZE_WAREHOUSE. Private keys are loaded with cryptography and converted to DER PKCS8, matching the original working connection. An unencrypted key requires no password. SNOWFLAKE_PASSWORD is ignored when a private key is supplied. SNOWFLAKE_ROLE is optional. SNOWFLAKE_DATABASES controls multiple databases; if blank, SNOWFLAKE_BRONZE_DATABASE is used. SNOWFLAKE_URL is not needed. Existing alternate names PRIVATE_KEY_FILE and WAREHOUSE remain accepted. Prefer PATH and BRONZE_WAREHOUSE if both are set. No live authentication has been verified.
