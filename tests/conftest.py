import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from support_analytics.ingest.sources import SyntheticSource  # noqa: E402
from support_analytics.ingest.store import connect  # noqa: E402
from support_analytics.ingest.sync import sync  # noqa: E402

NOW = datetime(2026, 10, 23, 18, tzinfo=UTC)


@pytest.fixture(scope="session")
def demo_db(tmp_path_factory: pytest.TempPathFactory) -> Path:
    path = tmp_path_factory.mktemp("demo") / "support.db"
    sync(connect(path), SyntheticSource(seed=7, members=450, days=120))
    return path
