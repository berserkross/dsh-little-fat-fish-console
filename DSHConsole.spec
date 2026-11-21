# -*- mode: python ; coding: utf-8 -*-

# 需要把 dshconsole/data 下的 ps1 与图标一起打进产物：
#   py -3.11 -m PyInstaller --noconfirm DSHConsole.spec
# 产物：dist\DSHConsole\DSHConsole.exe（一整个目录，含 _internal）。
#
# 为什么是 onedir 而不是 onefile：onefile 每次启动都要把 30 MB 内容解包到
# %TEMP%\_MEIxxxx，本机（装了腾讯电脑管家）上这一步会失败并弹出
# PyInstaller 引导层的「Could not create temporary directory!」，双击毫无反应。
# onedir 不写临时目录，启动也不再受杀软钩子影响。

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
    [],
    exclude_binaries=True,
    name='DSHConsole',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['DeepSeekChan [256x256].ico'],
    version='version_info.txt',
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='DSHConsole',
)
