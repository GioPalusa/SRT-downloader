"""Cheap early signal that the subliminal symbols the module relies on are bound.

The real bundling guard for the frozen binary is the CI smoke test (a real scan);
this only catches an import/refactor mistake quickly.
"""

from __future__ import annotations

import fetch_srt_subtitles as fss


def test_top_level_subliminal_symbols_bound():
    assert callable(fss.download_best_subtitles)
    assert callable(fss.scan_video)
    assert callable(fss.save_subtitles)
    assert fss.region is not None


def test_app_version_resolves():
    assert isinstance(fss.APP_VERSION, str)
    assert fss.APP_VERSION
