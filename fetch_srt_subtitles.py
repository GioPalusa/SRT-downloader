#!/usr/bin/env python3

from __future__ import annotations

import argparse
from collections import Counter, deque
import json
import logging
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable

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
    "srt-fetcher.json",
    ".srt-fetcher.json",
]

APP_VERSION = "0.1.0"


@dataclass
class RunStats:
    scanned: int = 0
    downloaded: int = 0
    skipped_existing: int = 0
    skipped_not_video: int = 0
    not_found: int = 0
    failed: int = 0
    provider_downloads: Counter[str] | None = None

    def __post_init__(self) -> None:
        if self.provider_downloads is None:
            self.provider_downloads = Counter()


class StatusUI:
    def __init__(self, enabled: bool = True) -> None:
        self.enabled = bool(enabled and HAS_RICH)
        self.console = Console() if self.enabled else None
        self.live = None
        self.recent_results: deque[str] = deque(maxlen=8)

    def print_splash(self, root: Path, primary_language: Language, providers: list[str]) -> None:
        if self.enabled and self.console is not None:
            splash = Text()
            splash.append("SRT Fetcher\n", style="bold magenta")
            splash.append(f"Root: {root}\n", style="cyan")
            splash.append(f"Primary: {primary_language}\n", style="green")
            splash.append("Fallback: en\n", style="yellow")
            splash.append(f"Providers: {', '.join(providers)}", style="white")
            self.console.print(Panel(splash, border_style="bright_blue", title="Live Mode"))
        else:
            print(f"Scanning {root}")
            print(f"Primary language: {primary_language}")
            print("Fallback language: en")
            print(f"Providers: {', '.join(providers)}")

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


