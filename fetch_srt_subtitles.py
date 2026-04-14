#!/usr/bin/env python3

from __future__ import annotations

import argparse
from collections import Counter, deque
import json
import logging
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable

import yaml
from babelfish import Language
from subliminal import VIDEO_EXTENSIONS, download_best_subtitles, region, save_subtitles, scan_video
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

DEFAULT_PROVIDERS = [
    "podnapisi",
    "tvsubtitles",
    "subtitulamos",
    "gestdown",
    "subtis",
]

DEFAULT_CONFIG_FILES = [
    "srt-downloader.yaml",
    ".srt-downloader.yaml",
]

APP_VERSION = "0.1.0"


@dataclass
class RunStats:
    scanned: int = 0
    downloaded: int = 0
    skipped_existing: int = 0
    not_found: int = 0
    failed: int = 0
    provider_downloads: Counter[str] = field(default_factory=Counter)


class StatusUI:
    def __init__(self, enabled: bool = True) -> None:
        self.enabled = bool(enabled and HAS_RICH)
        self.console = Console() if self.enabled else None
        self.live = None
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
            f"Not found: {stats.not_found}",
            f"Failed: {stats.failed}",
        ]

        if stats.provider_downloads:
            provider_parts = [
                f"{provider}: {count}"
                for provider, count in stats.provider_downloads.most_common()
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
                str(key): str(value)
                for key, value in credentials.items()
                if value is not None
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
    }
    return runtime


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
    print(
        "Public fallback providers: "
        f"{', '.join(public_fallback) if public_fallback else '(disabled)'}"
    )
    print(f"Effective provider order: {', '.join(providers) if providers else '(none)'}")


def print_effective_config(
    config_path: Path | None,
    runtime: dict[str, Any],
    provider_configs: dict[str, dict[str, str]],
    providers: list[str],
) -> None:
    effective = {
        "version": APP_VERSION,
        "config_file": str(config_path.resolve()) if config_path is not None else None,
        "path": str(Path(runtime["path"]).expanduser().resolve()),
        "languages": runtime["languages"],
        "encoding": runtime["encoding"],
        "verbose": runtime["verbose"],
        "detailed_progress": runtime["detailed_progress"],
        "only_selected_providers": runtime["only_selected_providers"],
        "selected_providers": runtime["providers"],
        "credentialed_providers": sorted(provider_configs.keys()),
        "effective_providers": providers,
    }
    print(json.dumps(effective, indent=2, sort_keys=True))


def configure_logging(verbose: bool) -> None:
    root_level = logging.DEBUG if verbose else logging.ERROR
    logging.basicConfig(level=root_level, format="%(levelname)s: %(message)s")

    if not verbose:
        # Keep provider/library chatter out of the live UI in normal mode.
        logging.getLogger("subliminal").setLevel(logging.ERROR)
        logging.getLogger("guessit").setLevel(logging.ERROR)
        logging.getLogger("babelfish").setLevel(logging.ERROR)


def configure_cache(root: Path) -> None:
    cache_dir = root / ".subtitle-cache"
    cache_dir.mkdir(exist_ok=True)
    region.configure("dogpile.cache.dbm", arguments={"filename": str(cache_dir / "cache.dbm")})


def iter_video_files(root: Path) -> Iterable[Path]:
    video_extensions = {extension.lower() for extension in VIDEO_EXTENSIONS}
    for path in root.rglob("*"):
        if path.is_file() and path.suffix.lower() in video_extensions:
            yield path


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

    for subtitle_path in video_path.parent.glob(f"{basename}*.srt"):
        name = subtitle_path.name
        if name == f"{basename}.srt" or name.startswith(f"{basename}."):
            results.append(subtitle_path)

    return sorted(results)


def has_subtitle_for_language(video_path: Path, language: Language) -> bool:
    basename = video_path.stem.lower()
    language_code = language.alpha2.lower()

    for subtitle_path in existing_subtitle_paths(video_path):
        name = subtitle_path.name.lower()

        if name == f"{basename}.{language_code}.srt":
            return True

        if language_code == "en" and name == f"{basename}.srt":
            return True

    return False


