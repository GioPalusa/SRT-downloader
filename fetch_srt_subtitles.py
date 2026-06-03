#!/usr/bin/env python3

from __future__ import annotations

import argparse
import concurrent.futures
import dbm
import functools
import itertools
import json
import logging
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from collections import Counter, deque
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from importlib import metadata as importlib_metadata
from pathlib import Path
from typing import Any

import yaml
from babelfish import Language
from requests.exceptions import RequestException
from subliminal import (
    VIDEO_EXTENSIONS,
    download_best_subtitles,
    refine,
    region,
    save_subtitles,
    scan_video,
)
from subliminal.exceptions import GuessingError, ProviderError

try:
    from rich.console import Console, Group
    from rich.live import Live
    from rich.panel import Panel
    from rich.spinner import Spinner
    from rich.text import Text

    HAS_RICH = True
except ImportError:  # pragma: no cover - fallback for environments without rich
    HAS_RICH = False

# Public providers tried when the user has not restricted the set. podnapisi was
# dropped because its host no longer resolves. subtitulamos/subtis are
# Spanish-only and are kept reachable via -p, but language-aware ordering
# deprioritises (or drops) providers that do not serve the requested language.
DEFAULT_PROVIDERS = [
    "gestdown",
    "tvsubtitles",
    "subtitulamos",
    "subtis",
]

# Refiners run locally after scanning to enrich a video before searching.
# "hash" computes the file hash used for release-accurate matches (the single
# biggest lever for hit rate); "metadata" reads embedded stream info via enzyme.
DEFAULT_REFINERS = ("hash", "metadata")

DEFAULT_CONFIG_FILES = [
    "srt-downloader.yaml",
    ".srt-downloader.yaml",
]


def _resolve_app_version() -> str:
    try:
        return importlib_metadata.version("srt-downloader")
    except importlib_metadata.PackageNotFoundError:
        return "0.0.0+source"


APP_VERSION = _resolve_app_version()
ISSUES_URL = "https://github.com/GioPalusa/SRT-downloader/issues"


@dataclass
class RunStats:
    scanned: int = 0
    downloaded: int = 0
    skipped_existing: int = 0
    skipped_recent: int = 0
    not_found: int = 0
    failed: int = 0
    synced: int = 0
    provider_downloads: Counter[str] = field(default_factory=Counter)


class StatusUI:
    def __init__(self, enabled: bool = True) -> None:
        self.enabled = bool(enabled and HAS_RICH)
        self.console = Console() if self.enabled else None
        self.live: Live | None = None
        self.recent_results: deque[str] = deque(maxlen=8)

    def print_splash(self, root: Path, languages: list[Language], providers: list[str]) -> None:
        language_line = ", ".join(str(language) for language in languages)
        provider_line = ", ".join(providers) if providers else "(none)"

        if self.enabled and self.console is not None:
            splash = Text()
            splash.append("SRT Downloader\n", style="bold magenta")
            splash.append(f"Root: {root}\n", style="cyan")
            splash.append(f"Languages: {language_line}\n", style="green")
            splash.append(f"Providers: {provider_line}", style="white")
            self.console.print(Panel(splash, border_style="bright_blue", title="Live Mode"))
        else:
            print(f"Scanning {root}")
            print(f"Languages: {language_line}")
            print(f"Providers: {provider_line}")

    def start(self, message: str, stats: RunStats, detail_text: str = "Ready") -> None:
        if not self.enabled:
            return
        self.live = Live(
            self._render(message, stats, detail_text=detail_text),
            console=self.console,
            refresh_per_second=12,
            screen=True,
        )
        self.live.start()

    def update(self, message: str, stats: RunStats, detail_text: str = "") -> None:
        if self.enabled and self.live is not None:
            self.live.update(self._render(message, stats, detail_text=detail_text))

    def add_result(self, text: str) -> None:
        self.recent_results.appendleft(text)

    def stop(self) -> None:
        if self.enabled and self.live is not None:
            self.live.stop()
            self.live = None

    def print_summary(self, stats: RunStats, interrupted: bool) -> None:
        summary_lines = [
            f"Videos scanned: {stats.scanned}",
            f"Subtitles downloaded: {stats.downloaded}",
            f"Skipped existing: {stats.skipped_existing}",
            f"Skipped (recently checked): {stats.skipped_recent}",
            f"Not found: {stats.not_found}",
            f"Failed: {stats.failed}",
        ]
        if stats.synced:
            summary_lines.append(f"Synced: {stats.synced}")

        if stats.provider_downloads:
            provider_parts = [
                f"{provider}: {count}" for provider, count in stats.provider_downloads.most_common()
            ]
            summary_lines.append(f"Downloaded by provider: {', '.join(provider_parts)}")

        if self.enabled and self.console is not None:
            title = "Run Cancelled" if interrupted else "Run Complete"
            style = "yellow" if interrupted else "green"
            self.console.print(Panel("\n".join(summary_lines), title=title, border_style=style))
        else:
            if interrupted:
                print("Run cancelled by user.")
            for line in summary_lines:
                print(line)

    def _render(self, message: str, stats: RunStats, detail_text: str = ""):
        body = Text()
        body.append("Scanned: ", style="bright_cyan")
        body.append(str(stats.scanned), style="bold white")
        body.append("  Downloaded: ", style="bright_green")
        body.append(str(stats.downloaded), style="bold white")
        body.append("  Skipped: ", style="bright_yellow")
        body.append(str(stats.skipped_existing), style="bold white")
        body.append("  Not found: ", style="bright_magenta")
        body.append(str(stats.not_found), style="bold white")
        body.append("  Failed: ", style="bright_red")
        body.append(str(stats.failed), style="bold white")

        spinner = Spinner("dots", text=Text(message, style="bold cyan"))

        detail_line = Text()
        detail_line.append("Now: ", style="bright_black")
        detail_line.append(detail_text or "working...", style="white")

        current_panel = Panel(
            Group(spinner, detail_line),
            subtitle=body,
            border_style="blue",
            title="Current",
        )

        if self.recent_results:
            history_content = Text("\n".join(self.recent_results), style="white")
        else:
            history_content = Text("No completed files yet", style="white")

        history_panel = Panel(history_content, border_style="bright_black", title="Recent")
        return Group(current_panel, history_panel)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Recursively scan a folder for video files, search online for matching subtitles, "
            "and save them next to each video using the same basename."
        )
    )
    parser.add_argument(
        "path",
        nargs="?",
        default=None,
        help="Folder to scan. Defaults to the configured path or the current working directory.",
    )
    parser.add_argument(
        "--config",
        default=None,
        help=(
            "Optional path to a YAML config file. If omitted, the tool auto-loads "
            "srt-downloader.yaml or .srt-downloader.yaml from the current directory when present."
        ),
    )
    parser.add_argument(
        "-l",
        "--language",
        default=None,
        help=(
            "Primary subtitle language as an IETF code, for example en, sv, or pt-BR. "
            "English is appended automatically as a fallback when it is not already included."
        ),
    )
    parser.add_argument(
        "-p",
        "--provider",
        action="append",
        dest="providers",
        help=(
            "Subtitle provider to prioritize. Repeat to use multiple providers. "
            "Configured and environment credential providers are auto-added."
        ),
    )
    parser.add_argument(
        "--encoding",
        default=None,
        help="Encoding used when saving subtitles. Default: utf-8.",
    )
    parser.add_argument(
        "--verbose",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Print debug information while scanning and downloading.",
    )
    parser.add_argument(
        "--detailed-progress",
        action=argparse.BooleanOptionalAction,
        default=None,
        help=(
            "Show detailed per-provider progress updates. This is slower than the default fast mode "
            "because providers are queried one-by-one."
        ),
    )
    parser.add_argument(
        "--only-selected-providers",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Use only explicitly selected and credentialed providers. Skip public fallback providers.",
    )
    parser.add_argument(
        "--clean",
        action="store_true",
        help=(
            "Ignore and reset the saved progress, re-searching every video from scratch. "
            "By default the tool resumes, skipping videos already resolved or recently not found."
        ),
    )
    parser.add_argument(
        "--recheck-after",
        type=float,
        default=None,
        metavar="DAYS",
        help=("How many days before a previously not-found video is searched again. Default: 14."),
    )
    parser.add_argument(
        "-j",
        "--jobs",
        type=int,
        default=None,
        metavar="N",
        help=(
            "Number of videos to process in parallel. Default: 4. Use 1 for fully "
            "sequential processing with detailed per-provider progress."
        ),
    )
    parser.add_argument(
        "--min-request-interval",
        type=float,
        default=None,
        metavar="SECONDS",
        help=(
            "Minimum delay between subtitle searches across all workers, to stay "
            "polite to providers. Default: 0 (rely on the worker count)."
        ),
    )
    parser.add_argument(
        "--sync",
        action=argparse.BooleanOptionalAction,
        default=None,
        help=(
            "After downloading, automatically correct subtitle timing against the "
            "video using ffsubsync (requires ffsubsync and ffmpeg on PATH)."
        ),
    )
    parser.add_argument(
        "--list-providers",
        action="store_true",
        help="Print provider selection details and exit.",
    )
    parser.add_argument(
        "--print-effective-config",
        action="store_true",
        help="Print merged runtime configuration and exit.",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"SRT Downloader {APP_VERSION}",
    )
    return parser.parse_args(argv)


