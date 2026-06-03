"""Download/fetch logic: multi-episode parsing, provider-error handling, outcomes."""

from __future__ import annotations

from pathlib import Path

import pytest
from babelfish import Language
from requests.exceptions import ConnectionError as RequestsConnectionError
from subliminal.exceptions import ProviderError

import fetch_srt_subtitles as fss

# --- _first_int / multi-episode (bug #3) -----------------------------------


def test_first_int_handles_list_scalar_none():
    assert fss._first_int([1, 2]) == 1
    assert fss._first_int(3) == 3
    assert fss._first_int(None) is None
    assert fss._first_int([]) is None


def test_build_keyword_query_video_multi_episode(fake_video):
    captured = {}

    class V(fake_video):
        @staticmethod
        def fromname(name):
            captured["name"] = name
            return "QUERY_VIDEO"

    v = V(series="Pack", season=1, episode=[1, 2], name="Pack.S01E01E02.mkv")
    result = fss.build_keyword_query_video(v)
    assert result == "QUERY_VIDEO"
    assert captured["name"].startswith("Pack S01E01")  # no TypeError on list episode


def test_build_keyword_query_video_no_fromname_returns_none(fake_video):
    # FakeVideo has no fromname -> guarded None
    assert fss.build_keyword_query_video(fake_video()) is None


# --- try_download_for_language outcomes (bug #4 family) --------------------


def _lang():
    return Language.fromietf("sv")


def test_try_download_downloaded(monkeypatch, fake_video, fake_subtitle):
    v = fake_video()
    monkeypatch.setattr(fss, "download_best_subtitles", lambda *a, **k: {v: [fake_subtitle("podnapisi")]})
    monkeypatch.setattr(fss, "save_subtitles", lambda *a, **k: [fake_subtitle()])
    status, provider = fss.try_download_for_language(
        v, _lang(), ["podnapisi"], {}, "utf-8", False, query_label="full"
    )
    assert (status, provider) == ("downloaded", "podnapisi")


def test_try_download_not_found(monkeypatch, fake_video):
    v = fake_video()
    monkeypatch.setattr(fss, "download_best_subtitles", lambda *a, **k: {})
    status, provider = fss.try_download_for_language(
        v, _lang(), ["podnapisi"], {}, "utf-8", False, query_label="full"
    )
    assert status == "not_found"


@pytest.mark.parametrize("exc", [ProviderError("x"), RequestsConnectionError("x"), RuntimeError("x")])
def test_try_download_errors_return_failed(monkeypatch, fake_video, exc):
    v = fake_video()

    def boom(*a, **k):
        raise exc

    monkeypatch.setattr(fss, "download_best_subtitles", boom)
    status, provider = fss.try_download_for_language(
        v, _lang(), ["podnapisi"], {}, "utf-8", False, query_label="full"
    )
    assert status == "failed"


def test_try_download_save_oserror_is_failed(monkeypatch, fake_video, fake_subtitle):
    v = fake_video()
    monkeypatch.setattr(fss, "download_best_subtitles", lambda *a, **k: {v: [fake_subtitle()]})

    def bad_save(*a, **k):
        raise OSError("disk full")

    monkeypatch.setattr(fss, "save_subtitles", bad_save)
    status, _ = fss.try_download_for_language(
        v, _lang(), ["podnapisi"], {}, "utf-8", False, query_label="full"
    )
    assert status == "failed"


def test_try_download_no_providers():
    status, provider = fss.try_download_for_language(
        object(), _lang(), [], {}, "utf-8", False, query_label="full"
    )
    assert (status, provider) == ("not_found", None)


# --- fetch_subtitle_for_video outcomes + ledger ----------------------------


def _touch_video(tmp_path: Path) -> Path:
    vid = tmp_path / "Some.Show.S01E01.mkv"
    vid.touch()
    return vid


def test_fetch_exists_short_circuits(monkeypatch, tmp_path, fake_video):
    vid = _touch_video(tmp_path)
    (tmp_path / "Some.Show.S01E01.sv.srt").touch()
    monkeypatch.setattr(fss, "scan_video", lambda p: fake_video(name=vid.name))
    led = fss.ProgressLedger(None, recheck_after_seconds=10_000)
    result, lang, _ = fss.fetch_subtitle_for_video(
        vid, [Language.fromietf("sv")], ["podnapisi"], {}, "utf-8", False, ledger=led
    )
    assert result == "exists"


def test_fetch_downloaded_records_ledger(monkeypatch, tmp_path, fake_video):
    vid = _touch_video(tmp_path)
    monkeypatch.setattr(fss, "scan_video", lambda p: fake_video(name=vid.name))
    monkeypatch.setattr(fss, "try_download_for_language", lambda *a, **k: ("downloaded", "prov"))
    led = fss.ProgressLedger(None, recheck_after_seconds=10_000)
    result, lang, provider = fss.fetch_subtitle_for_video(
        vid, [Language.fromietf("sv")], ["podnapisi"], {}, "utf-8", False, ledger=led
    )
    assert result == "downloaded"
    assert led.should_skip(vid, "sv") is True  # recorded as downloaded


def test_fetch_failed_not_cached(monkeypatch, tmp_path, fake_video):
    vid = _touch_video(tmp_path)
    monkeypatch.setattr(fss, "scan_video", lambda p: fake_video(name=vid.name))
    monkeypatch.setattr(fss, "try_download_for_language", lambda *a, **k: ("failed", None))
    led = fss.ProgressLedger(None, recheck_after_seconds=10_000)
    result, *_ = fss.fetch_subtitle_for_video(
        vid, [Language.fromietf("sv")], ["podnapisi"], {}, "utf-8", False, ledger=led
    )
    assert result == "failed"
    assert led.should_skip(vid, "sv") is False  # failures are retried


def test_fetch_not_found_records(monkeypatch, tmp_path, fake_video):
    vid = _touch_video(tmp_path)
    monkeypatch.setattr(fss, "scan_video", lambda p: fake_video(name=vid.name))
    monkeypatch.setattr(fss, "try_download_for_language", lambda *a, **k: ("not_found", None))
    led = fss.ProgressLedger(None, recheck_after_seconds=10_000)
    result, *_ = fss.fetch_subtitle_for_video(
        vid, [Language.fromietf("sv")], ["podnapisi"], {}, "utf-8", False, ledger=led
    )
    assert result == "not_found"
    assert led.should_skip(vid, "sv") is True


def test_fetch_skipped_recent(monkeypatch, tmp_path, fake_video):
    vid = _touch_video(tmp_path)
    monkeypatch.setattr(fss, "scan_video", lambda p: fake_video(name=vid.name))
    called = {"n": 0}

    def counting(*a, **k):
        called["n"] += 1
        return ("not_found", None)

    monkeypatch.setattr(fss, "try_download_for_language", counting)
    led = fss.ProgressLedger(None, recheck_after_seconds=10_000)
    led.record(vid, "sv", "not_found")  # pre-seed
    result, *_ = fss.fetch_subtitle_for_video(
        vid, [Language.fromietf("sv")], ["podnapisi"], {}, "utf-8", False, ledger=led
    )
    assert result == "skipped_recent"
    assert called["n"] == 0  # never searched


def test_fetch_scan_failure_returns_failed(monkeypatch, tmp_path):
    vid = _touch_video(tmp_path)

    def boom(p):
        raise RuntimeError("scan exploded")

    monkeypatch.setattr(fss, "scan_video", boom)
    result, *_ = fss.fetch_subtitle_for_video(
        vid, [Language.fromietf("sv")], ["podnapisi"], {}, "utf-8", False
    )
    assert result == "failed"
