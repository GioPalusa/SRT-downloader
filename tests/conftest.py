"""Shared fixtures for the srt-downloader test suite."""

from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest

import fetch_srt_subtitles as fss


@pytest.fixture(autouse=True)
def _no_real_dogpile(monkeypatch):
    """Stub the dogpile cache region's configure().

    subliminal's ``region`` is module-global and can only be ``configure()``-d
    once per process. Stubbing it lets ``configure_cache`` run repeatedly across
    tests; every cache test then asserts on the *returned path* (the
    writable -> temp -> memory fallback selection), never on dogpile state.
    """
    monkeypatch.setattr(fss.region, "configure", lambda *args, **kwargs: None)


@pytest.fixture
def media_tree(tmp_path: Path) -> Path:
    """A scan root exercising the historically-problematic filename shapes."""
    (tmp_path / "Some.Show.S01E01.1080p.mkv").touch()
    (tmp_path / "Movie [1080p] (2020).mkv").touch()  # bracket/paren stem (glob trap)
    (tmp_path / "Pack.S01E01E02.mkv").touch()  # multi-episode (list season/episode)
    nested = tmp_path / "Season 1"
    nested.mkdir()
    (nested / "Show.S01E03.mkv").touch()
    (tmp_path / "notes.txt").touch()  # non-video, must be ignored
    (tmp_path / "Some.Show.S01E01.1080p.en.srt").touch()  # pre-existing EN subtitle
    return tmp_path


@dataclasses.dataclass
class FakeSubtitle:
    """Stand-in for a subliminal subtitle (only the attribute the code reads)."""

    provider_name: str = "fakeprov"


@dataclasses.dataclass(eq=False)  # eq=False keeps identity hashing (real Videos are hashable)
class FakeVideo:
    """Stand-in for a subliminal Video. Only the attributes the module reads.

    ``season``/``episode`` may be set to lists to mimic guessit's output for
    multi-episode files (e.g. ``S01E01E02`` -> ``episode == [1, 2]``).
    """

    name: str = "Some.Show.S01E01.1080p.mkv"
    series: str | None = "Some Show"
    season: object = 1
    episode: object = 1
    title: str | None = None
    year: int | None = None


@pytest.fixture
def fake_video():
    return FakeVideo


@pytest.fixture
def fake_subtitle():
    return FakeSubtitle
