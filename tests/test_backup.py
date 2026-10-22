import ast
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
from utils import obs_upload as obs_module
from utils import backup_paths as files_module
from connections import snowflake as snowflake_module
from config import settings as config
from utils.snowflake_export import build_select_query
from utils.snowflake_export import quote_identifier
from services import postgres_backup as pg
from services import snowflake_backup as sf
from utils.snowflake_export import save_table_parquet
from utils.obs_upload import object_exists, transfer_files, upload_file
from utils import postgres_dump as tools


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

    def test_size_mismatch_keeps_files_without_download(self):
        files = self.files()
        original = self.obs.getObjectMetadata
        def metadata(bucket, key):
            result = original(bucket, key)
            if result.status == 200:
                result.body.contentLength += 1
            return result
        self.obs.getObjectMetadata = metadata
        self.obs.getObject = MagicMock(side_effect=AssertionError("Download forbidden"))
        with self.assertRaisesRegex(RuntimeError, "size mismatch"):
            transfer_files(self.obs, self.obs_settings, files, "base/T")
        self.assertTrue(all(path.exists() for path in files))
        self.obs.getObject.assert_not_called()

    def test_suffix_reserves_pair(self):
        self.obs.objects.update({"base/T.sql": b"old", "base/T_2.complete.json": b"marker"})
        transfer_files(self.obs, self.obs_settings, self.files(), "base/T")
        self.assertIn("base/T_3.sql", self.obs.objects); self.assertEqual(self.obs.objects["base/T.sql"], b"old")

    def test_denied_metadata_is_not_missing(self):
        self.obs.getObjectMetadata = lambda *args: response(403)
        with self.assertRaises(RuntimeError): object_exists(self.obs, "bucket", "key")

    def test_refuse_overwrite(self):
        path = self.files()[0]; self.obs.objects["existing"] = b"old"
        with self.assertRaises(FileExistsError): upload_file(self.obs, self.obs_settings, "existing", path)

    def test_multipart_one_final_file(self):
        path = self.root / "large.dump"; path.write_bytes(b"a" * 1048576)
        upload_file(self.obs, {**self.obs_settings, "multipart_threshold_mb": 1}, "large", path)
        self.assertIn(("multipart", "large"), self.obs.calls); self.assertEqual(list(self.obs.objects), ["large"])

    def test_verification_retries_not_reupload(self):
        with patch.object(obs_module, "check_uploaded_size", side_effect=[RuntimeError("timeout"), None]) as verify, patch.object(obs_module.time, "sleep"):
            upload_file(self.obs, {**self.obs_settings, "attempts": 2}, "file", self.files()[0])
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
        self.assertEqual(save_table_parquet(connection, '"D"."S"."T"', path), 2)
        result = pq.read_table(path)
        self.assertEqual(result.schema, table.schema)
        self.assertEqual(result.slice(0, 1).to_pydict(), table.to_pydict())
        connection.cursor.return_value.__enter__.return_value.fetch_arrow_all.assert_not_called()

    def test_empty_table_preserves_schema(self):
        table = self.native_table(); connection = self.fake_connection(table, [])
        path = self.root / "empty.parquet"
        self.assertEqual(save_table_parquet(connection, '"D"."S"."T"', path), 0)
        self.assertEqual(pq.read_table(path).schema, table.schema)

    def test_safe_cast_does_not_truncate_timestamps(self):
        schema_table = pa.table({"TS": pa.array([], type=pa.timestamp("us"))})
        batch = pa.table({"TS": pa.array([1760000000123456789], type=pa.timestamp("ns"))})
        connection = self.fake_connection(schema_table, [schema_table, batch]); path = self.root / "unsafe.parquet"
        with self.assertRaises(pa.ArrowInvalid): save_table_parquet(connection, '"D"."S"."T"', path)
        self.assertFalse(path.exists()); self.assertFalse(path.with_suffix(".parquet.partial").exists())

    def test_safe_cast_widens_integer_batches(self):
        table = pa.table({"ID": pa.array([], type=pa.int64())})
        batch = pa.table({"ID": pa.array([1], type=pa.int8())})
        connection = self.fake_connection(table, [table, batch]); path = self.root / "ints.parquet"
        self.assertEqual(save_table_parquet(connection, '"D"."S"."T"', path), 1)
        self.assertEqual(pq.read_table(path).schema.field("ID").type, pa.int64())

    def test_number_schema_preserves_scaled_decimal_for_empty_table(self):
        initial = pa.table({"AMOUNT": pa.array([], type=pa.int64())})
        connection = self.fake_connection(initial, [])
        connection.cursor.return_value.__enter__.return_value.fetchall.return_value = [("AMOUNT", "NUMBER(19,4)", "COLUMN", "Y")]
        path = self.root / "decimal_empty.parquet"
        self.assertEqual(save_table_parquet(connection, '"D"."S"."T"', path), 0)
        self.assertEqual(pq.read_table(path).schema.field("AMOUNT").type, pa.decimal128(19, 4))

    def test_integer_width_changes_preserve_large_number(self):
        small = pa.table({"ID": pa.array([1], type=pa.int8())})
        large = pa.table({"ID": pa.array([Decimal("12345678901234567890123456789012345678")], type=pa.decimal128(38, 0))})
        connection = self.fake_connection(small, [small, large])
        connection.cursor.return_value.__enter__.return_value.fetchall.return_value = [("ID", "NUMBER(38,0)", "COLUMN", "Y")]
        path = self.root / "mixed.parquet"
        self.assertEqual(save_table_parquet(connection, '"D"."S"."T"', path), 2)
        self.assertEqual(pq.read_table(path).to_pylist()[1]["ID"], Decimal("12345678901234567890123456789012345678"))

    def test_cli_rejects_removed_mode(self):
        with patch("sys.argv", ["main.py", "--source", "postgres", "--connection", "production", "--mode", "local"]), patch("sys.stderr"):
            with self.assertRaises(SystemExit) as error: main.main()
        self.assertEqual(error.exception.code, 2)

    def test_timestamp_tz_expression_only(self):
        connection = MagicMock(); cursor = connection.cursor.return_value.__enter__.return_value
        cursor.fetchall.return_value = [("TS", "TIMESTAMP_TZ(9)"), ("DAY", "DATE"), ("AT", "TIMESTAMP_NTZ(9)")]
        query, _ = build_select_query(connection, '"D"."S"."T"')
        self.assertIn('TO_CHAR("TS"', query); self.assertNotIn('TO_CHAR("AT"', query)
        self.assertIn('"DAY", "AT"', query); self.assertEqual(quote_identifier('A"B'), '"A""B"')

    def test_snowflake_schema_folder_and_same_named_tables(self):
        captured = []; failures = []
        def transfer(client, settings, files, key): captured.append(key)
        with patch.object(sf, "create_run", return_value=(self.now, self.root)), patch.object(sf, "connect_snowflake", return_value=MagicMock()), patch.object(sf, "get_tables", return_value=[("PUBLIC", "USERS"), ("SALES", "USERS")]), patch.object(sf, "save_table_files", return_value=([], 10)), patch.object(sf, "transfer_files", side_effect=transfer):
            count = sf.backup_snowflake({"databases": ["BRONZE"]}, self.obs, self.obs_settings)
        self.assertEqual(count, 0)
        self.assertTrue(captured[0].startswith("Snowflake/BRONZE/PUBLIC/2026/10/19/"))
        self.assertTrue(captured[1].startswith("Snowflake/BRONZE/SALES/2026/10/19/"))

    def test_continue_after_table_failure(self):
        with patch.object(sf, "create_run", return_value=(self.now, self.root)), patch.object(sf, "connect_snowflake", return_value=MagicMock()), patch.object(sf, "get_tables", return_value=[("S", "bad"), ("S", "good")]), patch.object(sf, "save_table_files", side_effect=[RuntimeError("bad"), ([], 1)]), patch.object(sf, "transfer_files") as transfer:
            self.assertEqual(sf.backup_snowflake({"databases": ["DB"]}, self.obs, self.obs_settings), 1)
        transfer.assert_called_once()

    def test_env_supports_multiple_named_hosts_and_accounts(self):
        values = {"PG_PRODUCTION_HOST": "host1", "PG_PRODUCTION_USER": "u", "PG_PRODUCTION_PASSWORD": "p", "PG_PRODUCTION_DATABASES": "db1,db2", "PG_ANALYTICS_HOST": "host2", "PG_ANALYTICS_USER": "u2", "PG_ANALYTICS_PASSWORD": "p2", "PG_ANALYTICS_DATABASES": "db3", "SNOWFLAKE_PRODUCTION_ACCOUNT": "a", "SNOWFLAKE_PRODUCTION_USER": "u", "SNOWFLAKE_PRODUCTION_ROLE": "r", "SNOWFLAKE_PRODUCTION_WAREHOUSE": "w", "SNOWFLAKE_PRODUCTION_PRIVATE_KEY_FILE": "secret/key.p8", "SNOWFLAKE_PRODUCTION_DATABASES": "BRONZE,SILVER"}
        with patch.dict(os.environ, values, clear=True):
            self.assertEqual(config.load_source_config("postgres", "production")["databases"], ["db1", "db2"])
            self.assertEqual(config.load_source_config("postgres", "analytics")["host"], "host2")
            self.assertEqual(config.load_source_config("snowflake", "production")["databases"], ["BRONZE", "SILVER"])

    def test_missing_credentials_error_names_variable_not_value(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(ValueError, "PG_PRODUCTION_HOST"): config.load_source_config("postgres", "production")

    def test_full_dump_without_restore_and_postgres_key_unchanged(self):
        settings = {"host": "10.11.5.4", "port": 5432, "user": "u", "password": "secret-test-value", "databases": ["db"], "pg_dump_path": "/usr/bin/pg_dump"}
        commands = []; keys = []
        def execute(command, settings, env=None):
            commands.append(command)
            self.assertNotIn("secret-test-value", " ".join(str(v) for v in command))
            self.assertEqual(env["PGPASSWORD"], "secret-test-value")
            Path(command[command.index("--file") + 1]).write_bytes(b"dump")
        with patch.object(pg, "create_run", return_value=(self.now, self.root)), patch.object(tools, "run_tool", side_effect=execute), patch.object(pg, "transfer_files", side_effect=lambda c,s,f,k:keys.append(k)):
            self.assertEqual(pg.backup_postgres(settings, self.obs, self.obs_settings), 0)
        self.assertEqual(len(commands), 1)
        self.assertNotIn("--schema", commands[0]); self.assertNotIn("--table", commands[0])
        self.assertTrue(keys[0].startswith("10.11.5.4/db/2026/10/19/"))

    def test_main_selects_sources_and_closes_obs(self):
        for source in ("postgres", "snowflake"):
            for failures in (0, 1):
                client = MagicMock()
                with self.subTest(source=source, failures=failures), patch("sys.argv", ["main.py", "--source", source, "--connection", "production"]), patch.object(main, "setup_logger"), patch.object(main, "BACKUP_DIR", self.root), patch.object(main, "load_source_config", return_value={}), patch.object(main, "load_obs_config", return_value={}), patch.object(main, "connect_obs", return_value=client), patch.object(main, "backup_postgres", return_value=failures) as postgres, patch.object(main, "backup_snowflake", return_value=failures) as snowflake:
                    self.assertEqual(main.main(), 1 if failures else 0)
                    selected = postgres if source == "postgres" else snowflake
                    other = snowflake if source == "postgres" else postgres
                    selected.assert_called_once_with({}, client, {})
                    other.assert_not_called()
                    client.close.assert_called_once()

    def test_snowflake_connection_closed_when_discovery_fails(self):
        connection = MagicMock()
        with patch.object(sf, "create_run", return_value=(self.now, self.root)), patch.object(sf, "connect_snowflake", return_value=connection), patch.object(sf, "get_tables", side_effect=RuntimeError("discovery")):
            self.assertEqual(sf.backup_snowflake({"databases": ["DB"]}, self.obs, self.obs_settings), 1)
        connection.close.assert_called_once()

    def test_all_project_imports_are_at_module_top(self):
        project = Path(__file__).resolve().parents[1]
        files = [project / "main.py"]
        for folder in ("config", "connections", "services", "utils"):
            files.extend((project / folder).glob("*.py"))
        for path in files:
            tree = ast.parse(path.read_text())
            top_imports = {id(node) for node in tree.body if isinstance(node, (ast.Import, ast.ImportFrom))}
            all_imports = {id(node) for node in ast.walk(tree) if isinstance(node, (ast.Import, ast.ImportFrom))}
            self.assertEqual(top_imports, all_imports, str(path))

    def test_native_key_file_configuration_and_failed_connection_cleanup(self):
        key = self.root / "rsa_key.p8"; key.write_text("test key path")
        settings = {"private_key_file": str(key), "private_key_password": "test-passphrase",
                    "account": "a", "user": "u", "role": "r", "warehouse": "w",
                    "connect_timeout": 30, "query_timeout": 3600}
        connection = MagicMock()
        connection.cursor.return_value.__enter__.return_value.fetchall.return_value = [("u", "r", "w")]
        with patch.object(snowflake_module.snowflake.connector, "connect", return_value=connection) as connect:
            self.assertIs(snowflake_module.connect_snowflake(settings), connection)
            self.assertEqual(connect.call_args.kwargs["private_key_file"], str(key))
            self.assertEqual(connect.call_args.kwargs["private_key_file_pwd"], "test-passphrase")
        connection.cursor.return_value.__enter__.return_value.execute.side_effect = RuntimeError("failed session query")
        with patch.object(snowflake_module.snowflake.connector, "connect", return_value=connection):
            with self.assertRaises(RuntimeError): snowflake_module.connect_snowflake(settings)
        connection.close.assert_called_once()



if __name__ == "__main__":
    unittest.main()
