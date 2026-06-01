#!/usr/bin/env sh
set -eu

REPO="${SRT_DOWNLOADER_REPO:-GioPalusa/SRT-downloader}"
INSTALL_DIR="${SRT_DOWNLOADER_INSTALL_DIR:-$HOME/.local/bin}"
VERSION="${SRT_DOWNLOADER_VERSION:-latest}"
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

if [ "$VERSION" = "latest" ]; then
  DOWNLOAD_URL="https://github.com/$REPO/releases/latest/download/$ASSET_NAME"
else
  case "$VERSION" in
    v*) TAG="$VERSION" ;;
    *)  TAG="v$VERSION" ;;
  esac
  DOWNLOAD_URL="https://github.com/$REPO/releases/download/$TAG/$ASSET_NAME"
fi

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

path_was_modified=0
path_shell_rc=""

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
    printf '\n# Added by srt-download installer\n%s\n' "$path_line" >> "$shell_rc"
  fi

  path_was_modified=1
  path_shell_rc="$shell_rc"
}

mkdir -p "$INSTALL_DIR"
tmp_file="$(mktemp "${TMPDIR:-/tmp}/srt-download.XXXXXX")"
trap 'rm -f "$tmp_file"' EXIT INT TERM

printf 'Downloading %s\n' "$DOWNLOAD_URL"
download_file "$DOWNLOAD_URL" "$tmp_file"
chmod +x "$tmp_file"

# Strip Gatekeeper quarantine so the unsigned binary can run.
# Without this, the first invocation is blocked with "cannot be opened
# because the developer cannot be verified" and the user has to clear it
# manually in System Settings > Privacy & Security.
if command -v xattr >/dev/null 2>&1; then
  xattr -d com.apple.quarantine "$tmp_file" 2>/dev/null || true
fi

mv "$tmp_file" "$TARGET_PATH"

ensure_path

printf '\nInstalled srt-download to %s\n' "$TARGET_PATH"

if [ "$path_was_modified" -eq 1 ]; then
  printf '\nAdded %s to PATH in %s\n' "$INSTALL_DIR" "$path_shell_rc"
  printf 'Open a new terminal, or run: . %s\n' "$path_shell_rc"
fi

cat <<EOF

Quick start:
  srt-download                  scan current folder
  srt-download -l sv            primary language (English added as fallback)
  srt-download --list-providers show provider order
  srt-download --help           full help

Drop a srt-downloader.yaml next to your videos for defaults and provider creds.
Docs: https://github.com/$REPO#readme
EOF
