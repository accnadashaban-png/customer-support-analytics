"""Command line: `python -m support_analytics sync` or `python -m support_analytics report`."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from . import metrics
from .api import DEFAULT_DB, sync
from .db import connect
from .sources import JsonSource, SyntheticSource


def main() -> None:
    parser = argparse.ArgumentParser(prog="support_analytics")
    sub = parser.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("sync", help="load data (synthetic by default, or --json export.json)")
    s.add_argument("--json", type=Path)
    r = sub.add_parser("report", help="print the summary for the last N days")
    r.add_argument("--days", type=int, default=30)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    args = parser.parse_args()

    args.db.parent.mkdir(parents=True, exist_ok=True)
    con = connect(args.db)
    if args.cmd == "sync":
        print(json.dumps(sync(con, JsonSource(args.json) if args.json else SyntheticSource())))
    else:
        stats = metrics.conversation_stats(con)
        latest = max(metrics.parse(x.first_message_at) for x in stats)
        from datetime import timedelta

        recent = metrics.in_range(stats, latest - timedelta(days=args.days), None)
        print(json.dumps(metrics.summary(recent, metrics.broadcast_count(con)), indent=2))


if __name__ == "__main__":
    main()
