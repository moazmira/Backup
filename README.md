# Backup — step 2: connection checks

Python 3.10 or newer. Install in a virtual environment:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python main.py --source postgres --connection production
.venv/bin/python main.py --source snowflake --connection production
```

Keep your existing secret JSON files. No secrets are included in the changes archive.

- main.py: validates settings, checks the selected source, then checks OBS.
- connections/postgres.py: connects to each configured database and reads database,
  username and server version.
- connections/snowflake.py: loads the PEM key as DER, connects, reads session context
  and checks access to every configured database using USE DATABASE.
- connections/obs.py: checks bucket access with listObjects(max_keys=1).
- utils/logger.py: logs to console and one file per run in logs/.

Relative Snowflake key paths resolve against secret/, independently of the working
folder. Set private_key_file to your PEM key path. Keep private_key_password empty
for an unencrypted key, or supply the key's passphrase.

No backup, upload, delete, business-table query or data modification occurs.
The OBS check confirms list access only; it does not prove upload/read permissions.
Database connection checks do not prove backup permissions on every table.
A failure stops the run with exit code 1, records the traceback and closes connections.
Use real configuration before running; no live services were tested during creation.
