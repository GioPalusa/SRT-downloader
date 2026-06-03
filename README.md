# SRT Downloader

<img width="846" height="429" alt="Screenshot" src="https://github.com/user-attachments/assets/fbca22f4-deef-4ea5-949a-cb8de8f690bf" />

Download subtitles for local video files, recursively.

The tool scans a folder tree, finds video files, searches subtitle providers, and saves subtitles next to each video.

## Install

> The standalone macOS binary and the Homebrew formula are built for **Apple Silicon only**. On an Intel Mac, use the [Python install](#python-install-alternative) instead.

### Homebrew (macOS)

```bash
brew install GioPalusa/homebrew-tap/srt-download
```

### Direct macOS Installer

```bash
curl -fsSL https://raw.githubusercontent.com/GioPalusa/SRT-downloader/main/install.sh | sh
```

The installer downloads the latest GitHub release binary for your Apple Silicon Mac, installs it as `srt-download`, strips the Gatekeeper quarantine flag so the first run is not blocked, and adds the install directory to your `PATH` when needed.

Pin a specific version or change the install location with environment variables:

```bash
SRT_DOWNLOADER_VERSION=v0.1.0 curl -fsSL https://raw.githubusercontent.com/GioPalusa/SRT-downloader/main/install.sh | sh
SRT_DOWNLOADER_INSTALL_DIR="$HOME/bin" curl -fsSL https://raw.githubusercontent.com/GioPalusa/SRT-downloader/main/install.sh | sh
```

### Winget (Windows)

```powershell
winget install GioPalusa.SRTDownloader
```

> Pending acceptance into the [WinGet Community Repository](https://github.com/microsoft/winget-pkgs). Until the package is merged, use the [Direct Windows Installer](#direct-windows-installer) below.

### Direct Windows Installer

```powershell
irm https://raw.githubusercontent.com/GioPalusa/SRT-downloader/main/install.ps1 | iex
```

The installer downloads the latest GitHub release binary, installs `srt-download.exe`, clears the Mark-of-the-Web so SmartScreen does not block the first run, and adds the install directory to your user `PATH`.

Pin a specific version or change the install location with environment variables:

```powershell
$env:SRT_DOWNLOADER_VERSION = 'v0.1.0'; irm https://raw.githubusercontent.com/GioPalusa/SRT-downloader/main/install.ps1 | iex
$env:SRT_DOWNLOADER_INSTALL_DIR = "$HOME\bin"; irm https://raw.githubusercontent.com/GioPalusa/SRT-downloader/main/install.ps1 | iex
```

### Python Install Alternative

```bash
pipx install git+https://github.com/GioPalusa/SRT-downloader.git
```

That gives you the same `srt-download` command through Python instead of a standalone binary.

## Uninstall

### Homebrew (macOS)

```bash
brew uninstall srt-download
```

### Direct macOS Installer

```bash
curl -fsSL https://raw.githubusercontent.com/GioPalusa/SRT-downloader/main/uninstall.sh | sh
```

Removes the binary and the `PATH` entry the installer added. Honors `SRT_DOWNLOADER_INSTALL_DIR` if you used a custom install location.

### Winget (Windows)

```powershell
winget uninstall GioPalusa.SRTDownloader
```

### Direct Windows Installer

```powershell
irm https://raw.githubusercontent.com/GioPalusa/SRT-downloader/main/uninstall.ps1 | iex
```

Removes the binary, the install directory if empty, and the user `PATH` entry.

### Python Install Alternative

```bash
pipx uninstall srt-downloader
```

## Usage

```bash
srt-download [path] [options]
```

Examples:

```bash
srt-download
srt-download --language sv
srt-download "/path/to/videos"
srt-download -p opensubtitlescom
srt-download --detailed-progress
```

Useful options:

- `-l, --language sv` Set the primary language. English is added automatically as fallback.
- `-p, --provider NAME` Prioritize one or more providers. Repeat the flag to set order.
- `--only-selected-providers` Disable public fallback providers.
- `-j, --jobs N` Process N videos in parallel (default 4; use 1 for sequential with detailed progress).
- `--min-request-interval SECONDS` Minimum delay between searches across workers, to stay polite to providers.
- `--sync` Auto-correct subtitle timing with ffsubsync after download (requires ffsubsync and ffmpeg on PATH).
- `--config /path/to/srt-downloader.yaml` Load settings from a YAML config file.
- `--clean` Ignore and reset saved progress; re-search every video from scratch.
- `--recheck-after DAYS` Days before a previously not-found video is searched again (default 14).
- `--list-providers` Print the final provider order and exit.
- `--print-effective-config` Print merged runtime settings and exit.
- `--verbose` Enable debug logging.
- `--version` Print the current version.

## Resuming Interrupted Runs

Scanning a large library can take a while, so the tool keeps a progress ledger
(`.subtitle-cache/progress.json` inside the scan folder). For each video it
records, per language, whether a subtitle was downloaded, already existed, or
was not found.

On the next run it skips:

- videos whose subtitles already exist, and
- videos that were **not found** within the last `--recheck-after` days (14 by default).

So if a run is interrupted (`Ctrl+C`, a crash, or a disconnected drive), just
run the same command again — it picks up roughly where it left off instead of
re-searching everything. Failures (a provider being down) are never cached, so
those are always retried.

Use `--clean` to reset saved progress and re-search everything from scratch
(equivalent to deleting `.subtitle-cache`). If the scan folder is read-only,
the cache falls back to a temporary directory automatically.

Run full help:

```bash
srt-download --help
```

## Config File

If `--config` is not provided, the tool automatically looks for:

- `srt-downloader.yaml`
- `.srt-downloader.yaml`

Example:

```yaml
path: .
languages:
  - sv
  - en
selected_providers:
  - opensubtitlescom
providers:
  opensubtitlescom:
    username: your_username
    password: your_password
only_selected_providers: false
detailed_progress: false
verbose: false
encoding: utf-8
recheck_after_days: 14
jobs: 4
min_request_interval: 0
sync: false
```

CLI flags override config values.

## Provider Credentials

Public providers work without accounts. If you have provider credentials, either place them in the YAML config or export them in your shell:

```bash
export OPENSUBTITLESCOM_USERNAME="your_username"
export OPENSUBTITLESCOM_PASSWORD="your_password"
export OPENSUBTITLES_USERNAME="your_username"
export OPENSUBTITLES_PASSWORD="your_password"
export ADDIC7ED_USERNAME="your_username"
export ADDIC7ED_PASSWORD="your_password"
```

Environment credentials override config credentials for the same provider.

## How It Searches

For each language, the downloader tries:

1. The full filename.
2. A simplified keyword query fallback.

If English is not already in your configured language list, it is appended automatically as the last fallback.

Existing subtitles are checked per language. A plain `.srt` file is treated as English for compatibility.

## Build And Release

To build locally:

```bash
python3 -m pip install '.[build]'
python3 -m build
pyinstaller fetch_srt_subtitles.spec
```

That produces:

- A wheel and source distribution in `dist/`
- A standalone executable in `dist/`

GitHub Actions now builds:

- Python packages on Ubuntu
- macOS standalone binaries for Apple Silicon
- Windows standalone binaries for x64

Intel Macs are not covered by the standalone binary or Homebrew formula; use the pipx install instead.

Tagged releases can also publish to package managers:

- Homebrew by updating `srt-download.rb` in your Homebrew tap repository
- WinGet by submitting the Windows release asset under the `GioPalusa.SRTDownloader` package identifier

To enable package-manager publishing, configure:

- Repository secret `HOMEBREW_TAP_GITHUB_TOKEN`: token with push access to your tap repository
- Repository variable `HOMEBREW_TAP_REPOSITORY`: optional override for the tap repository, defaults to `GioPalusa/homebrew-tap`
- Repository secret `WINGET_TOKEN`: classic PAT with `public_repo` scope
- Repository variable `WINGET_PACKAGE_IDENTIFIER`: optional override for the package identifier, defaults to `GioPalusa.SRTDownloader`
- Repository variable `WINGET_FORK_USER`: optional override for the account that owns your `winget-pkgs` fork

Homebrew publishing expects a tap repository such as `GioPalusa/homebrew-tap` with a `Formula/` directory.

WinGet publishing uses `vedantmgoyal9/winget-releaser`, so you need a fork of `microsoft/winget-pkgs` under the same account and one accepted initial package submission before automatic updates can take over.

Tagging a release like `vX.Y.Z` publishes those artifacts to GitHub Releases, which is what the one-line installers consume.

### Code signing (optional)

The standalone binaries are unsigned by default, which triggers macOS Gatekeeper
and Windows SmartScreen prompts (the installers work around this). The release
workflow includes **secret-gated** signing that activates only when the relevant
secrets are present — without them, builds ship unsigned exactly as before.

macOS (Developer ID + notarization, requires an Apple Developer account):

- `APPLE_CERTIFICATE_P12` — base64 of your Developer ID Application `.p12`
- `APPLE_CERTIFICATE_PASSWORD` — its export password
- `APPLE_SIGNING_IDENTITY` — e.g. `Developer ID Application: Your Name (TEAMID)`
- `APPLE_NOTARY_API_KEY` — base64 of your App Store Connect API key `.p8`
- `APPLE_NOTARY_API_KEY_ID`, `APPLE_NOTARY_API_ISSUER` — that key's IDs

Windows (Authenticode):

- `WINDOWS_CERT_PFX_BASE64` — base64 of a code-signing `.pfx`
- `WINDOWS_CERT_PASSWORD` — its password

A bare macOS CLI binary can't be stapled (only bundles/`.pkg`/`.dmg`), so it is
notarized for the online Gatekeeper check; wrapping it in a notarized+stapled
`.pkg` is a possible future enhancement. For Windows OSS projects without a paid
certificate, [SignPath Foundation](https://signpath.org) offers free signing.

## Troubleshooting

- If nothing is found, try a different language, more providers, or provider credentials.
- If you want strict provider control, combine `-p` with `--only-selected-providers`.
- If you need to inspect provider order before scanning, run `srt-download --list-providers`.
- Press `Ctrl+C` to stop safely. The tool exits cleanly and prints a partial summary.
- If you hit an unexpected error, the tool prints a report link. Please file it at [the issue tracker](https://github.com/GioPalusa/SRT-downloader/issues) with the command you ran and the printed details.
- macOS blocks the binary with "cannot be opened because the developer cannot be verified" if you downloaded it manually instead of through the installer. Clear the quarantine flag with `xattr -d com.apple.quarantine /path/to/srt-download`.
- Windows SmartScreen warning on first run is expected for unsigned binaries. The installer calls `Unblock-File`; if you downloaded the exe manually, right-click the file > Properties > tick **Unblock**, then re-run.
