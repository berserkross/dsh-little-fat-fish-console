# -*- mode: python ; coding: utf-8 -*-

# 需要把 dshconsole/data 下的 ps1 与图标一起打进产物：
#   py -3.11 -m PyInstaller --noconfirm DSHConsole.spec
# 产物：dist\DSHConsole.exe（ASCII 文件名，便于命令行、CI 与签名脚本引用无空格路径；
# 中文产品名由 version_info.txt 的 ProductName / FileDescription 与窗口标题体现）。

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
    name='DSHConsole',
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
    version='version_info.txt',
)
