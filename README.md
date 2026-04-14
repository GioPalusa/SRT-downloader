# SRT Downloader

<img width="846" height="429" alt="Skärmavbild 2026-04-14 kl  21 38 18" src="https://github.com/user-attachments/assets/fbca22f4-deef-4ea5-949a-cb8de8f690bf" />

Download subtitles for local video files, recursively.

The tool scans a folder tree, finds video files, searches online subtitle providers, and saves subtitles next to each video.

## Quick Start

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python3 fetch_srt_subtitles.py
```

That command scans the current folder and subfolders, tries English subtitles first, and writes files like:

- `Movie.mkv` -> `Movie.en.srt`

## Command Synopsis

```bash
python3 fetch_srt_subtitles.py [path] [options]
```

Common options:

- `-l, --language sv` Primary language (falls back to English if not found)
- `-p, --provider NAME` Prioritize one or more providers (repeat flag)
- `--only-selected-providers` Do not use public fallback providers
- `--config /path/to/srt-fetcher.json` Load settings from JSON config
- `--detailed-progress` Show per-provider progress (slower)
- `--verbose` Debug logging
- `--encoding utf-8` Subtitle file encoding
- `--list-providers` Show exactly which providers will be used
- `--print-effective-config` Show merged runtime config and exit
- `--version` Print version and exit

Run full help:

```bash
python3 fetch_srt_subtitles.py --help
```

## Getting Started

### 1. Scan current folder

```bash
python3 fetch_srt_subtitles.py
```

### 2. Choose a primary language (with English fallback)

```bash
python3 fetch_srt_subtitles.py --language sv
```

### 3. Scan a specific folder

```bash
python3 fetch_srt_subtitles.py "/path/to/videos"
```

### 4. See detailed provider-by-provider progress

```bash
python3 fetch_srt_subtitles.py --detailed-progress
```

## Practical Usage Examples

### Prioritize one provider, still keep fallback providers

```bash
python3 fetch_srt_subtitles.py -p opensubtitlescom
```

Behavior:

- Your selected providers are tried first.
- Public providers are still used as fallback.
- Credential-based providers are auto-added when credentials are exported.

### Use only selected providers (strict mode)

```bash
python3 fetch_srt_subtitles.py -p opensubtitlescom -p podnapisi --only-selected-providers
```

### Use a custom config file

```bash
python3 fetch_srt_subtitles.py --config /path/to/srt-fetcher.json
```

### Show provider setup before scanning

```bash
python3 fetch_srt_subtitles.py --list-providers
```

### Show effective runtime config (merged CLI + config file)

```bash
python3 fetch_srt_subtitles.py --print-effective-config
```

### Print version

```bash
python3 fetch_srt_subtitles.py --version
```

### Disable config behavior for one run

Any CLI option overrides config values. For example:

```bash
python3 fetch_srt_subtitles.py --config ./srt-fetcher.json --language en --no-detailed-progress
```

### Run from anywhere with a global command

```bash
mkdir -p ~/.local/bin
cat > ~/.local/bin/fetch-srt <<'EOF'
#!/usr/bin/env zsh
"/Users/palusa/Developer/STL fetcher/.venv/bin/python" "/Users/palusa/Developer/STL fetcher/fetch_srt_subtitles.py" "$@"
EOF
chmod +x ~/.local/bin/fetch-srt
```

Then use it from any folder:

```bash
fetch-srt . --language sv
```

## Config File

If `--config` is not provided, the tool automatically looks for one of these files in your current folder:

- `srt-fetcher.json`
- `.srt-fetcher.json`

Example:

```json
{
  "path": ".",
  "language": "sv",
  "providers": ["opensubtitlescom"],
  "only_selected_providers": false,
  "detailed_progress": false,
  "verbose": false,
  "encoding": "utf-8"
}
```

Precedence rule:

- Command-line flags win over config values.

## Provider Credentials (Optional)

Public providers work without accounts. If you have provider accounts, export credentials to improve hit rate:

```bash
export OPENSUBTITLESCOM_USERNAME="your_username"
export OPENSUBTITLESCOM_PASSWORD="your_password"
export OPENSUBTITLES_USERNAME="your_username"
export OPENSUBTITLES_PASSWORD="your_password"
export ADDIC7ED_USERNAME="your_username"
export ADDIC7ED_PASSWORD="your_password"
```

## How Matching Works

Per language, the tool uses two query stages:

1. Full filename style query
2. Simplified keyword query fallback

Example for `black-ish S01E02 The Talk.mp4`:

1. `black-ish S01E02 The Talk.mp4`
2. `black-ish S01E02.mp4`

Language flow:

1. Try primary language
2. If not found, try English fallback

## Existing Subtitle Rules

- Output subtitles are saved as `.language.srt` (for example `.sv.srt`, `.en.srt`).
- Existing subtitles are checked per language.
- If `.en.srt` exists and you request Swedish, it still searches for `.sv.srt`.
- A plain `.srt` is treated as English for compatibility.

## Terminal Output

The live UI shows:

- Current file and current action
- Recent completed file results
- Provider source on successful downloads
- Final summary, including per-provider download counts

Example recent line:

- `downloaded black-ish S01E15 The Dozens.mp4 (sv) from opensubtitles`

## Troubleshooting

### No subtitles found

- Try a different primary language.
- Enable fallback providers (avoid `--only-selected-providers`).
- Add provider credentials.
- Use `--detailed-progress` to see provider-level attempts.

### Too much output

- Avoid `--verbose` unless debugging.
- Keep default mode (faster and cleaner than detailed mode).

### Stop safely

Press `Ctrl+C` at any time. The tool exits cleanly and prints a partial summary.
