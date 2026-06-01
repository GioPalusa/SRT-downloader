#!/usr/bin/env sh
set -eu

INSTALL_DIR="${SRT_DOWNLOADER_INSTALL_DIR:-$HOME/.local/bin}"
TARGET_PATH="$INSTALL_DIR/srt-download"

removed_binary=0
if [ -e "$TARGET_PATH" ]; then
  rm -f "$TARGET_PATH"
  printf 'Removed %s\n' "$TARGET_PATH"
  removed_binary=1
else
  printf 'No binary found at %s\n' "$TARGET_PATH"
fi

# Strip the PATH entry that install.sh added. We look for both the marker
# comment and the matching export line, and leave the rest of the rc file
# untouched. This is a no-op if the user has already cleaned things up.
strip_path_entry() {
  rc_file="$1"
  [ -f "$rc_file" ] || return 0

  path_line="export PATH=\"$INSTALL_DIR:\$PATH\""
  if ! grep -F "$path_line" "$rc_file" >/dev/null 2>&1; then
    return 0
  fi

  tmp="$(mktemp "${TMPDIR:-/tmp}/srt-download-rc.XXXXXX")"
  awk -v marker='# Added by srt-download installer' -v line="$path_line" '
    {
      if ($0 == marker) { skip_marker = 1; next }
      if (skip_marker && $0 == "") { skip_marker = 0; next }
      if ($0 == line) { next }
      print
    }
  ' "$rc_file" > "$tmp"
  mv "$tmp" "$rc_file"
  printf 'Removed PATH entry from %s\n' "$rc_file"
}

for rc in "$HOME/.zshrc" "$HOME/.bash_profile" "$HOME/.bashrc" "$HOME/.profile"; do
  strip_path_entry "$rc"
done

if [ "$removed_binary" -eq 1 ]; then
  printf 'srt-download uninstalled.\n'
else
  printf 'Nothing to uninstall.\n'
fi
