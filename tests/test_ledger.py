"""ProgressLedger: TTL skipping, staleness invalidation, reset, persistence."""

from __future__ import annotations

import os
import time
from pathlib import Path

import fetch_srt_subtitles as fss


def _make_video(tmp_path: Path, name: str = "v.mkv") -> Path:
    vid = tmp_path / name
    vid.write_text("x")
    return vid


def test_empty_ledger_does_not_skip(tmp_path):
    led = fss.ProgressLedger(tmp_path / "p.json", recheck_after_seconds=10_000)
    assert led.should_skip(_make_video(tmp_path), "sv") is False


def test_not_found_skipped_within_ttl(tmp_path):
    vid = _make_video(tmp_path)
    led = fss.ProgressLedger(tmp_path / "p.json", recheck_after_seconds=10_000)
    led.record(vid, "sv", "not_found")
    assert led.should_skip(vid, "sv") is True


def test_not_found_expires_after_ttl(tmp_path):
    vid = _make_video(tmp_path)
    led = fss.ProgressLedger(tmp_path / "p.json", recheck_after_seconds=0)
    led.record(vid, "sv", "not_found")
    assert led.should_skip(vid, "sv") is False


def test_downloaded_always_skipped(tmp_path):
    vid = _make_video(tmp_path)
    led = fss.ProgressLedger(tmp_path / "p.json", recheck_after_seconds=0)
    led.record(vid, "en", "downloaded")
    assert led.should_skip(vid, "en") is True


def test_failed_never_skipped(tmp_path):
    vid = _make_video(tmp_path)
    led = fss.ProgressLedger(tmp_path / "p.json", recheck_after_seconds=10_000)
    led.record(vid, "sv", "failed")
    assert led.should_skip(vid, "sv") is False


def test_persistence_round_trip(tmp_path):
    vid = _make_video(tmp_path)
    path = tmp_path / "p.json"
    led = fss.ProgressLedger(path, recheck_after_seconds=10_000)
    led.record(vid, "sv", "not_found")
    led.save(force=True)
    assert path.exists()
    reloaded = fss.ProgressLedger(path, recheck_after_seconds=10_000)
    assert reloaded.should_skip(vid, "sv") is True


def test_stale_entry_invalidated_on_file_change(tmp_path):
    vid = _make_video(tmp_path)
    led = fss.ProgressLedger(tmp_path / "p.json", recheck_after_seconds=10_000)
    led.record(vid, "sv", "not_found")
    time.sleep(0.01)
    vid.write_text("much longer changed content")
    os.utime(vid, (time.time() + 5, time.time() + 5))
    assert led.should_skip(vid, "sv") is False


def test_reset_discards_existing_ledger(tmp_path):
    vid = _make_video(tmp_path)
    path = tmp_path / "p.json"
    seed = fss.ProgressLedger(path, recheck_after_seconds=10_000)
    seed.record(vid, "sv", "not_found")
    seed.save(force=True)
    assert path.exists()
    # --clean: reset=True wipes the file and starts empty
    cleaned = fss.ProgressLedger(path, recheck_after_seconds=10_000, reset=True)
    assert cleaned.should_skip(vid, "sv") is False
    assert not path.exists()


def test_path_none_is_inert(tmp_path):
    vid = _make_video(tmp_path)
    led = fss.ProgressLedger(None, recheck_after_seconds=10_000)
    led.record(vid, "sv", "not_found")
    led.save(force=True)  # no-op, must not raise
    assert led.should_skip(vid, "sv") is True  # in-memory still works
