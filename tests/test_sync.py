"""Phase 4: ffsubsync integration (subprocess mocked), tool detection, wiring."""

from __future__ import annotations

import subprocess
from pathlib import Path

from babelfish import Language

import fetch_srt_subtitles as fss


def test_sync_tools_available(monkeypatch):
    monkeypatch.setattr(fss.shutil, "which", lambda name: "/usr/bin/" + name)
    assert fss.sync_tools_available() is True
    monkeypatch.setattr(fss.shutil, "which", lambda name: None)
    assert fss.sync_tools_available() is False


def test_sync_subtitle_success_replaces_file(monkeypatch, tmp_path):
    video = tmp_path / "v.mkv"
    video.touch()
    srt = tmp_path / "v.sv.srt"
    srt.write_text("original")

    def fake_run(cmd, **kwargs):
        # ffsubsync writes the -o target; emulate it
        out = Path(cmd[cmd.index("-o") + 1])
        out.write_text("synced content")
        return subprocess.CompletedProcess(cmd, 0, b"", b"")

    monkeypatch.setattr(fss.subprocess, "run", fake_run)
    assert fss.sync_subtitle(video, srt) is True
    assert srt.read_text() == "synced content"
    # temp file cleaned up
    assert not (tmp_path / "v.sv.srt.synced.tmp").exists()


def test_sync_subtitle_failure_keeps_original(monkeypatch, tmp_path):
    video = tmp_path / "v.mkv"
    video.touch()
    srt = tmp_path / "v.sv.srt"
    srt.write_text("original")

    def fake_run(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, 1, b"", b"boom")

    monkeypatch.setattr(fss.subprocess, "run", fake_run)
    assert fss.sync_subtitle(video, srt) is False
    assert srt.read_text() == "original"  # untouched on failure


def test_sync_subtitle_handles_missing_binary(monkeypatch, tmp_path):
    video = tmp_path / "v.mkv"
    video.touch()
    srt = tmp_path / "v.sv.srt"
    srt.write_text("original")

    def fake_run(cmd, **kwargs):
        raise FileNotFoundError("ffsubsync")

    monkeypatch.setattr(fss.subprocess, "run", fake_run)
    assert fss.sync_subtitle(video, srt) is False
    assert srt.read_text() == "original"


def test_process_video_syncs_after_download(monkeypatch, tmp_path):
    video = tmp_path / "Some.Show.S01E01.mkv"
    video.touch()
    (tmp_path / "Some.Show.S01E01.sv.srt").write_text("subs")  # the "downloaded" file

    monkeypatch.setattr(
        fss,
        "fetch_subtitle_for_video",
        lambda **k: ("downloaded", Language.fromietf("sv"), "prov"),
    )
    calls = {"sync": 0}

    def fake_sync(video_path, subtitle_path):
        calls["sync"] += 1
        return True

    monkeypatch.setattr(fss, "sync_subtitle", fake_sync)
    result, lang, provider, synced = fss.process_video(
        video,
        languages=[Language.fromietf("sv")],
        providers=["gestdown"],
        provider_configs={},
        encoding="utf-8",
        detailed_progress=False,
        ledger=None,
        sync=True,
    )
    assert result == "downloaded"
    assert synced is True
    assert calls["sync"] == 1


def test_process_video_no_sync_when_disabled(monkeypatch, tmp_path):
    video = tmp_path / "Some.Show.S01E01.mkv"
    video.touch()
    monkeypatch.setattr(
        fss,
        "fetch_subtitle_for_video",
        lambda **k: ("downloaded", Language.fromietf("sv"), "prov"),
    )
    monkeypatch.setattr(
        fss, "sync_subtitle", lambda *a: (_ for _ in ()).throw(AssertionError("should not sync"))
    )
    result, lang, provider, synced = fss.process_video(
        video,
        languages=[Language.fromietf("sv")],
        providers=["gestdown"],
        provider_configs={},
        encoding="utf-8",
        detailed_progress=False,
        ledger=None,
        sync=False,
    )
    assert synced is False


def test_process_video_no_sync_on_not_found(monkeypatch, tmp_path):
    video = tmp_path / "v.mkv"
    video.touch()
    monkeypatch.setattr(fss, "fetch_subtitle_for_video", lambda **k: ("not_found", None, None))
    monkeypatch.setattr(
        fss, "sync_subtitle", lambda *a: (_ for _ in ()).throw(AssertionError("should not sync"))
    )
    result, lang, provider, synced = fss.process_video(
        video,
        languages=[Language.fromietf("sv")],
        providers=["gestdown"],
        provider_configs={},
        encoding="utf-8",
        detailed_progress=False,
        ledger=None,
        sync=True,
    )
    assert (result, synced) == ("not_found", False)


def test_sync_flag_resolution():
    rt = fss.resolve_runtime_options(fss.parse_args(["--sync", "."]), {})
    assert rt["sync"] is True
    assert fss.resolve_runtime_options(fss.parse_args(["."]), {})["sync"] is False


def test_synced_counts_in_summary():
    stats = fss.RunStats()
    ui = fss.StatusUI(enabled=False)
    fss._apply_result(ui, stats, Path("a.mkv"), "downloaded", Language.fromietf("sv"), "p", True)
    assert stats.synced == 1
    assert stats.downloaded == 1
