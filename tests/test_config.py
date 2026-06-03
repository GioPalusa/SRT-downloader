"""Argument parsing, config loading, and runtime/provider resolution."""

from __future__ import annotations

import pytest

import fetch_srt_subtitles as fss


def _runtime(argv, config=None):
    args = fss.parse_args(argv)
    return fss.resolve_runtime_options(args, config or {})


def test_first_defined():
    assert fss.first_defined(None, None, "x", "y") == "x"
    assert fss.first_defined(None, None) is None


def test_normalize_string_list_variants():
    assert fss.normalize_string_list("sv", "k") == ["sv"]
    assert fss.normalize_string_list(["sv", "en", "sv"], "k") == ["sv", "en"]  # dedup, order
    assert fss.normalize_string_list(None, "k") == []
    with pytest.raises(ValueError):
        fss.normalize_string_list(123, "k")


def test_coerce_positive_float():
    assert fss._coerce_positive_float("3", "k") == 3.0
    with pytest.raises(ValueError):
        fss._coerce_positive_float("nope", "k")
    with pytest.raises(ValueError):
        fss._coerce_positive_float(-1, "k")


def test_english_appended_as_fallback():
    rt = _runtime(["-l", "sv", "."])
    assert rt["languages"] == ["sv", "en"]


def test_clean_and_recheck_flags():
    rt = _runtime(["--clean", "--recheck-after", "3", "."])
    assert rt["clean"] is True
    assert rt["recheck_after_days"] == 3.0
    # default: resume on (clean False), default recheck window
    rt2 = _runtime(["."])
    assert rt2["clean"] is False
    assert rt2["recheck_after_days"] == 14.0


def test_cli_overrides_config():
    rt = _runtime(["-l", "de", "."], config={"languages": ["fr"]})
    assert rt["languages"][0] == "de"


def test_resolve_providers_appends_defaults_unless_only_selected():
    merged = fss.resolve_providers(["opensubtitlescom"], {"opensubtitlescom": {}}, False)
    assert merged[0] == "opensubtitlescom"
    assert any(p in merged for p in fss.DEFAULT_PROVIDERS)
    only = fss.resolve_providers(["opensubtitlescom"], {"opensubtitlescom": {}}, True)
    assert only == ["opensubtitlescom"]


def test_provider_configs_from_env(monkeypatch):
    monkeypatch.setenv("OPENSUBTITLESCOM_USERNAME", "u")
    monkeypatch.setenv("OPENSUBTITLESCOM_PASSWORD", "p")
    cfg = fss.provider_configs_from_env()
    assert cfg["opensubtitlescom"] == {"username": "u", "password": "p"}


def test_load_config_missing_file_raises(tmp_path):
    with pytest.raises(ValueError):
        fss.load_config(str(tmp_path / "nope.yaml"))


def test_load_config_reads_yaml(tmp_path):
    cfg_file = tmp_path / "srt.yaml"
    cfg_file.write_text("languages: [sv]\nrecheck_after_days: 7\n", encoding="utf-8")
    config, path = fss.load_config(str(cfg_file))
    assert config["languages"] == ["sv"]
    assert path == cfg_file
