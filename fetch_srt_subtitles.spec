# -*- mode: python ; coding: utf-8 -*-

from PyInstaller.utils.hooks import collect_data_files, collect_submodules, copy_metadata


babelfish_datas = collect_data_files('babelfish') + copy_metadata('babelfish')
babelfish_hiddenimports = collect_submodules('babelfish.converters')

a = Analysis(
    ['fetch_srt_subtitles.py'],
    pathex=[],
    binaries=[],
    datas=babelfish_datas,
    hiddenimports=['babelfish', 'yaml'] + babelfish_hiddenimports,
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
