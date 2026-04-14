# SRT Downloader

<img width="846" height="429" alt="Skärmavbild 2026-04-14 kl  21 38 18" src="https://github.com/user-attachments/assets/fbca22f4-deef-4ea5-949a-cb8de8f690bf" />

This script scans the folder where you run it, walks through all subfolders, finds video files, searches online for matching subtitles, and saves the subtitle next to the video using the same basename.

It first searches in your chosen primary language. If nothing is found, it automatically falls back to English.


The default output uses a live colorful status panel with in-place updates and spinner animation, so the terminal stays clean while the scan is running.

Example:

- `Movies/Arrival.mkv` -> `Movies/Arrival.sv.srt` (or `Movies/Arrival.en.srt` on fallback)

## Install

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Run

Run it from the folder you want to scan:

```bash
python3 fetch_srt_subtitles.py
```

Choose another language:

```bash
python3 fetch_srt_subtitles.py --language nl
```

That example tries Dutch first, then English if Dutch is not found.

Scan a different folder:

```bash
python3 fetch_srt_subtitles.py "/path/to/videos"
```

Use a config file (optional):

```bash
python3 fetch_srt_subtitles.py --config /path/to/srt-fetcher.json
```

If `--config` is not passed, the script will auto-load `srt-fetcher.json` or `.srt-fetcher.json` from the current folder when present.

Example config file:

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

Use detailed per-provider progress updates (slower):

```bash
python3 fetch_srt_subtitles.py --language sv --detailed-progress
```

### Run From Anywhere (Global Command)

Create a global launcher command:

```bash
mkdir -p ~/.local/bin
cat > ~/.local/bin/fetch-srt <<'EOF'
#!/usr/bin/env zsh
"/Users/palusa/Developer/STL fetcher/.venv/bin/python" "/Users/palusa/Developer/STL fetcher/fetch_srt_subtitles.py" "$@"
EOF
chmod +x ~/.local/bin/fetch-srt
```

Then you can run from any folder:

```bash
fetch-srt . --language sv
```

## Optional Provider Accounts

The script works with public providers by default. If you have provider accounts, you can improve match coverage by exporting credentials before running it.

```bash
export OPENSUBTITLESCOM_USERNAME="your_username"
export OPENSUBTITLESCOM_PASSWORD="your_password"
export OPENSUBTITLES_USERNAME="your_username"
export OPENSUBTITLES_PASSWORD="your_password"
export ADDIC7ED_USERNAME="your_username"
export ADDIC7ED_PASSWORD="your_password"
```

If you also pass `--provider`, those providers are used first, and any providers with exported credentials are added automatically.

By default, public providers are still included as fallback. If you want to use only the providers you selected, add:

```bash
--only-selected-providers
```

## Notes

- The output subtitle is always saved as `.language.srt` (for example `.sv.srt` or `.en.srt`).
- Existing subtitles are checked per language. For example, if `.en.srt` exists and primary language is Swedish, the script still tries to fetch `.sv.srt`.
- A generic `.srt` is treated as English for compatibility with older naming.
- Search strategy is two-stage per language: first full filename matching, then a simplified keyword query if no match is found.
- A local `.subtitle-cache` folder is created to reduce repeated provider requests.
- Pressing `Ctrl+C` stops the run cleanly and prints partial progress summary.
- Default mode is optimized for speed. Use `--detailed-progress` only when you want extra live details.
