"""Cache configuration: writability fallback and corrupt-dbm repair."""

from __future__ import annotations

import dbm

import fetch_srt_subtitles as fss


def test_configure_cache_uses_root_when_writable(tmp_path):
    cache_dir = fss.configure_cache(tmp_path)
    assert cache_dir == tmp_path / ".subtitle-cache"
    assert cache_dir.exists()


def test_configure_cache_falls_back_when_root_unwritable(tmp_path, monkeypatch):
    # Make only the root candidate look unwritable; the temp fallback stays usable.
    root_cache = tmp_path / ".subtitle-cache"

    real_writable = fss._dir_is_writable

    def fake_writable(directory):
        if directory == root_cache:
            return False
        return real_writable(directory)

    monkeypatch.setattr(fss, "_dir_is_writable", fake_writable)
    cache_dir = fss.configure_cache(tmp_path)
    assert cache_dir != root_cache  # fell back to the temp dir


def test_configure_cache_memory_last_resort(tmp_path, monkeypatch):
    # Nothing is writable anywhere -> must not raise (memory backend).
    monkeypatch.setattr(fss, "_dir_is_writable", lambda directory: False)
    cache_dir = fss.configure_cache(tmp_path)
    assert cache_dir is not None


def test_repair_dbm_cache_removes_corrupt(tmp_path):
    db_path = tmp_path / "cache.dbm"
    db_path.write_bytes(b"this is not a valid dbm file")
    fss._repair_dbm_cache(db_path)
    # A fresh open must now succeed (corrupt file was cleared).
    handle = dbm.open(str(db_path), "c")
    handle.close()
