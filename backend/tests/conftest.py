"""Tests use a throwaway store: DWIGHT_DB is set before dwight is imported."""
import os
import tempfile
from pathlib import Path

_tmp = Path(tempfile.mkdtemp(prefix="dwight-test-"))
os.environ["DWIGHT_DB"] = str(_tmp / "test.sqlite")
os.environ.setdefault("DWIGHT_FORCE_FIXTURES", "0")
os.environ["DWIGHT_PRICE_MULTIPLIER"] = "1"  # list prices; tests that need x100 monkeypatch config

import pytest  # noqa: E402

from dwight import db  # noqa: E402


@pytest.fixture
def conn(tmp_path):
    """A fresh, empty store per test."""
    c = db.connect(tmp_path / "store.sqlite")
    yield c
    c.close()
