import argparse
import sys

from config.settings import load_obs_config, load_source_config


def main():
    parser = argparse.ArgumentParser(description="Step 1: validate backup settings only")
    parser.add_argument("--source", choices=("postgres", "snowflake"), required=True)
    parser.add_argument("--connection", required=True)
    args = parser.parse_args()
    try:
        print(f"[START] Reading {args.source} settings", flush=True)
        source_config = load_source_config(args.source, args.connection)
        print(f"[OK] Connection selected: {args.connection}")
        print(f"[OK] Databases: {', '.join(source_config['databases'])}")
        print("[START] Reading OBS settings")
        obs_config = load_obs_config()
        print(f"[OK] OBS bucket: {obs_config['bucket']}")
        print("[DONE] Settings structure validated. No network connections or backups performed.")
        print("Placeholder values are examples; credentials and key file have not been verified.")
        return 0
    except (ValueError, OSError) as error:
        print(f"[ERROR] {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
