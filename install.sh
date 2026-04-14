#!/usr/bin/env sh
set -eu

REPO="${SRT_DOWNLOADER_REPO:-GioPalusa/SRT-downloader}"
INSTALL_DIR="${SRT_DOWNLOADER_INSTALL_DIR:-$HOME/.local/bin}"
TARGET_PATH="$INSTALL_DIR/srt-download"
OS_NAME="$(uname -s)"
ARCH_NAME="$(uname -m)"

if [ "$OS_NAME" != "Darwin" ]; then
  printf 'This installer currently supports macOS only.\n' >&2
  exit 1
fi

case "$ARCH_NAME" in
  arm64|aarch64)
    ASSET_NAME="srt-download-macos-arm64"
    ;;
  x86_64)
    ASSET_NAME="srt-download-macos-x64"
    ;;
  *)
    printf 'Unsupported macOS architecture: %s\n' "$ARCH_NAME" >&2
    exit 1
    ;;
esac

DOWNLOAD_URL="https://github.com/$REPO/releases/latest/download/$ASSET_NAME"

if command -v curl >/dev/null 2>&1; then
  download_file() {
    curl -fsSL "$1" -o "$2"
  }
elif command -v wget >/dev/null 2>&1; then
  download_file() {
    wget -qO "$2" "$1"
  }
else
  printf 'curl or wget is required to install srt-download.\n' >&2
  exit 1
fi

ensure_path() {
  case ":$PATH:" in
    *":$INSTALL_DIR:"*)
      return 0
      ;;
  esac

  shell_name="$(basename "${SHELL:-sh}")"
  case "$shell_name" in
    zsh)
      shell_rc="$HOME/.zshrc"
      ;;
    bash)
      if [ -f "$HOME/.bash_profile" ]; then
        shell_rc="$HOME/.bash_profile"
      else
        shell_rc="$HOME/.bashrc"
      fi
      ;;
    *)
      shell_rc="$HOME/.profile"
      ;;
  esac

  mkdir -p "$(dirname "$shell_rc")"
  path_line="export PATH=\"$INSTALL_DIR:\$PATH\""
  if [ ! -f "$shell_rc" ] || ! grep -F "$path_line" "$shell_rc" >/dev/null 2>&1; then
    printf '\n%s\n' "$path_line" >> "$shell_rc"
  fi

  printf 'Added %s to PATH in %s\n' "$INSTALL_DIR" "$shell_rc"
  printf 'Open a new terminal or run: . %s\n' "$shell_rc"
}

mkdir -p "$INSTALL_DIR"
tmp_file="$(mktemp "${TMPDIR:-/tmp}/srt-download.XXXXXX")"
trap 'rm -f "$tmp_file"' EXIT INT TERM

download_file "$DOWNLOAD_URL" "$tmp_file"
chmod +x "$tmp_file"
mv "$tmp_file" "$TARGET_PATH"

ensure_path

printf 'Installed srt-download to %s\n' "$TARGET_PATH"
printf 'Run: srt-download --help\n'
