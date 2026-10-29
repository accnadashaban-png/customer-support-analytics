"""Command line.

    python -m support_analytics sync                    # demo data
    python -m support_analytics sync --csv ./my-export  # your own members/messages/subscriptions CSVs
    python -m support_analytics sync --json export.json
    python -m support_analytics sync --file chats.csv --mapping my-mapping.json   # any chat export, your columns
    python -m support_analytics sync --sql my-database.json                       # your database, read-only
    python -m support_analytics report --days 30
    python -m support_analytics eval                    # metric accuracy scenarios + invariants
"""
from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

from support_analytics.analytics import reports
from support_analytics.analytics.contacts import compute_contacts
from support_analytics.core.config import load_config
from support_analytics.core.settings import get_settings
from support_analytics.ingest.sources import CsvSource, JsonSource, SyntheticSource
from support_analytics.ingest.store import connect
from support_analytics.ingest.sync import sync


def main() -> int:
    parser = argparse.ArgumentParser(prog="support_analytics", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("sync", help="load data (safe to run again)")
    src = s.add_mutually_exclusive_group()
    src.add_argument("--csv", type=Path, help="folder with members.csv, messages.csv, subscriptions.csv")
    src.add_argument("--json", type=Path)
    src.add_argument("--file", type=Path, help="any chat export (CSV or JSON); needs --mapping")
    src.add_argument("--sql", type=Path, help="connection file: database url and SELECT queries (read-only)")
    s.add_argument("--mapping", type=Path, help="which of your columns is which (see examples/connect)")
    r = sub.add_parser("report", help="print KPIs for the last N days")
    r.add_argument("--days", type=int, default=30)
    sub.add_parser("eval", help="run the metric evaluation")
    args = parser.parse_args()

    if args.cmd == "eval":
        from support_analytics.eval.runner import main as run_eval

        return run_eval()

    settings = get_settings()
    Path(settings.db_path).parent.mkdir(parents=True, exist_ok=True)
    con = connect(settings.db_path)
    if args.cmd == "sync":
        from support_analytics.ingest.connectors import MappedFileSource, MappingError, SqlSource
        from support_analytics.ingest.sources import Source

        source: Source

        try:
            if args.file:
                if not args.mapping:
                    parser.error("--file needs --mapping")
                source = MappedFileSource(args.file, args.mapping)
            elif args.sql:
                source = SqlSource(args.sql)
            else:
                source = CsvSource(args.csv) if args.csv else JsonSource(args.json) if args.json else SyntheticSource()
            print(json.dumps(sync(con, source)))
        except MappingError as exc:
            print(f"error: {exc}")
            return 2
        return 0
    cfg = load_config(settings.config_path)
    contacts = compute_contacts(con, cfg, now=datetime.now(UTC))
    latest = max((c.first_message_at for c in contacts), default=None)
    if latest:
        from datetime import timedelta

        from support_analytics.analytics.contacts import parse

        contacts = reports.in_range(contacts, parse(latest) - timedelta(days=args.days), None)
    print(json.dumps(reports.kpis(contacts), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