def first_defined(*values: Any) -> Any:
    for value in values:
        if value is not None:
            return value
    return None


def normalize_string_list(value: Any, key_name: str) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        items = [value]
    elif isinstance(value, list):
        items = value
    else:
        raise ValueError(f"Config key '{key_name}' must be a string or a list of strings.")

    normalized: list[str] = []
    for item in items:
        if not isinstance(item, str):
            raise ValueError(f"Config key '{key_name}' must contain only strings.")
        cleaned = item.strip()
        if cleaned and cleaned not in normalized:
            normalized.append(cleaned)
    return normalized


def load_config(config_arg: str | None) -> tuple[dict[str, Any], Path | None]:
    config_path = None
    config: dict[str, Any] = {}

    if config_arg:
        config_path = Path(config_arg).expanduser()
        if not config_path.exists():
            raise ValueError(f"Config file not found: {config_path}")
    else:
        for default_file in DEFAULT_CONFIG_FILES:
            candidate = Path(default_file)
            if candidate.exists():
                config_path = candidate
                break

    if config_path is not None:
        with config_path.open("r", encoding="utf-8") as handle:
            loaded = yaml.safe_load(handle) or {}
        if not isinstance(loaded, dict):
            raise ValueError("The config file must contain a YAML mapping at the top level.")
        config = loaded

    raw_providers = config.get("providers", {})
    provider_credentials: dict[str, dict[str, str]] = {}
    legacy_selected_providers: list[str] = []

    if isinstance(raw_providers, dict):
        for provider_name, credentials in raw_providers.items():
            if not isinstance(provider_name, str):
                raise ValueError("Config provider names must be strings.")
            if credentials is None:
                provider_credentials[provider_name] = {}
                continue
            if not isinstance(credentials, dict):
                raise ValueError(
                    "Config key 'providers' must be a mapping of provider names to provider settings."
                )
            provider_credentials[provider_name] = {
                str(key): str(value) for key, value in credentials.items() if value is not None
            }
    elif isinstance(raw_providers, list):
        legacy_selected_providers = normalize_string_list(raw_providers, "providers")
    else:
        raise ValueError("Config key 'providers' must be either a mapping or a list of strings.")

    config["providers"] = provider_credentials
    config["selected_providers"] = normalize_string_list(
        first_defined(config.get("selected_providers"), legacy_selected_providers),
        "selected_providers",
    )
    return config, config_path


