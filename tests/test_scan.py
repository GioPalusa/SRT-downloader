"""File iteration and existing-subtitle detection (incl. the bracket-glob bug)."""

from __future__ import annotations

import os

from babelfish import Language

import fetch_srt_subtitles as fss


def test_iter_video_files_finds_videos_ignores_others(media_tree):
    names = {p.name for p in fss.iter_video_files(media_tree)}
    assert "Some.Show.S01E01.1080p.mkv" in names
    assert "Show.S01E03.mkv" in names  # nested
    assert "notes.txt" not in names


def test_iter_video_files_skips_unreadable_dir(tmp_path):
    (tmp_path / "top.mkv").touch()
    locked = tmp_path / "locked"
    locked.mkdir()
    (locked / "inner.mkv").touch()
    os.chmod(locked, 0o000)
    try:
        names = {p.name for p in fss.iter_video_files(tmp_path)}
    finally:
        os.chmod(locked, 0o755)
    assert "top.mkv" in names  # did not crash on the locked dir


def test_existing_subtitle_paths_handles_bracket_stem(tmp_path):
    # A glob-based implementation would treat [1080p] as a character class
    # and miss this; iterdir-based matching must find it.
    video = tmp_path / "Movie [1080p] (2020).mkv"
    video.touch()
    (tmp_path / "Movie [1080p] (2020).sv.srt").touch()
    (tmp_path / "Movie [1080p] (2020).srt").touch()
    found = {p.name for p in fss.existing_subtitle_paths(video)}
    assert found == {"Movie [1080p] (2020).sv.srt", "Movie [1080p] (2020).srt"}


def test_has_subtitle_for_language_bracket(tmp_path):
    video = tmp_path / "Movie [1080p] (2020).mkv"
    video.touch()
    (tmp_path / "Movie [1080p] (2020).sv.srt").touch()
    assert fss.has_subtitle_for_language(video, Language.fromietf("sv")) is True
    # plain .srt counts as English
    (tmp_path / "Movie [1080p] (2020).srt").touch()
    assert fss.has_subtitle_for_language(video, Language.fromietf("en")) is True


def test_existing_subtitle_paths_tolerates_oserror(tmp_path):
    # parent dir gone -> returns [] instead of raising
    video = tmp_path / "gone" / "x.mkv"
    assert fss.existing_subtitle_paths(video) == []


def test_dir_is_writable(tmp_path):
    assert fss._dir_is_writable(tmp_path) is True
    ro = tmp_path / "ro"
    ro.mkdir()
    os.chmod(ro, 0o500)
    try:
        assert fss._dir_is_writable(ro) is False
    finally:
        os.chmod(ro, 0o755)


def test_language_code_fallback():
    assert fss._language_code(Language.fromietf("sv")) == "sv"
