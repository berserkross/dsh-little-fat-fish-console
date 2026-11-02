# -*- mode: python ; coding: utf-8 -*-

# 需要把 dshconsole/data 下的 ps1 与图标一起打进产物：
#   pyinstaller DSHConsole.spec
# 产物名与实物一致：DSH 控制台.exe

a = Analysis(
    ['dsh_gui.py'],
    pathex=['.'],
    binaries=[],
    datas=[
        ('DeepSeekChan [256x256].ico', '.'),
        ('dshconsole/data/launch-dsh.ps1', 'dshconsole/data'),
        ('dshconsole/data/switch-dsh-web.ps1', 'dshconsole/data'),
    ],
    hiddenimports=['qrcode', 'qrcode.image.pil', 'PIL', 'PIL.Image', 'PIL.ImageTk', 'customtkinter',
                   'pystray', 'pystray._win32'],
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
    name='DSH 控制台',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['DeepSeekChan [256x256].ico'],
)