def resolve_runtime_options(args: argparse.Namespace, config: dict[str, Any]) -> dict[str, Any]:
    language_value = first_defined(args.language, config.get("languages"), config.get("language"), "en")
    languages = normalize_string_list(language_value, "language")
    if not languages:
        raise ValueError("At least one subtitle language must be configured.")
    if "en" not in {language.lower() for language in languages}:
        languages.append("en")

    providers = normalize_string_list(
        first_defined(args.providers, config.get("selected_providers"), []),
        "selected_providers",
    )

    runtime = {
        "path": str(first_defined(args.path, config.get("path"), ".")),
        "languages": languages,
        "providers": providers,
        "only_selected_providers": bool(
            first_defined(args.only_selected_providers, config.get("only_selected_providers"), False)
        ),
        "detailed_progress": bool(
            first_defined(args.detailed_progress, config.get("detailed_progress"), False)
        ),
        "verbose": bool(first_defined(args.verbose, config.get("verbose"), False)),
        "encoding": str(first_defined(args.encoding, config.get("encoding"), "utf-8")),
        "clean": bool(getattr(args, "clean", False)),
        "recheck_after_days": _coerce_positive_float(
            first_defined(args.recheck_after, config.get("recheck_after_days"), 14.0),
            "recheck_after_days",
        ),
        "jobs": _coerce_jobs(first_defined(args.jobs, config.get("jobs"), 4)),
        "min_request_interval": _coerce_positive_float(
            first_defined(args.min_request_interval, config.get("min_request_interval"), 0.0),
            "min_request_interval",
        ),
        "sync": bool(first_defined(args.sync, config.get("sync"), False)),
    }
    return runtime


def _coerce_jobs(value: Any) -> int:
    try:
        jobs = int(value)
    except (TypeError, ValueError):
        raise ValueError("Config key 'jobs' must be an integer.") from None
    return max(1, jobs)


