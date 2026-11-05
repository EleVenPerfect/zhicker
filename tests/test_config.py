import os
import stat

import pytest

from app.config import config_from_env, ensure_data_dirs


def test_ensure_data_dirs_applies_mode(tmp_path):
    data_dir = tmp_path / "data"
    ensure_data_dirs(str(data_dir), 0o777)

    paths = [data_dir] + [
        data_dir / name for name in ("epubs", "archives", "archive_failed", "work")
    ]
    for path in paths:
        assert stat.S_IMODE(os.stat(path).st_mode) == 0o777


def test_data_dir_mode_from_env(monkeypatch):
    monkeypatch.setenv("DATA_DIR_MODE", "0750")
    assert config_from_env()["DATA_DIR_MODE"] == 0o750

    monkeypatch.setenv("DATA_DIR_MODE", "abc")
    with pytest.raises(RuntimeError):
        config_from_env()
