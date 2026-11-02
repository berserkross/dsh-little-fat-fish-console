"""统一的资源定位：源码运行取包目录，PyInstaller 冻结后取 sys._MEIPASS。

dsh_gui 用这里拿 data 目录下的 ps1 与 .ico，避免把「脚本就在 harness 目录里」当成前提。
"""
from __future__ import annotations

import sys
from pathlib import Path

ICON_NAME = "DeepSeekChan [256x256].ico"
PACKAGE_DIR = Path(__file__).resolve().parent


def frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def resource_root() -> Path:
    """冻结环境返回解包目录；源码运行返回仓库根（包目录的上一级）。"""
    if frozen():
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            return Path(meipass)
        return Path(sys.executable).resolve().parent
    return PACKAGE_DIR.parent


def _data_dirs() -> list[Path]:
    root = resource_root()
    return [root / "dshconsole" / "data", root / "data", PACKAGE_DIR / "data"]


def data_file(name: str) -> Path:
    """返回 data 下的资源路径；一个都不存在时返回首选候选，由调用方判断。"""
    candidates = [d / name for d in _data_dirs()]
    for cand in candidates:
        if cand.is_file():
            return cand
    return candidates[0]


def launch_ps1() -> Path:
    return data_file("launch-dsh.ps1")


def switch_ps1() -> Path:
    return data_file("switch-dsh-web.ps1")


def icon_path() -> Path | None:
    """窗口/exe 图标；找不到返回 None（调用方跳过 iconbitmap）。"""
    root = resource_root()
    for cand in (root / ICON_NAME, PACKAGE_DIR.parent / ICON_NAME, PACKAGE_DIR / ICON_NAME):
        if cand.is_file():
            return cand
    return None
