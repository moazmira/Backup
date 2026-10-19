import json
import logging
import os
import tempfile
import unittest
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

import pyarrow as pa
import pyarrow.parquet as pq
import main
from config import settings as config
from dbqueries.snowflake import export_query, quote_identifier
from services import postgres_backup as pg
from services import snowflake_backup as sf
from services.snowflake_export import export_parquet
from storage.obs import object_exists, transfer_files, upload_verified
from utils import postgres_tools as tools
from utils.files import path_component

def response(status=200, body=None):
    return SimpleNamespace(status=status, body=body, errorCode="TestError", errorMessage="Test response")


class FakeObs:
    """In-memory OBS test double performing real file byte transfers."""
    def __init__(self):
        self.objects, self.calls = {}, []
        self.fail_key, self.corrupt_download = None, False

    def getObjectMetadata(self, bucket, key):
        return response(body=SimpleNamespace(contentLength=len(self.objects[key]))) if key in self.objects else response(404)

    def putFile(self, bucket, key, path):
        self.calls.append(("put", key))
        if key == self.fail_key:
            return response(503)
        if key in self.objects:
            raise AssertionError("Overwrite detected")
        self.objects[key] = Path(path).read_bytes()
        return response()

    def uploadFile(self, **kwargs):
        self.calls.append(("multipart", kwargs["objectKey"]))
        return self.putFile(kwargs["bucketName"], kwargs["objectKey"], kwargs["uploadFile"])

    def getObject(self, bucket, key, downloadPath):
        data = self.objects[key]
        Path(downloadPath).write_bytes(b"x" * len(data) if self.corrupt_download else data)
        return response()


class BackupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        handler = logging.NullHandler(); logging.getLogger("backup").addHandler(handler)
        self.addCleanup(logging.getLogger("backup").removeHandler, handler)
        self.root = Path(self.temp.name); self.obs = FakeObs()
        self.obs_settings = {"bucket": "bucket", "attempts": 1, "multipart_threshold_mb": 100}
        self.now = datetime(2026, 10, 19, 12, tzinfo=ZoneInfo("Africa/Cairo"))

    def files(self):
        files = [self.root / "T.sql", self.root / "T.parquet"]
        files[0].write_text("CREATE TABLE T (ID NUMBER);"); files[1].write_bytes(b"parquet-test")
        return files

    def test_pair_and_completion_verified_before_cleanup(self):
        files = self.files()
        transfer_files(self.obs, self.obs_settings, files, "base/T")
        self.assertTrue(all(not p.exists() for p in files))
        self.assertEqual(len(json.loads(self.obs.objects["base/T.complete.json"])["files"]), 2)

    def test_pair_failure_keeps_both_files(self):
        files = self.files(); self.obs.fail_key = "base/T.parquet"
        with self.assertRaises(RuntimeError): transfer_files(self.obs, self.obs_settings, files, "base/T")
        self.assertTrue(all(p.exists() for p in files)); self.assertNotIn("base/T.complete.json", self.obs.objects)

    def test_marker_failure_keeps_original_files(self):
        files = self.files(); self.obs.fail_key = "base/T.complete.json"
        with self.assertRaises(RuntimeError): transfer_files(self.obs, self.obs_settings, files, "base/T")
        self.assertTrue(all(p.exists() for p in files))

    def test_corruption_keeps_files_and_cleans_verification(self):
        files = self.files(); self.obs.corrupt_download = True
        with self.assertRaisesRegex(RuntimeError, "SHA-256"): transfer_files(self.obs, self.obs_settings, files, "base/T")
        self.assertTrue(all(p.exists() for p in files)); self.assertEqual(list(self.root.glob("*.verify")), [])

    def test_suffix_reserves_pair(self):
        self.obs.objects.update({"base/T.sql": b"old", "base/T_2.complete.json": b"marker"})
        transfer_files(self.obs, self.obs_settings, self.files(), "base/T")
        self.assertIn("base/T_3.sql", self.obs.objects); self.assertEqual(self.obs.objects["base/T.sql"], b"old")

    def test_denied_metadata_is_not_missing(self):
        self.obs.getObjectMetadata = lambda *args: response(403)
        with self.assertRaises(RuntimeError): object_exists(self.obs, "bucket", "key")

    def test_refuse_overwrite(self):
        path = self.files()[0]; self.obs.objects["existing"] = b"old"
        with self.assertRaises(FileExistsError): upload_verified(self.obs, self.obs_settings, "existing", path)

    def test_multipart_one_final_file(self):
        path = self.root / "large.dump"; path.write_bytes(b"a" * 1048576)
        upload_verified(self.obs, {**self.obs_settings, "multipart_threshold_mb": 1}, "large", path)
        self.assertIn(("multipart", "large"), self.obs.calls); self.assertEqual(list(self.obs.objects), ["large"])

    def test_verification_retries_not_reupload(self):
        from storage import obs as module
        with patch.object(module, "verify_upload", side_effect=[RuntimeError("timeout"), None]) as verify, patch.object(module.time, "sleep"):
            upload_verified(self.obs, {**self.obs_settings, "attempts": 2}, "file", self.files()[0])
            self.assertEqual(verify.call_count, 2)
        self.assertEqual(self.obs.calls, [("put", "file")])

    def native_table(self):
        return pa.table({
            "ID": pa.array([Decimal("12345678901234567890123456789012345678")], type=pa.decimal128(38, 0)),
            "NAME": ["عربي"], "DATE": pa.array([date(2026, 10, 19)], type=pa.date32()),
            "TS": pa.array([1760000000123456789], type=pa.timestamp("ns")),
            "TIME": pa.array([123456789], type=pa.time64("ns")), "JSON": ['{"x":1}'],
        })

    def fake_connection(self, table, batches):
        connection = MagicMock(); cursor = connection.cursor.return_value.__enter__.return_value
        cursor.fetchall.return_value = [(name, "VARCHAR(200)", "COLUMN", "Y") for name in table.column_names]
        cursor.fetch_arrow_all.return_value = table.slice(0, 0)
        cursor.fetch_arrow_batches.return_value = iter(batches)
        return connection

    def test_native_types_and_nanoseconds_preserved(self):
        table = self.native_table(); connection = self.fake_connection(table, [None, table, table])
        path = self.root / "T.parquet"
        self.assertEqual(export_parquet(connection, '"D"."S"."T"', path), 2)
        result = pq.read_table(path)
        self.assertEqual(result.schema, table.schema)
        self.assertEqual(result.slice(0, 1).to_pydict(), table.to_pydict())
        connection.cursor.return_value.__enter__.return_value.fetch_arrow_all.assert_not_called()

    def test_empty_table_preserves_schema(self):
        table = self.native_table(); connection = self.fake_connection(table, [])
        path = self.root / "empty.parquet"
        self.assertEqual(export_parquet(connection, '"D"."S"."T"', path), 0)
        self.assertEqual(pq.read_table(path).schema, table.schema)

    def test_safe_cast_does_not_truncate_timestamps(self):
        schema_table = pa.table({"TS": pa.array([], type=pa.timestamp("us"))})
        batch = pa.table({"TS": pa.array([1760000000123456789], type=pa.timestamp("ns"))})
        connection = self.fake_connection(schema_table, [schema_table, batch]); path = self.root / "unsafe.parquet"
        with self.assertRaises(pa.ArrowInvalid): export_parquet(connection, '"D"."S"."T"', path)
        self.assertFalse(path.exists()); self.assertFalse(path.with_suffix(".parquet.partial").exists())

    def test_safe_cast_widens_integer_batches(self):
        table = pa.table({"ID": pa.array([], type=pa.int64())})
        batch = pa.table({"ID": pa.array([1], type=pa.int8())})
        connection = self.fake_connection(table, [table, batch]); path = self.root / "ints.parquet"
        self.assertEqual(export_parquet(connection, '"D"."S"."T"', path), 1)
        self.assertEqual(pq.read_table(path).schema.field("ID").type, pa.int64())

    def test_number_schema_preserves_scaled_decimal_for_empty_table(self):
        initial = pa.table({"AMOUNT": pa.array([], type=pa.int64())})
        connection = self.fake_connection(initial, [])
        connection.cursor.return_value.__enter__.return_value.fetchall.return_value = [("AMOUNT", "NUMBER(19,4)", "COLUMN", "Y")]
        path = self.root / "decimal_empty.parquet"
        self.assertEqual(export_parquet(connection, '"D"."S"."T"', path), 0)
        self.assertEqual(pq.read_table(path).schema.field("AMOUNT").type, pa.decimal128(19, 4))

    def test_integer_width_changes_preserve_large_number(self):
        small = pa.table({"ID": pa.array([1], type=pa.int8())})
        large = pa.table({"ID": pa.array([Decimal("12345678901234567890123456789012345678")], type=pa.decimal128(38, 0))})
        connection = self.fake_connection(small, [small, large])
        connection.cursor.return_value.__enter__.return_value.fetchall.return_value = [("ID", "NUMBER(38,0)", "COLUMN", "Y")]
        path = self.root / "mixed.parquet"
        self.assertEqual(export_parquet(connection, '"D"."S"."T"', path), 2)
        self.assertEqual(pq.read_table(path).to_pylist()[1]["ID"], Decimal("12345678901234567890123456789012345678"))

    def test_cli_rejects_removed_mode(self):
        with patch("sys.argv", ["main.py", "--source", "postgres", "--connection", "production", "--mode", "local"]), patch("sys.stderr"):
            with self.assertRaises(SystemExit) as error: main.main()
        self.assertEqual(error.exception.code, 2)

    def test_timestamp_tz_expression_only(self):
        connection = MagicMock(); cursor = connection.cursor.return_value.__enter__.return_value
        cursor.fetchall.return_value = [("TS", "TIMESTAMP_TZ(9)"), ("DAY", "DATE"), ("AT", "TIMESTAMP_NTZ(9)")]
        query, _ = export_query(connection, '"D"."S"."T"')
        self.assertIn('TO_CHAR("TS"', query); self.assertNotIn('TO_CHAR("AT"', query)
        self.assertIn('"DAY", "AT"', query); self.assertEqual(quote_identifier('A"B'), '"A""B"')

    def test_snowflake_schema_folder_and_same_named_tables(self):
        captured = []; failures = []
        def transfer(client, settings, files, key): captured.append(key)
        with patch.object(sf, "list_tables", return_value=[("PUBLIC", "USERS"), ("SALES", "USERS")]), patch.object(sf, "backup_table", return_value=([], 10)), patch.object(sf, "transfer_files", side_effect=transfer):
            count = sf.backup_snowflake(MagicMock(), {"databases": ["BRONZE"]}, self.obs, self.obs_settings, self.root, self.now)
        self.assertEqual(count, 0)
        self.assertTrue(captured[0].startswith("Snowflake/BRONZE/PUBLIC/2026/10/19/"))
        self.assertTrue(captured[1].startswith("Snowflake/BRONZE/SALES/2026/10/19/"))

    def test_continue_after_table_failure(self):
        with patch.object(sf, "list_tables", return_value=[("S", "bad"), ("S", "good")]), patch.object(sf, "backup_table", side_effect=[RuntimeError("bad"), ([], 1)]), patch.object(sf, "transfer_files") as transfer:
            self.assertEqual(sf.backup_snowflake(MagicMock(), {"databases": ["DB"]}, self.obs, self.obs_settings, self.root, self.now), 1)
        transfer.assert_called_once()

    def test_dot_in_ip_preserved_and_traversal_encoded(self):
        self.assertEqual(path_component("10.11.5.4"), "10.11.5.4")
        self.assertEqual(path_component(".."), "%2E%2E")
        self.assertEqual(path_component("a/b"), "a%2Fb")

    def test_env_supports_multiple_named_hosts_and_accounts(self):
        values = {"PG_PRODUCTION_HOST": "host1", "PG_PRODUCTION_USER": "u", "PG_PRODUCTION_PASSWORD": "p", "PG_PRODUCTION_DATABASES": "db1,db2", "PG_ANALYTICS_HOST": "host2", "PG_ANALYTICS_USER": "u2", "PG_ANALYTICS_PASSWORD": "p2", "PG_ANALYTICS_DATABASES": "db3", "SNOWFLAKE_PRODUCTION_ACCOUNT": "a", "SNOWFLAKE_PRODUCTION_USER": "u", "SNOWFLAKE_PRODUCTION_ROLE": "r", "SNOWFLAKE_PRODUCTION_WAREHOUSE": "w", "SNOWFLAKE_PRODUCTION_PRIVATE_KEY_FILE": "secret/key.p8", "SNOWFLAKE_PRODUCTION_DATABASES": "BRONZE,SILVER"}
        with patch.dict(os.environ, values, clear=True):
            self.assertEqual(config.load_source_config("postgres", "production")["databases"], ["db1", "db2"])
            self.assertEqual(config.load_source_config("postgres", "analytics")["host"], "host2")
            self.assertEqual(config.load_source_config("snowflake", "production")["databases"], ["BRONZE", "SILVER"])

    def test_missing_credentials_error_names_variable_not_value(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(ValueError, "PG_PRODUCTION_DATABASES"): config.load_source_config("postgres", "production")

    def test_newer_pg_client_accepted_older_rejected(self):
        dump = self.root / "pg_dump"; restore = self.root / "pg_restore"; dump.touch(); restore.touch()
        with patch.object(tools, "connect_postgres", return_value=MagicMock()), patch.object(tools, "select_data", return_value=[("160001",)]), patch.object(tools, "tool_version", return_value=18):
            self.assertEqual(tools.get_pg_tools({"pg_dump_path": str(dump)}, "db"), (dump, restore))
        with patch.object(tools, "connect_postgres", return_value=MagicMock()), patch.object(tools, "select_data", return_value=[("180001",)]), patch.object(tools, "tool_version", return_value=16):
            with self.assertRaisesRegex(RuntimeError, "pg_dump >= 18"): tools.get_pg_tools({"pg_dump_path": str(dump)}, "db")

    def test_full_dump_then_validation_and_postgres_key_unchanged(self):
        settings = {"host": "10.11.5.4", "port": 5432, "user": "u", "password": "secret-test-value", "databases": ["db"]}
        commands = []; keys = []
        def execute(command, settings, env=None):
            commands.append(command)
            if "--format=custom" in command:
                self.assertNotIn("secret-test-value", " ".join(str(v) for v in command)); self.assertEqual(env["PGPASSWORD"], "secret-test-value")
                Path(command[command.index("--file") + 1]).write_bytes(b"dump")
        with patch.object(pg, "get_pg_tools", return_value=(Path("pg_dump"), Path("pg_restore"))), patch.object(pg, "run_tool", side_effect=execute), patch.object(pg, "transfer_files", side_effect=lambda c,s,f,k:keys.append(k)):
            self.assertEqual(pg.backup_postgres(settings, self.obs, self.obs_settings, self.root, self.now), 0)
        self.assertNotIn("--schema", commands[0]); self.assertNotIn("--table", commands[0]); self.assertIn(os.devnull, commands[1])
        self.assertTrue(keys[0].startswith("10.11.5.4/db/2026/10/19/"))

    def test_main_full_flow_cleanup_no_summary(self):
        from utils import files as module
        import connections.snowflake as connector
        table = self.native_table(); connection = self.fake_connection(table, [table]); self.obs.close = MagicMock()
        args = SimpleNamespace(source="snowflake", connection="production")
        with patch.object(module, "BACKUP_DIR", self.root), patch.object(connector, "connect_snowflake", return_value=connection), patch.object(sf, "list_tables", return_value=[("PUBLIC", "USERS")]), patch("services.snowflake_backup.export_ddl", side_effect=lambda c,a,p:p.write_text("CREATE TABLE T (ID NUMBER);")):
            self.assertEqual(main.run_backup(args, {"databases": ["BRONZE"]}, self.obs, self.obs_settings), 0)
        self.assertEqual(len(self.obs.objects), 3)
        self.assertTrue(all(key.startswith("Snowflake/BRONZE/PUBLIC/") for key in self.obs.objects))
        self.assertEqual(list(self.root.rglob("summary.json")), []); self.assertEqual(list(self.root.rglob("*.parquet")), [])
        connection.close.assert_called_once()


if __name__ == "__main__":
    unittest.main()
