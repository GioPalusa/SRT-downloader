# -*- mode: python ; coding: utf-8 -*-

from PyInstaller.utils.hooks import collect_all, copy_metadata

datas = []
binaries = []
hiddenimports = ['yaml']

# subliminal loads providers/refiners and dogpile loads its cache backends
# lazily by string name (via entry points / importlib), so PyInstaller's
# static analysis misses them. collect_all pulls in every submodule and data
# file for these packages; copy_metadata ships the dist-info so the runtime
# entry-point lookups (subliminal.providers, subliminal.refiners) resolve.
for package in ("subliminal", "babelfish", "guessit", "rebulk", "dogpile"):
    pkg_datas, pkg_binaries, pkg_hiddenimports = collect_all(package)
    datas += pkg_datas
    binaries += pkg_binaries
    hiddenimports += pkg_hiddenimports

for dist in ("subliminal", "babelfish", "guessit", "srt-downloader"):
    datas += copy_metadata(dist)

# dogpile's dbm cache backend goes through Python's stdlib `dbm`, which picks
# a clone (gnu/ndbm/dumb) lazily at runtime. PyInstaller misses them, and on
# Windows none get bundled -> "no dbm clone found". dbm.dumb is pure Python and
# available everywhere, so it guarantees a working fallback on every platform.
hiddenimports += ['dbm', 'dbm.dumb', 'dbm.ndbm', 'dbm.gnu']

a = Analysis(
    ['fetch_srt_subtitles.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='srt-download',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
