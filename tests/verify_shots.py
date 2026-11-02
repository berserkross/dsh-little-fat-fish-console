r"""截图的取证脚本（批次 G）：不用眼睛，用像素。

判据：
  A1 白底垫后 vs 黑底垫后：同一窗口两次抓图的像素必须**完全一致** —— 只要有任何一个
     桌面字形透进来，两张图就会不同（白底会更亮、黑底会更暗）。
  A2 玻璃三件套在场：竖向渐变（顶 > 底）、GLASS_EDGE 亮边（边缘比卡面亮）、
     柔影（卡片正下方比远处更暗）。
  A3 日志区没有系统选中蓝带：逐行统计 Windows 高亮色，任何一行都不许铺满宽度。
  A4 日志正文高度 = clamp(行数,6,26) 行 * 16 逻辑像素。

用法：py -3.11 tests\verify_shots.py
"""
from __future__ import annotations

import json
import os
import re
import warnings
from pathlib import Path

from PIL import Image, ImageChops

warnings.simplefilter("ignore", DeprecationWarning)

OUT = Path(os.environ.get("TEMP", ".")) / "ui_v4"
fails: list[str] = []


def check(ok: bool, label: str, detail: str = "") -> None:
    print(("  PASS " if ok else "  FAIL ") + label + ((" " + detail) if detail else ""))
    if not ok:
        fails.append(label)


def load(name: str) -> Image.Image:
    return Image.open(OUT / name).convert("RGB")


def band_mean(img: Image.Image, x0: int, y0: int, w: int, h: int) -> float:
    box = img.crop((x0, y0, x0 + w, y0 + h))
    data = list(box.getdata())
    return sum(sum(px) for px in data) / (3.0 * len(data))


def system_blue_rows(img: Image.Image) -> tuple[int, int]:
    """返回 (命中像素总数, 单行最多命中数) —— 蓝带会表现为整行铺满。"""
    w, h = img.size
    total, widest = 0, 0
    for y in range(h):
        row = 0
        for x in range(0, w, 2):
            r, g, b = img.getpixel((x, y))
            if r < 40 and 70 < g < 160 and 165 < b < 245:
                row += 1
        total += row * 2
        widest = max(widest, row * 2)
    return total, widest


def marker() -> dict[str, str]:
    path = Path(os.environ.get("TEMP", ".")) / "dsh-gui-selftest.txt"
    if not path.is_file():
        return {}
    text = path.read_text(encoding="utf-8", errors="replace")
    return dict(re.findall(r"(\w+)=([^\s]+)", text))


def layout_of(name: str) -> dict:
    stem = name.rsplit(".", 1)[0]
    return json.loads((OUT / ("layout-%s.json" % stem)).read_text(encoding="utf-8"))


