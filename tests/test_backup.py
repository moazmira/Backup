import json
import os
import tempfile
import unittest
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

import pyarrow as pa
import pyarrow.parquet as pq
import main
from config import settings as config
from services import postgres_backup as pg
from services import snowflake_backup as sf
from services.snowflake_export import build_export_schema, export_ddl, export_parquet
from storage.obs import object_exists, transfer_files, upload_verified
from utils.database import select_data
from utils.files import create_run, path_component


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
        self.root = Path(self.temp.name); self.log = MagicMock(); self.obs = FakeObs()
        self.obs_settings = {"bucket": "bucket", "attempts": 1, "multipart_threshold_mb": 100}
        self.now = datetime(2026, 10, 19, 12, tzinfo=ZoneInfo("Africa/Cairo"))

    def files(self):
        paths = [self.root / "T.sql", self.root / "T.parquet"]
        paths[0].write_text("CREATE TABLE T (ID NUMBER);"); paths[1].write_bytes(b"parquet-test")
        return paths

    def test_upload_pair_delete_after_both_and_marker_verified(self):
        files = self.files()
        result = transfer_files(self.obs, self.obs_settings, files, "base/T", self.log)
        self.assertTrue(all(not f.exists() for f in files))
        self.assertEqual(len(json.loads(self.obs.objects["base/T.complete.json"])["files"]), 2)
        self.assertEqual(result["completion"]["key"], "base/T.complete.json")

    def test_pair_failure_keeps_both_files(self):
        files = self.files(); self.obs.fail_key = "base/T.parquet"
        with self.assertRaises(RuntimeError): transfer_files(self.obs, self.obs_settings, files, "base/T", self.log)
        self.assertTrue(all(f.exists() for f in files)); self.assertNotIn("base/T.complete.json", self.obs.objects)

    def test_marker_failure_keeps_original_files(self):
        files = self.files(); self.obs.fail_key = "base/T.complete.json"
        with self.assertRaises(RuntimeError): transfer_files(self.obs, self.obs_settings, files, "base/T", self.log)
        self.assertTrue(all(f.exists() for f in files))

    def test_corrupt_download_keeps_files_and_cleans_verification(self):
        files = self.files(); self.obs.corrupt_download = True
        with self.assertRaisesRegex(RuntimeError, "SHA-256"): transfer_files(self.obs, self.obs_settings, files, "base/T", self.log)
        self.assertTrue(all(f.exists() for f in files)); self.assertEqual(list(self.root.glob("*.verify")), [])

    def test_suffix_avoids_existing_pair_and_marker(self):
        self.obs.objects.update({"base/T.sql": b"old", "base/T_2.complete.json": b"marker"})
        files = self.files()
        result = transfer_files(self.obs, self.obs_settings, files, "base/T", self.log, True)
        self.assertEqual(result["files"][0]["key"], "base/T_3.sql")
        self.assertTrue(all(f.exists() for f in files)); self.assertEqual(self.obs.objects["base/T.sql"], b"old")

    def test_denied_metadata_is_not_missing(self):
        self.obs.getObjectMetadata = lambda *args: response(403)
        with self.assertRaises(RuntimeError): object_exists(self.obs, "bucket", "key")

    def test_upload_refuses_existing_object(self):
        path = self.files()[0]; self.obs.objects["existing"] = b"old"
        with self.assertRaises(FileExistsError): upload_verified(self.obs, self.obs_settings, "existing", path, self.log)
        self.assertEqual(self.obs.objects["existing"], b"old")

    def test_multipart_produces_single_object(self):
        path = self.root / "large.dump"; path.write_bytes(b"a" * 1048576)
        upload_verified(self.obs, {**self.obs_settings, "multipart_threshold_mb": 1}, "large", path, self.log)
        self.assertIn(("multipart", "large"), self.obs.calls); self.assertEqual(list(self.obs.objects), ["large"])

    def test_verification_retry_does_not_reupload(self):
        from storage import obs as module
        with patch.object(module, "verify_upload", side_effect=[RuntimeError("timeout"), None]) as verify, patch.object(module.time, "sleep"):
            upload_verified(self.obs, {**self.obs_settings, "attempts": 2}, "file", self.files()[0], self.log)
            self.assertEqual(verify.call_count, 2)
        self.assertEqual(self.obs.calls, [("put", "file")])

    def test_actual_parquet_decimal_unicode_null_and_metadata(self):
        columns = [("ID", "NUMBER(38,0)", "COLUMN", "N"), ("NAME", "VARCHAR(200)", "COLUMN", "Y"), ("TS", "TIMESTAMP_NTZ(9)", "COLUMN", "Y"), ("DATA", "VARIANT", "COLUMN", "Y")]
        schema, expressions = build_export_schema(columns)
        number = Decimal("12345678901234567890123456789012345678")
        batch = pa.Table.from_pylist([{"ID": number, "NAME": "عربي", "TS": "1500-01-01T00:00:00.123456789", "DATA": None}], schema=schema)
        connection = MagicMock(); cursor = connection.cursor.return_value.__enter__.return_value
        cursor.fetchall.return_value = columns; cursor.fetch_arrow_batches.return_value = iter([None, batch, batch])
        path = self.root / "data.parquet"
        self.assertEqual(export_parquet(connection, '"DB"."S"."T"', path, self.log), 2)
        result = pq.read_table(path)
        self.assertEqual(result.to_pylist()[0]["ID"], number); self.assertEqual(result.to_pylist()[0]["NAME"], "عربي")
        self.assertIsNone(result.to_pylist()[0]["DATA"]); self.assertIn(b"snowflake_columns", result.schema.metadata)
        self.assertIn("TO_CHAR", expressions[2]); self.assertIn("TO_JSON", expressions[3])

    def test_empty_table(self):
        connection = MagicMock(); cursor = connection.cursor.return_value.__enter__.return_value
        cursor.fetchall.return_value = [("ID", "NUMBER(10,0)", "COLUMN", "Y")]; cursor.fetch_arrow_batches.return_value = iter([])
        path = self.root / "empty.parquet"
        self.assertEqual(export_parquet(connection, '"D"."S"."T"', path, self.log), 0)
        self.assertEqual(pq.ParquetFile(path).schema_arrow.names, ["ID"])

    def test_batch_error_removes_partial(self):
        connection = MagicMock(); cursor = connection.cursor.return_value.__enter__.return_value
        cursor.fetchall.return_value = [("ID", "NUMBER(10,0)", "COLUMN", "Y")]
        schema, _ = build_export_schema(cursor.fetchall.return_value)
        def batches():
            yield pa.Table.from_pylist([{"ID": Decimal(1)}], schema=schema)
            raise RuntimeError("download failed")
        cursor.fetch_arrow_batches.return_value = batches(); path = self.root / "broken.parquet"
        with self.assertRaises(RuntimeError): export_parquet(connection, '"D"."S"."T"', path, self.log)
        self.assertFalse(path.exists()); self.assertFalse(path.with_suffix(".parquet.partial").exists())

    def test_unsupported_type(self):
        with self.assertRaisesRegex(ValueError, "GEOGRAPHY"): build_export_schema([("G", "GEOGRAPHY", "COLUMN", "Y")])

    def test_sql_definition_saved_not_executed_and_no_overwrite(self):
        connection = MagicMock(); cursor = connection.cursor.return_value.__enter__.return_value
        cursor.fetchall.return_value = [("CREATE TABLE T (ID NUMBER);",)]; path = self.root / "T.sql"
        export_ddl(connection, '"DB"."S"."T"', path, self.log)
        self.assertEqual(cursor.execute.call_args.args, ("SELECT GET_DDL('TABLE', %s, TRUE)", ('"DB"."S"."T"',)))
        with self.assertRaises(FileExistsError): export_ddl(connection, '"DB"."S"."T"', path, self.log)

    def test_select_closes_cursor_not_connection(self):
        connection = MagicMock(); cursor = connection.cursor.return_value.__enter__.return_value; cursor.fetchall.return_value = [(1,)]
        self.assertEqual(select_data(connection, "SELECT %s", (1,)), [(1,)])
        connection.cursor.return_value.__exit__.assert_called_once(); connection.close.assert_not_called()

    def test_snowflake_continues_after_table_failure(self):
        summary = {"units": []}
        with patch.object(sf, "list_tables", return_value=[("S", "bad"), ("S", "good")]), patch.object(sf, "backup_table", side_effect=[RuntimeError("bad"), (self.files(), 3)]):
            sf.backup_snowflake(MagicMock(), {"databases": ["DB"]}, None, None, self.root, self.now, summary, self.log, "local", False)
        self.assertEqual([u["status"] for u in summary["units"]], ["failed", "local_ready"])

    def test_database_identifier_quoted(self):
        connection = MagicMock(); connection.cursor.return_value.__enter__.return_value.fetchall.return_value = []
        sf.list_tables(connection, 'A"B', self.log)
        self.assertIn('"A""B".INFORMATION_SCHEMA.TABLES', connection.cursor.return_value.__enter__.return_value.execute.call_args.args[0])

    def test_full_database_dump_and_archive_validation_command(self):
        settings = {"host": "host", "port": 5432, "user": "user", "password": "secret"}; connection = MagicMock(); commands = []
        def execute(command, settings, logger, env=None):
            commands.append(command)
            if "--format=custom" in command:
                self.assertNotIn("secret", " ".join(str(x) for x in command)); self.assertEqual(env["PGPASSWORD"], "secret")
                Path(command[command.index("--file") + 1]).write_bytes(b"archive")
        with patch.object(pg, "connect_postgres", return_value=connection), patch.object(pg, "select_data", return_value=[("180003",)]), patch.object(pg, "find_pg_tools", return_value=(Path("pg_dump"), Path("pg_restore"))), patch.object(pg, "run_tool", side_effect=execute):
            path = pg.create_dump(settings, "postgres", self.root, self.now, self.log)
        self.assertTrue(path.is_file()); connection.close.assert_called_once()
        self.assertIn("--format=custom", commands[0]); self.assertNotIn("--schema", commands[0]); self.assertNotIn("--table", commands[0])
        self.assertEqual(commands[1][0], Path("pg_restore")); self.assertIn(os.devnull, commands[1])

    def test_invalid_dump_removes_partial(self):
        settings = {"host": "host", "port": 5432, "user": "u", "password": "secret"}
        def execute(command, *args):
            if "--format=custom" in command: Path(command[command.index("--file") + 1]).write_bytes(b"bad")
            else: raise RuntimeError("corrupt archive")
        with patch.object(pg, "connect_postgres", return_value=MagicMock()), patch.object(pg, "select_data", return_value=[("180003",)]), patch.object(pg, "find_pg_tools", return_value=(Path("pg_dump"), Path("pg_restore"))), patch.object(pg, "run_tool", side_effect=execute):
            with self.assertRaises(RuntimeError): pg.create_dump(settings, "postgres", self.root, self.now, self.log)
        self.assertEqual(list(self.root.rglob("*.partial")), []); self.assertEqual(list(self.root.rglob("*.dump")), [])

    def test_postgres_continues_after_database_failure(self):
        summary = {"units": []}; path = self.root / "good.dump"; path.write_bytes(b"data")
        with patch.object(pg, "create_dump", side_effect=[RuntimeError("denied"), path]):
            pg.backup_postgres({"databases": ["bad", "good"]}, None, None, self.root, self.now, summary, self.log, "local", False)
        self.assertEqual([u["status"] for u in summary["units"]], ["failed", "local_ready"])

    def test_mismatched_pg_client_rejected(self):
        executable = self.root / "pg_dump"; executable.touch()
        with patch.object(pg, "check_tool_version", return_value=16), patch.dict(os.environ, {"PG_DUMP_PATH": str(executable)}):
            with self.assertRaisesRegex(RuntimeError, "PostgreSQL 18"): pg.find_pg_tools({}, 18, self.log)

    def test_run_failure_summary_and_connection_cleanup(self):
        import connections.snowflake as connector
        directory = self.root / "run"; directory.mkdir(); connection = MagicMock()
        args = SimpleNamespace(source="snowflake", connection="production", mode="local", keep_local=False)
        def fail(*arguments): arguments[6]["units"].append({"status": "failed"})
        with patch.object(main, "create_run", return_value=(self.now, directory)), patch.object(connector, "connect_snowflake", return_value=connection), patch.object(sf, "backup_snowflake", side_effect=fail):
            self.assertEqual(main.run_backup(args, {}, None, None, self.log), 1)
        self.assertEqual(json.loads((directory / "summary.json").read_text())["status"], "failed"); connection.close.assert_called_once()

    def test_unique_runs_and_path_encoding(self):
        import utils.files as module
        with patch.object(module, "BACKUP_DIR", self.root): self.assertNotEqual(create_run("snowflake")[1], create_run("snowflake")[1])
        self.assertEqual(path_component("../x"), "%2E%2E%2Fx")

    def test_configuration_defaults_and_bad_port(self):
        data = {"production": {"host": "host", "port": 5432, "user": "u", "password": "p", "databases": ["db"]}}
        (self.root / "postgres.json").write_text(json.dumps(data))
        with patch.object(config, "SECRET_DIR", self.root):
            self.assertEqual(config.load_source_config("postgres", "production")["dump_timeout"], 21600)
            data["production"]["port"] = True; (self.root / "postgres.json").write_text(json.dumps(data))
            with self.assertRaises(ValueError): config.load_source_config("postgres", "production")

    def test_complete_snowflake_cli_with_real_files_and_simulated_services(self):
        import connections.snowflake as connector
        import utils.files as files_module
        secret = self.root / "secret"; secret.mkdir()
        secret.joinpath("snowflake.json").write_text(json.dumps({"production": {
            "account": "account", "user": "user", "warehouse": "wh", "role": "role",
            "private_key_file": "unused-in-test.p8", "databases": ["DB"]}}))
        secret.joinpath("obs.json").write_text(json.dumps({"endpoint": "https://example.test", "bucket": "bucket",
                                                        "access_key_id": "ak", "secret_access_key": "sk"}))
        columns = [("ID", "NUMBER(10,0)", "COLUMN", "N"), ("NAME", "VARCHAR(20)", "COLUMN", "Y")]
        schema, _ = build_export_schema(columns)
        batch = pa.Table.from_pylist([{"ID": Decimal(1), "NAME": "Arabic عربي"}], schema=schema)
        class Cursor:
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def execute(self, query, params=None): self.query = query
            def fetchall(self):
                if "INFORMATION_SCHEMA.TABLES" in self.query: return [("PUBLIC", "USERS")]
                if "GET_DDL" in self.query: return [("CREATE TABLE DB.PUBLIC.USERS (ID NUMBER(10,0), NAME VARCHAR(20));",)]
                if self.query.startswith("DESC TABLE"): return columns
                raise AssertionError(self.query)
            def fetch_arrow_batches(self): return iter([batch])
        connection = MagicMock(); connection.cursor.side_effect = Cursor
        self.obs.close = MagicMock()
        output = self.root / "output"
        with patch.object(config, "SECRET_DIR", secret), patch.object(main, "BACKUP_DIR", output), patch.object(files_module, "BACKUP_DIR", output), patch.object(main, "setup_logger", return_value=self.log), patch.object(connector, "connect_snowflake", return_value=connection), patch.object(main, "connect_obs", return_value=self.obs), patch("sys.argv", ["main.py", "--source", "snowflake", "--connection", "production"]):
            self.assertEqual(main.main(), 0)
        summaries = list(output.rglob("summary.json")); self.assertEqual(len(summaries), 1)
        summary = json.loads(summaries[0].read_text())
        self.assertEqual(summary["status"], "complete"); self.assertEqual(summary["units"][0]["rows"], 1)
        self.assertEqual(len(self.obs.objects), 3)
        self.assertEqual(list(output.rglob("*.parquet")), []); self.assertEqual(list(output.rglob("*.sql")), [])
        connection.close.assert_called_once(); self.obs.close.assert_called_once()
        key = next(key for key in self.obs.objects if key.endswith(".parquet"))
        from io import BytesIO
        self.assertEqual(pq.read_table(BytesIO(self.obs.objects[key])).to_pylist()[0]["NAME"], "Arabic عربي")

    def test_local_mode_never_reads_obs_credentials(self):
        with patch.object(main, "setup_logger", return_value=self.log), patch.object(main, "load_source_config", return_value={}), patch.object(main, "BACKUP_DIR", self.root), patch.object(main, "connect_obs") as connect, patch.object(main, "load_obs_config") as load, patch.object(main, "run_backup", return_value=0), patch("sys.argv", ["main.py", "--source", "postgres", "--connection", "production", "--mode", "local"]):
            self.assertEqual(main.main(), 0); connect.assert_not_called(); load.assert_not_called()


if __name__ == "__main__":
    unittest.main()
