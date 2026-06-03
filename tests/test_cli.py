"""Entry-point behavior: exit codes, deleted CWD, version, crash handler."""

from __future__ import annotations

import re

import pytest

import fetch_srt_subtitles as fss


def test_version(capsys):
    with pytest.raises(SystemExit) as exc:
        fss.parse_args(["--version"])
    # argparse exits 0 after printing version
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert re.search(r"SRT Downloader \S+", out)


def test_main_nonexistent_path_returns_2(tmp_path, capsys):
    missing = tmp_path / "does-not-exist"
    assert fss.main([str(missing)]) == 2
    assert "does not exist" in capsys.readouterr().err


def test_main_unresolvable_path_is_friendly(monkeypatch, capsys):
    # Simulate a deleted working directory: resolving the path raises OSError.
    def boom(self, *a, **k):
        raise OSError("No such file or directory")

    monkeypatch.setattr(fss.Path, "resolve", boom)
    assert fss.main(["."]) == 2
    err = capsys.readouterr().err
    assert "Cannot access the scan path" in err
    assert "Traceback" not in err  # friendly, not a raw crash


def test_run_handles_unexpected_exception(monkeypatch, capsys):
    monkeypatch.setattr(fss, "main", lambda argv=None: (_ for _ in ()).throw(RuntimeError("boom")))
    code = fss.run()
    assert code == 70
    err = capsys.readouterr().err
    assert fss.ISSUES_URL in err


def test_run_keyboardinterrupt_returns_130(monkeypatch):
    def interrupt(argv=None):
        raise KeyboardInterrupt

    monkeypatch.setattr(fss, "main", interrupt)
    assert fss.run() == 130


def test_list_providers_exits_zero(capsys):
    assert fss.main(["--list-providers", "."]) == 0
    assert "provider" in capsys.readouterr().out.lower()
