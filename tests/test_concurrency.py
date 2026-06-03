"""Phase 3: rate limiter, ledger locking, jobs resolution, concurrent scan."""

from __future__ import annotations

import threading
import time

from babelfish import Language

import fetch_srt_subtitles as fss


def test_rate_limiter_disabled_is_instant():
    rl = fss.RateLimiter(0.0)
    start = time.monotonic()
    for _ in range(5):
        rl.wait()
    assert time.monotonic() - start < 0.05


def test_rate_limiter_paces_calls():
    rl = fss.RateLimiter(0.02)
    start = time.monotonic()
    for _ in range(3):
        rl.wait()
    # 3 calls at >=0.02s spacing -> at least ~0.04s total (first is free)
    assert time.monotonic() - start >= 0.03


def test_jobs_coercion():
    assert fss._coerce_jobs(8) == 8
    assert fss._coerce_jobs(0) == 1  # floored to 1
    assert fss._coerce_jobs(-3) == 1


def test_jobs_default_and_flag():
    rt = fss.resolve_runtime_options(fss.parse_args(["."]), {})
    assert rt["jobs"] == 4
    rt2 = fss.resolve_runtime_options(fss.parse_args(["-j", "8", "."]), {})
    assert rt2["jobs"] == 8


def test_ledger_concurrent_records_are_consistent(tmp_path):
    """Hammer the ledger from many threads; no lost updates / no crash."""
    led = fss.ProgressLedger(tmp_path / "p.json", recheck_after_seconds=10_000)
    videos = []
    for i in range(20):
        v = tmp_path / f"v{i}.mkv"
        v.write_text("x")
        videos.append(v)

    barrier = threading.Barrier(8)

    def worker(start):
        barrier.wait()
        for i in range(start, len(videos)):
            led.record(videos[i], "sv", "not_found")

    threads = [threading.Thread(target=worker, args=(s,)) for s in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # Every video must be recorded and skippable; no exception under contention.
    for v in videos:
        assert led.should_skip(v, "sv") is True


def test_apply_result_updates_stats():
    ui = fss.StatusUI(enabled=False)
    stats = fss.RunStats()
    fss._apply_result(ui, stats, __as_path("a.mkv"), "downloaded", Language.fromietf("sv"), "prov")
    fss._apply_result(ui, stats, __as_path("b.mkv"), "not_found", None, None)
    fss._apply_result(ui, stats, __as_path("c.mkv"), "exists", None, None)
    fss._apply_result(ui, stats, __as_path("d.mkv"), "skipped_recent", None, None)
    fss._apply_result(ui, stats, __as_path("e.mkv"), "failed", None, None)
    assert stats.downloaded == 1
    assert stats.not_found == 1
    assert stats.skipped_existing == 1
    assert stats.skipped_recent == 1
    assert stats.failed == 1
    assert stats.provider_downloads["prov"] == 1


def __as_path(name):
    from pathlib import Path

    return Path(name)


def test_concurrent_scan_processes_all(monkeypatch, tmp_path):
    """End-to-end concurrent main() over several files with mocked network."""
    for i in range(7):
        (tmp_path / f"Show.S01E0{i}.mkv").touch()
    monkeypatch.setattr(fss, "scan_video", lambda p: _FakeV(p))
    monkeypatch.setattr(fss, "refine", lambda video, **k: video)
    monkeypatch.setattr(fss, "try_download_for_language", lambda *a, **k: ("not_found", None))
    code = fss.main(["-j", "4", "-l", "sv", str(tmp_path)])
    assert code == 0  # not_found is not a failure


class _FakeV:
    def __init__(self, path):
        self.name = str(path)
        self.series = None
        self.season = 1
        self.episode = 1
        self.title = "Show"
        self.year = None