def parse_args() -> argparse.Namespace:
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
        help="Folder to scan. Defaults to config path or current working directory.",
    )
    parser.add_argument(
        "--config",
        default=None,
        help=(
            "Optional path to a JSON config file. If omitted, the script auto-loads "
            "srt-fetcher.json or .srt-fetcher.json from the current directory when present."
        ),
    )
    parser.add_argument(
        "-l",
        "--language",
        default=None,
        help=(
            "Primary subtitle language as IETF code, for example en, nl, pt-BR. "
            "If that language is not found, the script falls back to English. Default: en."
        ),
    )
    parser.add_argument(
        "-p",
        "--provider",
        action="append",
        dest="providers",
        help=(
            "Subtitle provider to prioritize. Repeat to use multiple providers. "
            "By default, built-in public providers are still used as fallback and "
            "credentialed providers are auto-added when environment variables are present."
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
        help=(
            "Use only providers selected with --provider plus any credentialed providers "
            "detected from environment variables. Skip public-provider fallback."
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
    return parser.parse_args()


def load_config(config_arg: str | None) -> tuple[dict, Path | None]:
    config_path: Path | None = None

    if config_arg:
        config_path = Path(config_arg).expanduser().resolve()
        if not config_path.exists() or not config_path.is_file():
            raise SystemExit(f"Config file does not exist: {config_path}")
    else:
        cwd = Path.cwd()
        for candidate in DEFAULT_CONFIG_FILES:
            candidate_path = cwd / candidate
            if candidate_path.exists() and candidate_path.is_file():
                config_path = candidate_path
                break

    if config_path is None:
        return ({}, None)

    try:
        raw = json.loads(config_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SystemExit(f"Invalid JSON in config file {config_path}: {exc}") from exc
    except OSError as exc:
        raise SystemExit(f"Could not read config file {config_path}: {exc}") from exc

    if not isinstance(raw, dict):
        raise SystemExit(f"Config file must contain a JSON object: {config_path}")

    return (raw, config_path)


def resolve_runtime_options(args: argparse.Namespace, config: dict) -> dict:
    language = args.language if args.language is not None else config.get("language", "en")
    encoding = args.encoding if args.encoding is not None else config.get("encoding", "utf-8")
    scan_path = args.path if args.path is not None else config.get("path", ".")

    providers = args.providers if args.providers is not None else config.get("providers")
    if providers is not None and not isinstance(providers, list):
        raise SystemExit("Config key 'providers' must be a JSON array of provider names")
    if isinstance(providers, list):
        providers = [str(item) for item in providers]

    detailed_progress = (
        args.detailed_progress if args.detailed_progress is not None else bool(config.get("detailed_progress", False))
    )
    verbose = args.verbose if args.verbose is not None else bool(config.get("verbose", False))
    only_selected_providers = (
        args.only_selected_providers
        if args.only_selected_providers is not None
        else bool(config.get("only_selected_providers", False))
    )

    return {
        "language": str(language),
        "encoding": str(encoding),
        "path": str(scan_path),
        "providers": providers,
        "detailed_progress": detailed_progress,
        "verbose": verbose,
        "only_selected_providers": only_selected_providers,
    }


def print_provider_report(
    runtime: dict,
    provider_configs: dict[str, dict[str, str]],
    providers: list[str],
) -> None:
    selected = runtime["providers"] or []
    credentialed = sorted(provider_configs.keys())

    if selected:
        if runtime["only_selected_providers"]:
            public_fallback = []
        else:
            public_fallback = [name for name in DEFAULT_PROVIDERS if name not in selected]
    else:
        public_fallback = list(DEFAULT_PROVIDERS)

    print("Provider Report")
    print(f"Selected providers: {', '.join(selected) if selected else '(none)'}")
    print(
        "Public fallback providers: "
        f"{', '.join(public_fallback) if public_fallback else '(disabled)'}"
    )
    print(
        "Credentialed providers from environment: "
        f"{', '.join(credentialed) if credentialed else '(none)'}"
    )
    print(f"Effective provider order: {', '.join(providers) if providers else '(none)'}")


def print_effective_config(
    config_path: Path | None,
    runtime: dict,
    provider_configs: dict[str, dict[str, str]],
    providers: list[str],
) -> None:
    effective = {
        "version": APP_VERSION,
        "config_file": str(config_path) if config_path is not None else None,
        "path": str(Path(runtime["path"]).expanduser().resolve()),
        "language": runtime["language"],
        "encoding": runtime["encoding"],
        "verbose": runtime["verbose"],
        "detailed_progress": runtime["detailed_progress"],
        "only_selected_providers": runtime["only_selected_providers"],
        "selected_providers": runtime["providers"] or [],
        "credentialed_providers_from_env": sorted(provider_configs.keys()),
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


def load_language(language_code: str) -> Language:
    try:
        return Language.fromietf(language_code)
    except Exception as exc:  # pragma: no cover - defensive error message for invalid input
        raise SystemExit(f"Invalid language code: {language_code}") from exc


def provider_configs_from_env() -> dict[str, dict[str, str]]:
    provider_configs: dict[str, dict[str, str]] = {}

    opensubtitlescom_user = os.getenv("OPENSUBTITLESCOM_USERNAME")
    opensubtitlescom_pass = os.getenv("OPENSUBTITLESCOM_PASSWORD")
    if opensubtitlescom_user and opensubtitlescom_pass:
        provider_configs["opensubtitlescom"] = {
            "username": opensubtitlescom_user,
            "password": opensubtitlescom_pass,
        }

    opensubtitles_user = os.getenv("OPENSUBTITLES_USERNAME")
    opensubtitles_pass = os.getenv("OPENSUBTITLES_PASSWORD")
    if opensubtitles_user and opensubtitles_pass:
        provider_configs["opensubtitles"] = {
            "username": opensubtitles_user,
            "password": opensubtitles_pass,
        }

    addic7ed_user = os.getenv("ADDIC7ED_USERNAME")
    addic7ed_pass = os.getenv("ADDIC7ED_PASSWORD")
    if addic7ed_user and addic7ed_pass:
        provider_configs["addic7ed"] = {
            "username": addic7ed_user,
            "password": addic7ed_pass,
        }

    return provider_configs


def resolve_providers(
    cli_providers: list[str] | None,
    provider_configs: dict[str, dict[str, str]],
    only_selected_providers: bool,
) -> list[str]:
    credentialed = [name for name in ("opensubtitlescom", "opensubtitles", "addic7ed") if name in provider_configs]

    if cli_providers:
        # User-selected providers are always first.
        providers = list(cli_providers)

        # Unless strict mode is requested, keep default public providers as fallback.
        if not only_selected_providers:
            for provider_name in DEFAULT_PROVIDERS:
                if provider_name not in providers:
                    providers.append(provider_name)

        # Add authenticated providers discovered from environment variables.
        for provider_name in credentialed:
            if provider_name not in providers:
                providers.append(provider_name)
        return providers

    providers = list(DEFAULT_PROVIDERS)
    for provider_name in credentialed:
            providers.append(provider_name)

    return providers


def target_subtitle_path(video_path: Path) -> Path:
    return video_path.with_suffix(".srt")


def existing_subtitle_paths(video_path: Path) -> list[Path]:
    basename = video_path.stem
    results: list[Path] = []

    for subtitle_path in video_path.parent.glob(f"{basename}*.srt"):
        name = subtitle_path.name
        if name == f"{basename}.srt" or name.startswith(f"{basename}."):
            results.append(subtitle_path)

    return sorted(results)


def has_subtitle_for_language(video_path: Path, language: Language) -> bool:
    basename = video_path.stem
    lang = language.alpha2.lower()

    for subtitle_path in existing_subtitle_paths(video_path):
        name = subtitle_path.name.lower()

        if name == f"{basename.lower()}.{lang}.srt":
            return True

        # Treat a generic .srt as English for backward compatibility.
        if lang == "en" and name == f"{basename.lower()}.srt":
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

    return (("failed", None) if had_errors else ("not_found", None))


def fetch_subtitle_for_video(
    video_path: Path,
    primary_language: Language,
    providers: list[str],
    provider_configs: dict[str, dict[str, str]],
    encoding: str,
    detailed_progress: bool,
    progress_cb: Callable[[str], None] | None = None,
) -> tuple[str, Language | None, str | None]:
    try:
        if progress_cb is not None:
            progress_cb("scanning video metadata")
        video = scan_video(str(video_path))
    except GuessingError:
        logging.warning("Could not identify video metadata for %s", video_path)
        return ("failed", None, None)
    except ValueError:
        logging.warning("Could not scan %s", video_path)
        return ("failed", None, None)

    keyword_video = build_keyword_query_video(video)

    def try_language(language: Language) -> tuple[str, Language | None, str | None]:
        if progress_cb is not None:
            progress_cb(f"checking existing subtitle for {language}")
        if has_subtitle_for_language(video_path, language):
            return ("exists", None, None)

        if progress_cb is not None:
            progress_cb(f"trying language {language}")
        result, provider_name = try_download_for_language(
            video=video,
            language=language,
            providers=providers,
            provider_configs=provider_configs,
            encoding=encoding,
            detailed_progress=detailed_progress,
            query_label="full filename",
            save_video=video,
            progress_cb=progress_cb,
        )
        if result == "downloaded":
            return (result, language, provider_name)
        if result == "failed":
            return (result, language, provider_name)

        if keyword_video is not None:
            if progress_cb is not None:
                progress_cb("no full filename match, trying keyword search")
            keyword_result, keyword_provider_name = try_download_for_language(
                video=keyword_video,
                language=language,
                providers=providers,
                provider_configs=provider_configs,
                encoding=encoding,
                detailed_progress=detailed_progress,
                query_label="keyword",
                save_video=video,
                progress_cb=progress_cb,
            )
            if keyword_result == "downloaded":
                return (keyword_result, language, keyword_provider_name)
            if keyword_result == "failed":
                return (keyword_result, language, keyword_provider_name)

        return ("not_found", None, None)

    primary_result, primary_downloaded_language, primary_provider_name = try_language(primary_language)
    if primary_result in {"downloaded", "failed", "exists"}:
        return (primary_result, primary_downloaded_language, primary_provider_name)

    fallback_language = Language.fromietf("en")
    if primary_language != fallback_language:
        if progress_cb is not None:
            progress_cb("no primary match, switching to English fallback")
        logging.info(
            "No %s subtitle found for %s, trying English fallback",
            primary_language,
            video_path,
        )
        fallback_result, fallback_downloaded_language, fallback_provider_name = try_language(fallback_language)
        if fallback_result in {"downloaded", "failed", "exists"}:
            return (fallback_result, fallback_downloaded_language, fallback_provider_name)

    return ("not_found", None, None)


def main() -> int:
    args = parse_args()
    config, config_path = load_config(args.config)
    runtime = resolve_runtime_options(args, config)

    provider_configs = provider_configs_from_env()
    providers = resolve_providers(
        runtime["providers"],
        provider_configs,
        runtime["only_selected_providers"],
    )

    if args.list_providers:
        print_provider_report(runtime, provider_configs, providers)

    if args.print_effective_config:
        print_effective_config(config_path, runtime, provider_configs, providers)

    if args.list_providers or args.print_effective_config:
        return 0

    configure_logging(runtime["verbose"])

    root = Path(runtime["path"]).expanduser().resolve()
    if not root.exists() or not root.is_dir():
        print(f"Scan path does not exist or is not a directory: {root}", file=sys.stderr)
        return 2

    configure_cache(root)

    primary_language = load_language(runtime["language"])

    ui = StatusUI(enabled=not runtime["verbose"])
    ui.print_splash(root, primary_language, providers)

    stats = RunStats()
    interrupted = False
    last_result = "Ready"
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
                primary_language=primary_language,
                providers=providers,
                provider_configs=provider_configs,
                encoding=runtime["encoding"],
                detailed_progress=runtime["detailed_progress"],
                progress_cb=set_detail,
            )

            if result == "downloaded":
                stats.downloaded += 1
                if provider_name:
                    last_result = f"downloaded {video_path.name} ({downloaded_language}) from {provider_name}"
                    stats.provider_downloads[provider_name] += 1
                else:
                    last_result = f"downloaded {video_path.name} ({downloaded_language})"
                ui.add_result(last_result)
                ui.update(current_line, stats, detail_text="completed: downloaded")
            elif result == "exists":
                stats.skipped_existing += 1
                last_result = f"skipped {video_path.name}"
                ui.add_result(last_result)
                ui.update(current_line, stats, detail_text="completed: skipped")
            elif result == "not_found":
                stats.not_found += 1
                last_result = f"not found {video_path.name}"
                ui.add_result(last_result)
                ui.update(current_line, stats, detail_text="completed: not found")
            else:
                stats.failed += 1
                last_result = f"failed {video_path.name}"
                ui.add_result(last_result)
                ui.update(current_line, stats, detail_text="completed: failed")
    except KeyboardInterrupt:
        interrupted = True
        ui.update("Interrupted by user. Cleaning up...", stats, detail_text="cancelled by user")

    ui.stop()

    print()
    ui.print_summary(stats, interrupted)

    if interrupted:
        return 130

    return 0 if stats.failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())