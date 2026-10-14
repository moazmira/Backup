# Backup — step 1

Requires Python 3.10 or newer. No external packages required at this step.
This is a separate fresh project, not a replacement of the existing backup.

From this folder run:

```bash
python main.py --source postgres --connection production
python main.py --source postgres --connection analytics
python main.py --source snowflake --connection production
```

These commands validate configuration structure only. Placeholder values pass
structural validation; no credentials, private key, connectivity, database
existence, or permissions are checked. No backups or uploads occur.

- `main.py`: parses arguments, calls settings functions, logs safe summaries.
- `utils/logger.py`: creates console and UTF-8 file handlers; one file per run in `logs/`.
  INFO records progress; ERROR records validation failures. Timestamps use the
  machine's local timezone without fractional seconds. No secrets are logged.
- `config/settings.py`: reads JSON and validates required fields and types.
- `secret/postgres.json`: named hosts and their databases.
- `secret/snowflake.json`: named accounts and their databases; key authentication.
- `secret/obs.json`: shared upload destination.

All credentials are examples. Replace them locally. In the connection step,
relative private-key paths will be resolved against `secret/`. The key file is
not included or opened at this step. The folder is excluded from Git; it is
plain local storage, not encryption. Do not commit actual secrets.
