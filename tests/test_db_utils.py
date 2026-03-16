from __future__ import annotations

import pytest

from shinylims.integrations import db_utils


def test_get_db_path_caches_pin_failure_until_refresh(monkeypatch):
    calls = {"count": 0}

    class FakeBoard:
        def pin_download(self, name):
            calls["count"] += 1
            raise RuntimeError("Cannot check version, since pin vi2172/clarity_lims_sqlite does not exist")

    monkeypatch.setattr(db_utils, "board_connect", lambda **kwargs: FakeBoard())
    monkeypatch.setattr(db_utils, "_DB_PATH", None)
    monkeypatch.setattr(db_utils, "_DB_PATH_ERROR", None)

    with pytest.raises(RuntimeError, match="does not exist"):
        db_utils.get_db_path()

    with pytest.raises(RuntimeError, match="does not exist"):
        db_utils.get_db_path()

    assert calls["count"] == 1

    db_utils.refresh_db_connection()

    with pytest.raises(RuntimeError, match="does not exist"):
        db_utils.get_db_path()

    assert calls["count"] == 2