def main() -> int:
    layout = layout_of("01-stopped.png")
    mark = marker()

    print("[A1] 白底垫后 vs 黑底垫后：像素必须完全一致（桌面内容进不来）")
    white, dark = load("09-white-backdrop-app.png"), load("11-black-backdrop-app.png")
    repeat = load("09b-white-repeat-app.png")
    # 窗口最外 8px 是 DWM 画的圆角/影边，它天然与背后窗口混合，不属于应用内容
    INSET = 8

    def inner(img):
        return img.crop((INSET, INSET, img.width - INSET, img.height - INSET))

    same_shot = ImageChops.difference(inner(white), inner(repeat))
    check(same_shot.getbbox() is None, "同一状态连抓两次完全一致（差异只可能来自桌面）",
          "bbox=%s" % (same_shot.getbbox(),))
    if white.size != dark.size:
        check(False, "两次抓图尺寸一致", "%s vs %s" % (white.size, dark.size))
    else:
        full_diff = ImageChops.difference(white, dark)
        diff = ImageChops.difference(inner(white), inner(dark))
        bbox = diff.getbbox()
        worst = max(max(px) for px in diff.getdata())
        rim = sum(1 for px in full_diff.getdata() if max(px) > 0)
        check(bbox is None and worst == 0, "主窗口内容与垫后窗口无关",
              "内容区差异 bbox=%s 最大差=%d；窗口最外 8px 圆角/影边另有 %d px（DWM 合成）"
              % (bbox, worst, rim))
    # 附证：面板内部纯白像素只能来自 ico 头像，占比必须很低（桌面穿透会铺满整片）
    white90 = layout_of("09-white-backdrop-app.png")
    for key in ("header", "group0", "group1", "group2", "log", "foot"):
        if key not in white90:
            continue
        x, y, w, h = white90[key]
        box = white.crop((x + 8, y + 8, x + w - 8, y + h - 8))
        pixels = list(box.getdata())
        pure = sum(1 for px in pixels if min(px) >= 250)
        ratio = pure / float(len(pixels))
        check(ratio < 0.03, "%s 内部纯白占比 <3%%" % key,
              "%.3f%% (%d px)" % (ratio * 100.0, pure))

    print("[A2] 玻璃三件套：渐变 / 亮边 / 柔影")
    shot = load("01-stopped.png")
    _, h = shot.size
    top = band_mean(shot, 4, 4, 6, 12)
    bottom = band_mean(shot, 4, h - 16, 6, 12)
    check(top > bottom + 20, "整窗竖向渐变可见", "顶=%.1f 底=%.1f" % (top, bottom))
    hx, hy, hw, hh = layout["header"]
    mid_x = hx + hw // 2
    profile = [(sum(shot.getpixel((mid_x, y))) / 3.0) for y in range(max(0, hy - 14), hy + 6)]
    edge = max(profile)
    face = band_mean(shot, hx + 40, hy + 20, hw - 80, 8)
    check(edge > face + 6, "GLASS_EDGE 上沿亮边比卡面亮",
          "边=%.1f 面=%.1f" % (edge, face))
    near = band_mean(shot, hx + 40, hy + hh + 2, hw - 80, 4)
    far = band_mean(shot, hx + 40, hy + hh + 16, hw - 80, 4)
    check(near < far - 1.0, "卡片下方柔影可见（近处更暗）", "近=%.1f 远=%.1f" % (near, far))

    print("[A3] 日志区没有系统选中蓝带（扫描日志正文矩形）")
    for name in ("01-stopped.png", "02-running.png", "06-log-strip.png"):
        img = load(name)
        x, y, w, h = layout_of(name)["log_text"]
        region = img.crop((x, y, x + w, y + h))
        total, widest = system_blue_rows(region)
        limit = max(4, int(w * 0.02))
        check(widest <= limit, name + " 正文区没有整行蓝带",
              "命中=%d 单行最多=%d (宽 %d, 限 %d)" % (total, widest, w, limit))

    print("[A4] 日志正文高度 = clamp(行数,6,26) 行（空态走 LOG_ROWS_EMPTY）")
    # 默认窗口 960x700 @150% → 1440x1050：设备像素 / 1.5 = 逻辑像素
    scale = white.width / float(os.environ.get("LOGICAL_W", "960"))
    for name, expect_rows in (("02-running.png", None), ("07-empty-state.png", None)):
        info = layout_of(name)
        h = info["log_text"][3]
        lines = int(info["lines"])
        rows = int(info["rows"])
        measured = h / scale
        check(abs(measured - rows * 16) <= 8,
              "%s 正文高 = %d 行" % (name, rows),
              "设备高=%d 逻辑高=%.1f 控件行数=%d -> %dpx"
              % (h, measured, lines, rows * 16))
    running = layout_of("02-running.png")
    empty = layout_of("07-empty-state.png")
    expect = max(6, min(int(running["lines"]), 26))
    check(running["rows"] == expect, "有字时 rows = clamp(实际行数,6,26)",
          "rows=%d lines=%d 期望=%d" % (running["rows"], running["lines"], expect))
    check(empty["rows"] == 12, "空态抬到 LOG_ROWS_EMPTY=12 行",
          "rows=%d lines=%d" % (empty["rows"], empty["lines"]))
    check(mark.get("alpha") == "1.0", "marker alpha=1.0", str(mark.get("alpha")))
    # marker 说的是 selftest 那一次运行（它的日志内容与截图进程不同），所以只校验
    # 「marker 的 rows 由它自己的实际行数算出」——这才是「marker 与视觉一致」的定义。
    m_rows = int(mark.get("rows", "0") or 0)
    m_lines = int(mark.get("rows_lines", "0") or 0)
    check(m_rows == max(6, min(m_lines, 26)), "marker rows = clamp(自己的行数,6,26)",
          "rows=%d rows_lines=%d" % (m_rows, m_lines))
    check(mark.get("rows_ok") == "True", "marker rows_ok", str(mark.get("rows_ok")))

    print()
    print("VERIFY %s (%d 项失败)" % ("OK" if not fails else "FAILED", len(fails)))
    return 0 if not fails else 1


if __name__ == "__main__":
    raise SystemExit(main())
