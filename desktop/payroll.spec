from pathlib import Path

root = Path(SPECPATH).parent.parent
a = Analysis(
    [str(root / "desktop" / "launcher.py")],
    pathex=[str(root)],
    binaries=[],
    datas=[],
    hiddenimports=["app.main"],
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
    [],
    exclude_binaries=True,
    name="mrbot-payroll",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
)
COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    name="mrbot-payroll",
)