def _coerce_positive_float(value: Any, key_name: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Config key '{key_name}' must be a number.") from exc
    if result < 0:
        raise ValueError(f"Config key '{key_name}' must not be negative.")
    return result


def merge_provider_configs(config_provider_configs: dict[str, dict[str, str]]) -> dict[str, dict[str, str]]:
    merged = {name: values.copy() for name, values in config_provider_configs.items()}
    for provider_name, credentials in provider_configs_from_env().items():
        merged[provider_name] = credentials
    return merged


def resolve_providers(
    selected_providers: list[str],
    provider_configs: dict[str, dict[str, str]],
    only_selected_providers: bool,
) -> list[str]:
    effective: list[str] = []

    def add_provider(name: str) -> None:
        if name and name not in effective:
            effective.append(name)

    for provider in selected_providers:
        add_provider(provider)

    for provider in provider_configs:
        add_provider(provider)

    if not only_selected_providers:
        for provider in DEFAULT_PROVIDERS:
            add_provider(provider)

    return effective


@functools.lru_cache(maxsize=1)
def _provider_language_map() -> dict[str, frozenset[str]]:
    """Map provider name -> set of alpha2 language codes it advertises.

    Read best-effort from each provider class's ``languages`` attribute via the
    subliminal entry points. Providers that fail to load are simply omitted,
    which makes ordering fail-open (an unknown provider is never dropped).
    """
    result: dict[str, frozenset[str]] = {}
    try:
        from importlib.metadata import entry_points

        eps = entry_points(group="subliminal.providers")
    except Exception:  # pragma: no cover - defensive
        return result
    for ep in eps:
        try:
            provider_cls = ep.load()
            langs = getattr(provider_cls, "languages", None) or ()
            codes = set()
            for lang in langs:
                code = getattr(lang, "alpha2", None) or str(lang)
                if code:
                    codes.add(code.lower())
            if codes:
                result[ep.name] = frozenset(codes)
        except Exception:  # pragma: no cover - a provider failing to import is non-fatal
            continue
    return result


def order_providers_for_language(
    providers: list[str],
    language_code: str,
    language_map: dict[str, frozenset[str]] | None = None,
    drop_unsupported: bool = True,
) -> list[str]:
    """Order providers so those that serve ``language_code`` come first.

    Providers whose language set is known and does NOT include the language are
    dropped when ``drop_unsupported`` is set; providers with an unknown language
    set are always kept (fail-open) so an incomplete map never hides a provider.
    Original order is otherwise preserved (stable).
    """
    language_map = _provider_language_map() if language_map is None else language_map
    code = language_code.lower()
    supported: list[str] = []
    unknown: list[str] = []
    unsupported: list[str] = []
    for provider in providers:
        langs = language_map.get(provider)
        if langs is None:
            unknown.append(provider)
        elif code in langs:
            supported.append(provider)
        else:
            unsupported.append(provider)
    ordered = supported + unknown
    if not drop_unsupported:
        ordered += unsupported
    # Never return an empty list just because the map was confident-but-wrong:
    # fall back to the original providers if language-gating removed everything.
    return ordered or providers


def coverage_hint(stats: RunStats, provider_configs: dict[str, dict[str, str]]) -> str | None:
    """Suggest configuring OpenSubtitles.com when results were thin."""
    found_any_credentials = any(name in provider_configs for name in ("opensubtitlescom", "opensubtitles"))
    if stats.not_found > 0 and not found_any_credentials:
        return (
            f"{stats.not_found} not found. For better coverage (especially non-English), "
            "create a free OpenSubtitles.com account and set OPENSUBTITLESCOM_USERNAME / "
            "OPENSUBTITLESCOM_PASSWORD, then add -p opensubtitlescom."
        )
    return None


def print_provider_report(
    runtime: dict[str, Any],
    provider_configs: dict[str, dict[str, str]],
    providers: list[str],
) -> None:
    selected = runtime["providers"]
    credentialed = sorted(provider_configs.keys())
    public_fallback = [
        provider
        for provider in DEFAULT_PROVIDERS
        if provider not in selected and provider not in credentialed
    ]
    if runtime["only_selected_providers"]:
        public_fallback = []

    print("Provider Report")
    print(f"Selected providers: {', '.join(selected) if selected else '(none)'}")
    print(
        "Credentialed providers from config or environment: "
        f"{', '.join(credentialed) if credentialed else '(none)'}"
    )
    print(f"Public fallback providers: {', '.join(public_fallback) if public_fallback else '(disabled)'}")
    print(f"Effective provider order: {', '.join(providers) if providers else '(none)'}")


def print_effective_config(
    config_path: Path | None,
    runtime: dict[str, Any],
    provider_configs: dict[str, dict[str, str]],
    providers: list[str],
) -> None:
    try:
        resolved_path = str(Path(runtime["path"]).expanduser().resolve())
    except OSError:
        resolved_path = runtime["path"]
    effective = {
        "version": APP_VERSION,
        "config_file": str(config_path.resolve()) if config_path is not None else None,
        "path": resolved_path,
        "languages": runtime["languages"],
        "encoding": runtime["encoding"],
        "verbose": runtime["verbose"],
        "detailed_progress": runtime["detailed_progress"],
        "only_selected_providers": runtime["only_selected_providers"],
        "selected_providers": runtime["providers"],
        "credentialed_providers": sorted(provider_configs.keys()),
        "effective_providers": providers,
        "clean": runtime["clean"],
        "recheck_after_days": runtime["recheck_after_days"],
    }
    print(json.dumps(effective, indent=2, sort_keys=True))


def configure_logging(verbose: bool) -> None:
    root_level = logging.DEBUG if verbose else logging.ERROR
    logging.basicConfig(level=root_level, format="%(levelname)s: %(message)s")

    if not verbose:
        # Keep provider/library chatter out of the live UI in normal mode.
        # subliminal logs routine provider failures (a dead host, a 404, a
        # timeout) with logger.exception(), i.e. full tracebacks at ERROR
        # level. Those are expected and we already report them in the summary,
        # so silence them below CRITICAL here. Use --verbose to see them.
        logging.getLogger("subliminal").setLevel(logging.CRITICAL)
        logging.getLogger("guessit").setLevel(logging.ERROR)
        logging.getLogger("babelfish").setLevel(logging.ERROR)


def _dir_is_writable(directory: Path) -> bool:
    probe = directory / ".srt-write-test"
    try:
        with probe.open("w") as handle:
            handle.write("ok")
        probe.unlink()
        return True
    except OSError:
        return False


def _repair_dbm_cache(db_path: Path) -> None:
    # A dbm file left half-written by a killed run raises on the next open and
    # would otherwise wedge every future run. Validate it; if it is corrupt,
    # remove the cache files so a fresh one is created.
    try:
        handle = dbm.open(str(db_path), "c")
        handle.close()
        return
    except Exception:
        for leftover in db_path.parent.glob(db_path.name + "*"):
            try:
                leftover.unlink()
            except OSError:
                pass


def configure_cache(root: Path) -> Path:
    """Configure the subtitle cache, returning the directory actually used.

    Prefers a ``.subtitle-cache`` directory inside the scan root. Falls back to
    a temp directory when the root is not writable (e.g. a read-only share),
    and to an in-memory cache as a last resort, so a scan never fails just
    because it cannot persist its cache.
    """
    candidates = [root / ".subtitle-cache", Path(tempfile.gettempdir()) / "srt-downloader-cache"]
    for cache_dir in candidates:
        try:
            cache_dir.mkdir(parents=True, exist_ok=True)
        except OSError:
            continue
        if not _dir_is_writable(cache_dir):
            continue
        db_path = cache_dir / "cache.dbm"
        _repair_dbm_cache(db_path)
        region.configure("dogpile.cache.dbm", arguments={"filename": str(db_path)})
        if cache_dir != candidates[0]:
            logging.warning("Scan root is not writable; using cache at %s", cache_dir)
        return cache_dir

    # Nothing writable anywhere: keep working with a process-local cache.
    logging.warning("No writable cache location found; using an in-memory cache.")
    region.configure("dogpile.cache.memory")
    return candidates[0]


LEDGER_VERSION = 1


class ProgressLedger:
    """Tracks per-video, per-language outcomes so an aborted or repeated run
    can skip work it already did instead of re-searching every file.

    Keyed by absolute path plus size and mtime, so a file that changes on disk
    is re-evaluated. ``downloaded``/``exists`` are always skipped; ``not_found``
    is skipped only until ``recheck_after`` elapses (subtitles may appear
    later); ``failed`` is never cached, since failures are usually transient.
    """

    def __init__(self, path: Path | None, recheck_after_seconds: float, reset: bool = False) -> None:
        self.path = path
        self.recheck_after = recheck_after_seconds
        self.dirty = False
        self._entries: dict[str, dict[str, Any]] = {}
        self._lock = threading.RLock()  # guards _entries for concurrent workers
        if reset:
            # --clean: discard any saved progress and start fresh.
            if self.path is not None:
                try:
                    self.path.unlink()
                except OSError:
                    pass
        else:
            self._load()

    def _load(self) -> None:
        if self.path is None or not self.path.exists():
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        if isinstance(data, dict) and data.get("version") == LEDGER_VERSION:
            entries = data.get("entries")
            if isinstance(entries, dict):
                self._entries = entries

    @staticmethod
    def _stat(video_path: Path) -> tuple[int | None, int | None]:
        try:
            st = video_path.stat()
            return int(st.st_size), int(st.st_mtime)
        except OSError:
            return (None, None)

    def _valid_entry(self, video_path: Path) -> dict[str, Any] | None:
        entry = self._entries.get(str(video_path))
        if entry is None:
            return None
        size, mtime = self._stat(video_path)
        if entry.get("size") != size or entry.get("mtime") != mtime:
            # File changed since we recorded it; drop the stale entry.
            self._entries.pop(str(video_path), None)
            self.dirty = True
            return None
        return entry

    def should_skip(self, video_path: Path, language_code: str) -> bool:
        with self._lock:
            entry = self._valid_entry(video_path)
            if not entry:
                return False
            lang = entry.get("languages", {}).get(language_code)
            if not lang:
                return False
            status = lang.get("status")
            if status in ("downloaded", "exists"):
                return True
            if status == "not_found":
                return (time.time() - float(lang.get("ts", 0))) < self.recheck_after
            return False

    def record(self, video_path: Path, language_code: str, status: str) -> None:
        with self._lock:
            size, mtime = self._stat(video_path)
            entry = self._entries.get(str(video_path))
            if entry is None or entry.get("size") != size or entry.get("mtime") != mtime:
                entry = {"size": size, "mtime": mtime, "languages": {}}
                self._entries[str(video_path)] = entry
            entry["languages"][language_code] = {"status": status, "ts": int(time.time())}
            self.dirty = True

    def save(self, force: bool = False) -> None:
        with self._lock:
            if self.path is None or (not self.dirty and not force):
                return
            payload = json.dumps({"version": LEDGER_VERSION, "entries": self._entries})
            try:
                tmp = self.path.with_name(self.path.name + ".tmp")
                tmp.write_text(payload, encoding="utf-8")
                tmp.replace(self.path)
                self.dirty = False
            except OSError as exc:
                logging.debug("Could not save progress ledger: %s", exc)


class RateLimiter:
    """Thread-safe minimum-interval throttle shared across worker threads.

    ``wait()`` blocks until at least ``min_interval`` seconds have elapsed since
    the previous call returned, pacing total request volume to keep providers
    happy. ``min_interval <= 0`` disables it (the worker-pool size is then the
    only throttle).
    """

    def __init__(self, min_interval: float) -> None:
        self.min_interval = max(0.0, min_interval)
        self._lock = threading.Lock()
        self._next_allowed = 0.0

    def wait(self) -> None:
        if self.min_interval <= 0:
            return
        with self._lock:
            now = time.monotonic()
            sleep_for = self._next_allowed - now
            if sleep_for > 0:
                time.sleep(sleep_for)
                now = time.monotonic()
            self._next_allowed = now + self.min_interval


def iter_video_files(root: Path) -> Iterable[Path]:
    video_extensions = {extension.lower() for extension in VIDEO_EXTENSIONS}
    # Manual walk (instead of rglob) so an unreadable directory or a file that
    # vanishes mid-scan — e.g. a network share that disconnects — is skipped
    # with a warning instead of crashing the whole run.
    pending: list[Path] = [root]
    while pending:
        directory = pending.pop()
        try:
            entries = list(directory.iterdir())
        except OSError as exc:
            logging.warning("Cannot read directory %s: %s", directory, exc)
            continue
        for path in entries:
            try:
                if path.is_dir():
                    pending.append(path)
                elif path.is_file() and path.suffix.lower() in video_extensions:
                    yield path
            except OSError as exc:
                logging.warning("Cannot access %s: %s", path, exc)
                continue


def load_languages(language_codes: Iterable[str]) -> list[Language]:
    languages: list[Language] = []
    for language_code in language_codes:
        try:
            languages.append(Language.fromietf(language_code))
        except Exception as exc:  # pragma: no cover - defensive error message for invalid input
            raise ValueError(f"Invalid language code: {language_code}") from exc
    return languages


def provider_configs_from_env() -> dict[str, dict[str, str]]:
    env_providers = {}

    if os.getenv("OPENSUBTITLESCOM_USERNAME") and os.getenv("OPENSUBTITLESCOM_PASSWORD"):
        env_providers["opensubtitlescom"] = {
            "username": os.getenv("OPENSUBTITLESCOM_USERNAME", ""),
            "password": os.getenv("OPENSUBTITLESCOM_PASSWORD", ""),
        }

    if os.getenv("OPENSUBTITLES_USERNAME") and os.getenv("OPENSUBTITLES_PASSWORD"):
        env_providers["opensubtitles"] = {
            "username": os.getenv("OPENSUBTITLES_USERNAME", ""),
            "password": os.getenv("OPENSUBTITLES_PASSWORD", ""),
        }

    if os.getenv("ADDIC7ED_USERNAME") and os.getenv("ADDIC7ED_PASSWORD"):
        env_providers["addic7ed"] = {
            "username": os.getenv("ADDIC7ED_USERNAME", ""),
            "password": os.getenv("ADDIC7ED_PASSWORD", ""),
        }

    return env_providers


def existing_subtitle_paths(video_path: Path) -> list[Path]:
    basename = video_path.stem
    results: list[Path] = []

    # Use iterdir + name comparison rather than glob: a stem containing glob
    # metacharacters (e.g. "Show [1080p]") would otherwise be treated as a
    # pattern and silently fail to match. Tolerate an unreadable directory.
    try:
        entries = list(video_path.parent.iterdir())
    except OSError:
        return []

    for subtitle_path in entries:
        if subtitle_path.suffix.lower() != ".srt":
            continue
        name = subtitle_path.name
        if name == f"{basename}.srt" or name.startswith(f"{basename}."):
            results.append(subtitle_path)

    return sorted(results)


def _language_code(language: Language) -> str:
    # Most languages expose a 2-letter alpha2 code, but some only have a
    # 3-letter code, in which case babelfish raises on .alpha2.
    try:
        return language.alpha2.lower()
    except Exception:
        return str(language).lower()


def has_subtitle_for_language(video_path: Path, language: Language) -> bool:
    basename = video_path.stem.lower()
    language_code = _language_code(language)

    for subtitle_path in existing_subtitle_paths(video_path):
        name = subtitle_path.name.lower()

        if name == f"{basename}.{language_code}.srt":
            return True

        if language_code == "en" and name == f"{basename}.srt":
            return True

    return False


def _first_int(value: Any) -> int | None:
    # guessit can return a list for season/episode on multi-episode files
    # (e.g. "S01E01E02" -> episode == [1, 2]). Take the first entry and fall
    # back to None if it is not coercible to an int.
    if isinstance(value, (list, tuple)):
        value = value[0] if value else None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def build_keyword_query_video(video):
    video_cls = type(video)
    fromname = getattr(video_cls, "fromname", None)
    if fromname is None:
        return None

    keyword_name: str | None = None

    series = getattr(video, "series", None)
    season = _first_int(getattr(video, "season", None))
    episode = _first_int(getattr(video, "episode", None))
    if series and season is not None and episode is not None:
        keyword_name = f"{series} S{season:02d}E{episode:02d}"
    else:
        title = getattr(video, "title", None)
        year = getattr(video, "year", None)
        if title:
            keyword_name = f"{title} {year}" if year else str(title)

    if not keyword_name:
        return None

    suffix = Path(str(getattr(video, "name", ""))).suffix
    if suffix:
        keyword_name = f"{keyword_name}{suffix}"

    try:
        return fromname(keyword_name)
    except Exception:
        return None


def try_download_for_language(
    video,
    language: Language,
    providers: list[str],
    provider_configs: dict[str, dict[str, str]],
    encoding: str,
    detailed_progress: bool,
    query_label: str,
    save_video=None,
    progress_cb: Callable[[str], None] | None = None,
) -> tuple[str, str | None]:
    if not providers:
        return ("not_found", None)

    save_target = save_video if save_video is not None else video

    if not detailed_progress:
        if progress_cb is not None:
            provider_text = ", ".join(providers)
            progress_cb(f"searching {language} via {provider_text} ({query_label})")

        try:
            subtitles = download_best_subtitles(
                {video},
                {language},
                providers=providers,
                provider_configs=provider_configs,
                only_one=True,
            )
        except ProviderError as exc:
            logging.warning("Provider error while processing %s: %s", video.name, exc)
            return ("failed", None)
        except RequestException as exc:
            logging.warning("Network error reaching a provider for %s: %s", video.name, exc)
            return ("failed", None)
        except Exception as exc:  # pragma: no cover - keep the batch running on unexpected provider failures
            logging.exception("Unexpected error while processing %s", video.name)
            logging.debug("Unexpected exception details: %s", exc)
            return ("failed", None)

        matches = subtitles.get(video, [])
        if not matches:
            return ("not_found", None)

        provider_name = getattr(matches[0], "provider_name", "unknown provider")
        if progress_cb is not None:
            progress_cb(f"saving subtitle from {provider_name}")

        try:
            saved = save_subtitles(
                save_target,
                matches,
                encoding=encoding,
                subtitle_format="srt",
                language_format="alpha2",
            )
        except OSError as exc:
            logging.warning("Could not save subtitle for %s: %s", video.name, exc)
            return ("failed", None)
        if not saved:
            return ("failed", None)

        return ("downloaded", provider_name)

    had_errors = False

    for index, provider in enumerate(providers, start=1):
        if progress_cb is not None:
            progress_cb(f"searching {language} via {provider} ({index}/{len(providers)}) ({query_label})")

        try:
            subtitles = download_best_subtitles(
                {video},
                {language},
                providers=[provider],
                provider_configs=provider_configs,
                only_one=True,
            )
        except ProviderError as exc:
            had_errors = True
            logging.warning("Provider %s error while processing %s: %s", provider, video.name, exc)
            if progress_cb is not None:
                progress_cb(f"provider {provider} failed, trying next")
            continue
        except RequestException as exc:
            had_errors = True
            logging.warning("Network error reaching provider %s for %s: %s", provider, video.name, exc)
            if progress_cb is not None:
                progress_cb(f"provider {provider} unreachable, trying next")
            continue
        except Exception as exc:  # pragma: no cover - keep the batch running on unexpected provider failures
            had_errors = True
            logging.exception("Unexpected provider %s error while processing %s", provider, video.name)
            logging.debug("Unexpected exception details: %s", exc)
            if progress_cb is not None:
                progress_cb(f"provider {provider} failed, trying next")
            continue

        matches = subtitles.get(video, [])
        if not matches:
            if progress_cb is not None:
                progress_cb(f"no match from {provider}, trying next")
            continue

        provider_name = getattr(matches[0], "provider_name", provider)
        if progress_cb is not None:
            progress_cb(f"saving subtitle from {provider_name}")

        try:
            saved = save_subtitles(
                save_target,
                matches,
                encoding=encoding,
                subtitle_format="srt",
                language_format="alpha2",
            )
        except OSError as exc:
            had_errors = True
            logging.warning("Could not save subtitle for %s: %s", video.name, exc)
            continue
        if saved:
            return ("downloaded", provider_name)

        had_errors = True

    return ("failed", None) if had_errors else ("not_found", None)


def fetch_subtitle_for_video(
    video_path: Path,
    languages: list[Language],
    providers: list[str],
    provider_configs: dict[str, dict[str, str]],
    encoding: str,
    detailed_progress: bool,
    ledger: ProgressLedger | None = None,
    progress_cb: Callable[[str], None] | None = None,
) -> tuple[str, Language | None, str | None]:
    try:
        video = scan_video(str(video_path))
    except GuessingError as exc:
        logging.warning("Could not parse video metadata for %s: %s", video_path.name, exc)
        return ("failed", None, None)
    except Exception as exc:  # pragma: no cover - keep the batch running on unexpected scan failures
        logging.exception("Unexpected scan error for %s", video_path.name)
        logging.debug("Unexpected exception details: %s", exc)
        return ("failed", None, None)

    # Enrich the video with a file hash (and embedded metadata) so providers can
    # return release-accurate matches. Best-effort: a refiner failure must not
    # stop the search.
    try:
        refine(video, refiners=DEFAULT_REFINERS)
    except Exception as exc:  # pragma: no cover - refinement is advisory
        logging.debug("Refinement failed for %s: %s", video_path.name, exc)

    keyword_video = build_keyword_query_video(video)
    had_errors = False
    searched_any = False
    skipped_recent = False

    for language in languages:
        language_code = _language_code(language)

        if has_subtitle_for_language(video_path, language):
            if ledger is not None:
                ledger.record(video_path, language_code, "exists")
            if progress_cb is not None:
                progress_cb(f"subtitle already exists for {language}")
            return ("exists", language, None)

        if ledger is not None and ledger.should_skip(video_path, language_code):
            skipped_recent = True
            if progress_cb is not None:
                progress_cb(f"recently checked {language}, skipping")
            continue

        searched_any = True
        language_failed = False

        # Prefer providers that actually serve this language (drops e.g. the
        # Spanish-only providers for a Swedish search).
        language_providers = order_providers_for_language(providers, language_code)

        status, provider_name = try_download_for_language(
            video,
            language,
            language_providers,
            provider_configs,
            encoding,
            detailed_progress,
            query_label="full filename",
            progress_cb=progress_cb,
        )
        if status == "downloaded":
            if ledger is not None:
                ledger.record(video_path, language_code, "downloaded")
            return ("downloaded", language, provider_name)
        if status == "failed":
            language_failed = True

        if keyword_video is not None:
            status, provider_name = try_download_for_language(
                keyword_video,
                language,
                language_providers,
                provider_configs,
                encoding,
                detailed_progress,
                query_label="keyword fallback",
                save_video=video,
                progress_cb=progress_cb,
            )
            if status == "downloaded":
                if ledger is not None:
                    ledger.record(video_path, language_code, "downloaded")
                return ("downloaded", language, provider_name)
            if status == "failed":
                language_failed = True

        if language_failed:
            had_errors = True
            # Don't cache failures: they are usually transient (a provider was
            # down), so the language should be retried on the next run.
        elif ledger is not None:
            ledger.record(video_path, language_code, "not_found")

    if had_errors:
        return ("failed", None, None)
    if searched_any:
        return ("not_found", None, None)
    if skipped_recent:
        return ("skipped_recent", None, None)
    return ("not_found", None, None)


def sync_tools_available() -> bool:
    """True when both ffsubsync and ffmpeg are on PATH."""
    return bool(shutil.which("ffsubsync") and shutil.which("ffmpeg"))


def sync_subtitle(video_path: Path, subtitle_path: Path) -> bool:
    """Align ``subtitle_path`` to ``video_path`` with ffsubsync, in place.

    Writes to a temp file and replaces the original only on success, so a failed
    or interrupted sync never corrupts the downloaded subtitle. Returns True on
    a successful re-sync.
    """
    tmp = subtitle_path.with_name(subtitle_path.name + ".synced.tmp")
    try:
        proc = subprocess.run(
            ["ffsubsync", str(video_path), "-i", str(subtitle_path), "-o", str(tmp)],
            capture_output=True,
            timeout=900,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        logging.warning("Subtitle sync failed for %s: %s", subtitle_path.name, exc)
        return False
    if proc.returncode == 0 and tmp.exists():
        try:
            os.replace(tmp, subtitle_path)
            return True
        except OSError as exc:
            logging.warning("Could not replace subtitle after sync for %s: %s", subtitle_path.name, exc)
    else:
        logging.warning("ffsubsync exited %s for %s", proc.returncode, subtitle_path.name)
    try:
        tmp.unlink()
    except OSError:
        pass
    return False


def _subtitle_path_for(video_path: Path, language: Language) -> Path:
    return video_path.parent / f"{video_path.stem}.{_language_code(language)}.srt"


def process_video(
    video_path: Path,
    *,
    languages: list[Language],
    providers: list[str],
    provider_configs: dict[str, dict[str, str]],
    encoding: str,
    detailed_progress: bool,
    ledger: ProgressLedger | None,
    sync: bool,
    progress_cb: Callable[[str], None] | None = None,
) -> tuple[str, Language | None, str | None, bool]:
    """Fetch a subtitle and, when enabled, sync it. Runs in a worker thread.

    Returns ``(status, language, provider, synced)``; never touches the UI or
    run stats (the main thread owns those).
    """
    result, language, provider = fetch_subtitle_for_video(
        video_path=video_path,
        languages=languages,
        providers=providers,
        provider_configs=provider_configs,
        encoding=encoding,
        detailed_progress=detailed_progress,
        ledger=ledger,
        progress_cb=progress_cb,
    )
    synced = False
    if result == "downloaded" and sync and language is not None:
        subtitle_path = _subtitle_path_for(video_path, language)
        if subtitle_path.exists():
            if progress_cb is not None:
                progress_cb(f"syncing {language}")
            synced = sync_subtitle(video_path, subtitle_path)
    return result, language, provider, synced


def _apply_result(
    ui: StatusUI,
    stats: RunStats,
    video_path: Path,
    result: str,
    downloaded_language: Language | None,
    provider_name: str | None,
    synced: bool = False,
) -> None:
    """Fold a single video's outcome into the run stats and recent-results UI."""
    if result == "downloaded":
        stats.downloaded += 1
        if synced:
            stats.synced += 1
        suffix = " [synced]" if synced else ""
        if provider_name is not None:
            stats.provider_downloads[provider_name] += 1
            ui.add_result(
                f"downloaded {video_path.name} ({downloaded_language}) from {provider_name}{suffix}"
            )
        else:
            ui.add_result(f"downloaded {video_path.name} ({downloaded_language}){suffix}")
    elif result == "exists":
        stats.skipped_existing += 1
        ui.add_result(f"skipped {video_path.name}")
    elif result == "skipped_recent":
        stats.skipped_recent += 1
        ui.add_result(f"skipped {video_path.name} (checked recently)")
    elif result == "not_found":
        stats.not_found += 1
        ui.add_result(f"not found {video_path.name}")
    else:
        stats.failed += 1
        ui.add_result(f"failed {video_path.name}")


def main(argv: list[str] | None = None) -> int:
    try:
        args = parse_args(argv)
        config, config_path = load_config(args.config)
        runtime = resolve_runtime_options(args, config)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2

    provider_configs = merge_provider_configs(config.get("providers", {}))
    providers = resolve_providers(
        runtime["providers"],
        provider_configs,
        runtime["only_selected_providers"],
    )

    if args.list_providers:
        print_provider_report(runtime, provider_configs, providers)
        return 0

    if args.print_effective_config:
        print_effective_config(config_path, runtime, provider_configs, providers)
        return 0

    configure_logging(runtime["verbose"])

    try:
        languages = load_languages(runtime["languages"])
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2

    try:
        root = Path(runtime["path"]).expanduser().resolve()
    except OSError as exc:
        # Resolving a relative path (the default ".") calls os.getcwd(), which
        # raises if the working directory no longer exists — e.g. a network
        # share that disconnected while the shell was still inside it.
        print(
            f"Cannot access the scan path '{runtime['path']}': {exc}.\n"
            "If you were in a network folder that disconnected, reconnect it "
            "or cd to a directory that exists and try again.",
            file=sys.stderr,
        )
        return 2
    if not root.exists() or not root.is_dir():
        print(f"Scan path does not exist or is not a directory: {root}", file=sys.stderr)
        return 2

    cache_dir = configure_cache(root)
    ledger = ProgressLedger(
        path=cache_dir / "progress.json",
        recheck_after_seconds=runtime["recheck_after_days"] * 86400,
        reset=runtime["clean"],
    )

    ui = StatusUI(enabled=not runtime["verbose"])
    ui.print_splash(root, languages, providers)

    stats = RunStats()
    interrupted = False
    jobs = runtime["jobs"]
    rate = RateLimiter(runtime["min_request_interval"])

    sync_enabled = runtime["sync"]
    if sync_enabled and not sync_tools_available():
        print(
            "--sync requested but ffsubsync and/or ffmpeg were not found on PATH; "
            "continuing without subtitle sync.",
            file=sys.stderr,
        )
        sync_enabled = False

    def work(
        video_path: Path,
        progress_cb: Callable[[str], None] | None = None,
    ) -> tuple[str, Language | None, str | None, bool]:
        # Worker body: network + optional sync. Touches the (lock-protected)
        # ledger but never the UI/stats — those are mutated on the main thread.
        rate.wait()
        return process_video(
            video_path,
            languages=languages,
            providers=providers,
            provider_configs=provider_configs,
            encoding=runtime["encoding"],
            detailed_progress=runtime["detailed_progress"],
            ledger=ledger,
            sync=sync_enabled,
            progress_cb=progress_cb,
        )

    ui.start("Warming up subtitle engines...", stats, detail_text="starting up")
    try:
        if jobs <= 1:
            for video_path in iter_video_files(root):
                current_line = f"Scanning {video_path.name}..."
                ui.update(current_line, stats, detail_text="queued")

                # Bind current_line via default arg so the closure captures
                # this iteration's value (called synchronously below).
                def set_detail(detail: str, _line: str = current_line) -> None:
                    ui.update(_line, stats, detail_text=detail)

                stats.scanned += 1
                result, downloaded_language, provider_name, synced = work(video_path, progress_cb=set_detail)
                _apply_result(ui, stats, video_path, result, downloaded_language, provider_name, synced)
                ui.update(current_line, stats, detail_text=f"completed: {result}")
                if stats.scanned % 25 == 0:
                    ledger.save()
        else:
            # Concurrent: a bounded pool of workers, results folded in on the
            # main thread as they complete. Bound submission to ~2x jobs ahead
            # since iter_video_files is a generator over a possibly-huge tree.
            videos = iter(iter_video_files(root))
            executor = concurrent.futures.ThreadPoolExecutor(max_workers=jobs)
            futures: dict[concurrent.futures.Future, Path] = {}
            try:
                for video_path in itertools.islice(videos, jobs * 2):
                    futures[executor.submit(work, video_path)] = video_path
                while futures:
                    done, _ = concurrent.futures.wait(futures, return_when=concurrent.futures.FIRST_COMPLETED)
                    for fut in done:
                        finished_path = futures.pop(fut)
                        stats.scanned += 1
                        try:
                            result, downloaded_language, provider_name, synced = fut.result()
                        except Exception:
                            logging.exception("Worker failed for %s", finished_path.name)
                            result, downloaded_language, provider_name, synced = (
                                "failed",
                                None,
                                None,
                                False,
                            )
                        _apply_result(
                            ui,
                            stats,
                            finished_path,
                            result,
                            downloaded_language,
                            provider_name,
                            synced,
                        )
                        ui.update(
                            f"Scanning ({stats.scanned} done, {jobs} workers)...",
                            stats,
                            detail_text=finished_path.name,
                        )
                        if stats.scanned % 25 == 0:
                            ledger.save()
                        next_path = next(videos, None)
                        if next_path is not None:
                            futures[executor.submit(work, next_path)] = next_path
            finally:
                # cancel_futures cancels queued-but-unstarted work; in-flight
                # searches (<= jobs) are allowed to finish.
                executor.shutdown(wait=True, cancel_futures=True)
    except KeyboardInterrupt:
        interrupted = True
        ui.update("Interrupted by user. Cleaning up...", stats, detail_text="cancelled by user")
    finally:
        # Always flush progress so a Ctrl+C or unexpected error still resumes.
        ledger.save(force=True)
        ui.stop()

    print()
    ui.print_summary(stats, interrupted)

    hint = coverage_hint(stats, provider_configs)
    if hint is not None:
        print(f"\nTip: {hint}")

    if interrupted:
        return 130
    return 0 if stats.failed == 0 else 1


def run() -> int:
    try:
        return main()
    except KeyboardInterrupt:
        # main handles Ctrl+C during the scan; this guards the setup phase too.
        return 130
    except Exception:
        import traceback

        print(
            "\nSRT Downloader hit an unexpected error and had to stop.\n"
            f"This is a bug — please report it at:\n  {ISSUES_URL}\n"
            "Include the command you ran and the details below:\n",
            file=sys.stderr,
        )
        traceback.print_exc()
        return 70  # EX_SOFTWARE


if __name__ == "__main__":
    raise SystemExit(run())
