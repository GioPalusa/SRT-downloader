# SRT Downloader

<img width="846" height="429" alt="Screenshot" src="https://github.com/user-attachments/assets/fbca22f4-deef-4ea5-949a-cb8de8f690bf" />

Download subtitles for local video files, recursively.

The tool scans a folder tree, finds video files, searches subtitle providers, and saves subtitles next to each video.

## Install

### macOS

```bash
curl -fsSL https://raw.githubusercontent.com/GioPalusa/SRT-downloader/main/install.sh | sh
```

The installer downloads the latest GitHub release binary for your Mac, installs it as `srt-download`, and adds the install directory to your `PATH` when needed.

### Windows

```powershell
irm https://raw.githubusercontent.com/GioPalusa/SRT-downloader/main/install.ps1 | iex
```

The installer downloads the latest GitHub release binary, installs `srt-download.exe`, and adds it to your user `PATH`.

### Python Install Alternative

```bash
pipx install git+https://github.com/GioPalusa/SRT-downloader.git
```

That gives you the same `srt-download` command through Python instead of a standalone binary.

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
- `--config /path/to/srt-downloader.yaml` Load settings from a YAML config file.
- `--list-providers` Print the final provider order and exit.
- `--print-effective-config` Print merged runtime settings and exit.
- `--verbose` Enable debug logging.
- `--version` Print the current version.

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
- macOS standalone binaries for Intel and Apple Silicon
- Windows standalone binaries for x64

Tagging a release like `vX.Y.Z` publishes those artifacts to GitHub Releases, which is what the one-line installers consume.

## Troubleshooting

- If nothing is found, try a different language, more providers, or provider credentials.
- If you want strict provider control, combine `-p` with `--only-selected-providers`.
- If you need to inspect provider order before scanning, run `srt-download --list-providers`.
- Press `Ctrl+C` to stop safely. The tool exits cleanly and prints a partial summary.