def build_keyword_query_video(video):
    video_cls = type(video)
    fromname = getattr(video_cls, "fromname", None)
    if fromname is None:
        return None

    keyword_name: str | None = None

    series = getattr(video, "series", None)
    season = getattr(video, "season", None)
    episode = getattr(video, "episode", None)
    if series and season is not None and episode is not None:
        keyword_name = f"{series} S{int(season):02d}E{int(episode):02d}"
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

        saved = save_subtitles(
            save_target,
            matches,
            encoding=encoding,
            subtitle_format="srt",
            language_format="alpha2",
        )
        if not saved:
            return ("failed", None)

        return ("downloaded", provider_name)

    had_errors = False

    for index, provider in enumerate(providers, start=1):
        if progress_cb is not None:
            progress_cb(
                f"searching {language} via {provider} ({index}/{len(providers)}) ({query_label})"
            )

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

        saved = save_subtitles(
            save_target,
            matches,
            encoding=encoding,
            subtitle_format="srt",
            language_format="alpha2",
        )
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

    keyword_video = build_keyword_query_video(video)
    had_errors = False

    for language in languages:
        if has_subtitle_for_language(video_path, language):
            if progress_cb is not None:
                progress_cb(f"subtitle already exists for {language}")
            return ("exists", language, None)

        status, provider_name = try_download_for_language(
            video,
            language,
            providers,
            provider_configs,
            encoding,
            detailed_progress,
            query_label="full filename",
            progress_cb=progress_cb,
        )
        if status == "downloaded":
            return ("downloaded", language, provider_name)
        if status == "failed":
            had_errors = True

        if keyword_video is None:
            continue

        status, provider_name = try_download_for_language(
            keyword_video,
            language,
            providers,
            provider_configs,
            encoding,
            detailed_progress,
            query_label="keyword fallback",
            save_video=video,
            progress_cb=progress_cb,
        )
        if status == "downloaded":
            return ("downloaded", language, provider_name)
        if status == "failed":
            had_errors = True

    return ("failed", None, None) if had_errors else ("not_found", None, None)


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

    root = Path(runtime["path"]).expanduser().resolve()
    if not root.exists() or not root.is_dir():
        print(f"Scan path does not exist or is not a directory: {root}", file=sys.stderr)
        return 2

    configure_cache(root)

    ui = StatusUI(enabled=not runtime["verbose"])
    ui.print_splash(root, languages, providers)

    stats = RunStats()
    interrupted = False
    ui.start("Warming up subtitle engines...", stats, detail_text="starting up")
    try:
        for video_path in iter_video_files(root):
            current_line = f"Scanning {video_path.name}..."
            ui.update(current_line, stats, detail_text="queued")

            def set_detail(detail: str) -> None:
                ui.update(current_line, stats, detail_text=detail)

            stats.scanned += 1
            result, downloaded_language, provider_name = fetch_subtitle_for_video(
                video_path=video_path,
                languages=languages,
                providers=providers,
                provider_configs=provider_configs,
                encoding=runtime["encoding"],
                detailed_progress=runtime["detailed_progress"],
                progress_cb=set_detail,
            )

            if result == "downloaded":
                stats.downloaded += 1
                if provider_name is not None:
                    stats.provider_downloads[provider_name] += 1
                    ui.add_result(
                        f"downloaded {video_path.name} ({downloaded_language}) from {provider_name}"
                    )
                else:
                    ui.add_result(f"downloaded {video_path.name} ({downloaded_language})")
                ui.update(current_line, stats, detail_text="completed: downloaded")
            elif result == "exists":
                stats.skipped_existing += 1
                ui.add_result(f"skipped {video_path.name}")
                ui.update(current_line, stats, detail_text="completed: skipped")
            elif result == "not_found":
                stats.not_found += 1
                ui.add_result(f"not found {video_path.name}")
                ui.update(current_line, stats, detail_text="completed: not found")
            else:
                stats.failed += 1
                ui.add_result(f"failed {video_path.name}")
                ui.update(current_line, stats, detail_text="completed: failed")
    except KeyboardInterrupt:
        interrupted = True
        ui.update("Interrupted by user. Cleaning up...", stats, detail_text="cancelled by user")
    finally:
        ui.stop()

    print()
    ui.print_summary(stats, interrupted)

    if interrupted:
        return 130
    return 0 if stats.failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())