# -*- mode: python ; coding: utf-8 -*-

import os
from pathlib import Path

block_cipher = None
debug_build = os.environ.get("ToolBar2_DEBUG", "").lower() in {"1", "true", "yes"}
help_datas = [
    (
        str(path),
        str((Path("help") / path.parent.relative_to("help")).as_posix()),
    )
    for path in Path("help").rglob("*")
    if path.is_file()
]


a = Analysis(
    ["toolbar.py"],
    pathex=[],
    binaries=[],
    datas=[
        ("img/gear.svg", "img"),
        ("img/ToolBar2.ico", "img"),
        ("img/ToolBar2.png", "img"),
    ] + help_datas,
    hiddenimports=[
        "PyQt6.QtCore",
        "PyQt6.QtGui",
        "PyQt6.QtWidgets",
        "PyQt6.QtSvg",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="ToolBar2",
    debug=debug_build,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=debug_build,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon="img/ToolBar2.ico",
)
