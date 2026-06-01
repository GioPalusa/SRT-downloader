#!/usr/bin/env python3

from __future__ import annotations

import argparse
from pathlib import Path
from textwrap import dedent


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Render the Homebrew formula for srt-download.")
    parser.add_argument("--output", required=True, help="Path to the formula file to write.")
    parser.add_argument("--repository", required=True, help="GitHub repository in owner/name format.")
    parser.add_argument("--tag", required=True, help="Git tag for the release, for example v0.1.0.")
    parser.add_argument("--version", required=True, help="Version string without the v prefix.")
    parser.add_argument("--sha256-arm64", required=True, help="SHA256 for the macOS arm64 binary.")
    parser.add_argument("--sha256-x64", required=True, help="SHA256 for the macOS x64 binary.")
    return parser.parse_args()


def build_formula(repository: str, tag: str, version: str, sha256_arm64: str, sha256_x64: str) -> str:
    base_url = f"https://github.com/{repository}/releases/download/{tag}"
    return dedent(
        f"""
        class SrtDownload < Formula
          desc \"Download subtitles for local video files recursively\"
          homepage \"https://github.com/{repository}\"
          version \"{version}\"

          on_macos do
            if Hardware::CPU.arm?
              url \"{base_url}/srt-download-macos-arm64\"
              sha256 \"{sha256_arm64}\"
            else
              url \"{base_url}/srt-download-macos-x64\"
              sha256 \"{sha256_x64}\"
            end
          end

          def install
            bin.install Dir[\"srt-download-macos-*\"].first => \"srt-download\"
          end

          def caveats
            <<~EOS
              Quick start:
                srt-download                  scan current folder
                srt-download -l sv            primary language (English added as fallback)
                srt-download --list-providers show provider order
                srt-download --help           full help

              Drop a srt-downloader.yaml next to your videos for defaults and provider creds.
              Docs: https://github.com/{repository}#readme
            EOS
          end

          test do
            assert_match version.to_s, shell_output("#{{bin}}/srt-download --version")
          end
        end
        """
    ).lstrip()


def main() -> int:
    args = parse_args()
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        build_formula(
            repository=args.repository,
            tag=args.tag,
            version=args.version,
            sha256_arm64=args.sha256_arm64,
            sha256_x64=args.sha256_x64,
        ),
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())