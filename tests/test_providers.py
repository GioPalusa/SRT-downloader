"""Phase 2: language-aware provider ordering, refiner wiring, coverage hint."""

from __future__ import annotations

import fetch_srt_subtitles as fss

LANG_MAP = {
    "subtitulamos": frozenset({"es"}),
    "subtis": frozenset({"es"}),
    "gestdown": frozenset({"en"}),
    "opensubtitlescom": frozenset({"en", "sv", "es", "de"}),
    # "tvsubtitles" intentionally absent -> unknown (fail-open)
}


def test_order_drops_unsupported_for_swedish():
    ordered = fss.order_providers_for_language(
        ["subtitulamos", "gestdown", "opensubtitlescom", "tvsubtitles"],
        "sv",
        language_map=LANG_MAP,
    )
    # opensubtitlescom supports sv -> first; tvsubtitles unknown -> kept;
    # subtitulamos (es only) dropped; gestdown (en only) dropped.
    assert ordered[0] == "opensubtitlescom"
    assert "tvsubtitles" in ordered
    assert "subtitulamos" not in ordered
    assert "gestdown" not in ordered


def test_order_keeps_unsupported_when_not_dropping():
    ordered = fss.order_providers_for_language(
        ["subtitulamos", "opensubtitlescom"], "sv", language_map=LANG_MAP, drop_unsupported=False
    )
    assert ordered == ["opensubtitlescom", "subtitulamos"]


def test_order_never_returns_empty():
    # All known-and-unsupported -> would be empty -> fall back to originals.
    ordered = fss.order_providers_for_language(["subtitulamos", "subtis"], "sv", language_map=LANG_MAP)
    assert ordered == ["subtitulamos", "subtis"]


def test_order_preserves_order_for_english():
    ordered = fss.order_providers_for_language(
        ["gestdown", "opensubtitlescom", "tvsubtitles"], "en", language_map=LANG_MAP
    )
    # both gestdown and opensubtitlescom support en; tvsubtitles unknown kept last
    assert ordered == ["gestdown", "opensubtitlescom", "tvsubtitles"]


def test_default_providers_dropped_dead_podnapisi():
    assert "podnapisi" not in fss.DEFAULT_PROVIDERS


def test_refine_called_during_fetch(monkeypatch, tmp_path, fake_video):
    vid = tmp_path / "Some.Show.S01E01.mkv"
    vid.touch()
    monkeypatch.setattr(fss, "scan_video", lambda p: fake_video(name=vid.name))
    refined = {"called": False}

    def fake_refine(video, **kwargs):
        refined["called"] = True
        assert kwargs.get("refiners") == fss.DEFAULT_REFINERS
        return video

    monkeypatch.setattr(fss, "refine", fake_refine)
    monkeypatch.setattr(fss, "try_download_for_language", lambda *a, **k: ("not_found", None))
    from babelfish import Language

    fss.fetch_subtitle_for_video(vid, [Language.fromietf("sv")], ["gestdown"], {}, "utf-8", False)
    assert refined["called"] is True


def test_refine_failure_is_non_fatal(monkeypatch, tmp_path, fake_video):
    vid = tmp_path / "Some.Show.S01E01.mkv"
    vid.touch()
    monkeypatch.setattr(fss, "scan_video", lambda p: fake_video(name=vid.name))

    def boom(video, **kwargs):
        raise RuntimeError("hash failed")

    monkeypatch.setattr(fss, "refine", boom)
    monkeypatch.setattr(fss, "try_download_for_language", lambda *a, **k: ("not_found", None))
    from babelfish import Language

    result, *_ = fss.fetch_subtitle_for_video(
        vid, [Language.fromietf("sv")], ["gestdown"], {}, "utf-8", False
    )
    assert result == "not_found"  # refine blowing up did not break the search


def test_coverage_hint_when_thin_and_unconfigured():
    stats = fss.RunStats(not_found=5)
    hint = fss.coverage_hint(stats, {})
    assert hint is not None and "OpenSubtitles" in hint


def test_no_coverage_hint_when_configured():
    stats = fss.RunStats(not_found=5)
    assert fss.coverage_hint(stats, {"opensubtitlescom": {"username": "u"}}) is None


def test_no_coverage_hint_when_nothing_missing():
    assert fss.coverage_hint(fss.RunStats(not_found=0), {}) is None
