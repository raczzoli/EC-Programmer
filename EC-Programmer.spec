# -*- mode: python ; coding: utf-8 -*-
# SPDX-FileCopyrightText: 2026 R89 Repairs and contributors
# SPDX-License-Identifier: GPL-2.0-or-later
import os

a = Analysis(
    ['run_gui.py'],
    pathex=[],
    binaries=[],
    datas=[('app/assets', 'app/assets'), ('VERSION', '.')]
          + ([(os.environ['EC_BUILD_INFO_FILE'], '.')]
             if os.environ.get('EC_BUILD_INFO_FILE') else []),
    hiddenimports=[],
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
    name='EC-Programmer',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
