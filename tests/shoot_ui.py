r"""截图自检（批次 G）：把每个状态抓成 PNG，存 %TEMP%\ui_v4\。

规矩：
  1. 只启动**本项目这一份代码**的窗口，抓完自己关掉，绝不去碰任何真实 node/DSH 进程
     —— 状态一律用注入的假 provider（_status_provider / _pids_provider / _port_open）。
  2. 抓图前必须清掉日志里的选中区：不清的话 Tk 的系统高亮色会铺成一条全宽蓝带。
  3. 「白底垫后」对比图：在白底（带黑色字形）窗口正后方垫一张，再抓主窗口 —— 卡面、
     日志区、状态行内部不许出现任何字形轮廓。

用法：py -3.11 tests\shoot_ui.py
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import customtkinter as ctk          # noqa: E402
from PIL import Image, ImageChops, ImageDraw, ImageGrab, ImageStat   # noqa: E402

import dsh_gui                        # noqa: E402
from dshconsole import status, ui_theme       # noqa: E402

OUT = Path(os.environ.get("DSH_SHOTS_DIR") or (Path(os.environ.get("TEMP", ".")) / "ui_v4"))
# 固定主窗口左上角：Windows 会在这台机器上把窗口越挪越偏（曾经一路挪到屏幕外，
# 抓到整张黑图）。每次抓图前把它钉回同一个位置，截图才可复现，也避开系统浮窗。
ANCHOR = (160, 160)   # 留出 bbox_pad=120 的外扩余量，否则窗口贴边时外扩图被屏幕裁掉


def _quiet(**_kwargs):
    return status.Status(phase=status.Phase.STOPPED, pids=[], port_open=False,
                         phone_open=False, ts_ip=None, lan_ips=None, notes=[])


def _running():
    return status.Status(phase=status.Phase.RUNNING, pids=[4321], port_open=True,
                         phone_open=True, ts_ip="100.124.206.105",
                         lan_ips=["192.168.1.20"], notes=[])


def _degraded():
    return status.Status(phase=status.Phase.DEGRADED, pids=[], port_open=True,
                         phone_open=False, ts_ip=None, lan_ips=None, notes=[],
                         others=[(41544, r"C:\fake\node_modules\@deepseek-ai\dsh\lib\bin.js")])


def _residue():
    return status.Status(phase=status.Phase.STOPPED, pids=[], port_open=False,
                         phone_open=False, ts_ip=None, lan_ips=None, notes=[],
                         residue=True)


def _starting():
    return status.Status(phase=status.Phase.STARTING, pids=[4321], port_open=False,
                         phone_open=False, ts_ip=None, lan_ips=None, notes=[])


def settle(app, seconds: float = 0.55) -> None:
    """把挂起的事件跑完：玻璃底图是 140ms 防抖之后才画的。"""
    end = time.time() + seconds
    while time.time() < end:
        app.update()
        time.sleep(0.02)


def stabilize(app, seconds: float = 0.45) -> None:
    """按当前几何强制重画一次玻璃底图，再等事件走完 —— 抓图前把状态钉死。

    不这么做的话，两张截图之间可能夹进一帧（140ms 防抖）重绘，底部边缘差 1 个色阶，
    看上去像「有东西透进来了」，其实是时序。
    """
    settle(app, 0.15)
    paint = getattr(app, "_paint_glass", None)
    if paint is not None:
        try:
            paint()
        except Exception:      # noqa: BLE001 - 窗口已销毁
            pass
    settle(app, seconds)


def clear_selection(app) -> None:
    """抓图前清选中区：不清就会把系统高亮色（蓝带）一起拍进去。"""
    for box in (app.log, getattr(app._log_overlay, "textbox", None)):
        if box is None:
            continue
        try:
            box.tag_remove("sel", "1.0", "end")
            box.selection_clear()
        except Exception:      # noqa: BLE001 - 浮层没开 / 控件替身
            pass


def _rect(app, pad: int):
    x, y = app.winfo_rootx(), app.winfo_rooty()
    return (x - pad, y - pad, x + app.winfo_width() + pad, y + app.winfo_height() + pad)


def _shot(app, pad: int):
    return ImageGrab.grab(bbox=_rect(app, pad), all_screens=True).convert("RGB")


def grab(app, name: str, bbox_pad: int = 0, tries: int = 8) -> Path:
    """抓一张「确定拍到了自己」的图。

    桌面合成器偶尔会慢一帧：连抓两次可能一次拿到旧帧（曾拍到主窗口整体右移 510px、垫后
    窗口还没画出来的桌面）。所以每次抓图都自检 —— 连抓两张必须逐像素相同；带 bbox_pad
    时，外扩图按 pad 内缩裁出来的内容必须与被抓窗口本身逐像素相同。不满足就多等一帧重抓。
    """
    if hasattr(app, "_paint_glass"):
        stabilize(app)
    w, h = app.winfo_width(), app.winfo_height()
    img = None
    for _attempt in range(tries):
        if hasattr(app, "_panels"):
            # deiconify：垫后窗口被激活时主窗口曾被系统最小化（rect 变成 -32000）
            app.deiconify()
            app.attributes("-topmost", True)
            app.geometry("+%d+%d" % ANCHOR)
        app.update_idletasks()
        app.update()
        rect = _rect(app, 0)
        plain = _shot(app, 0)
        if not hasattr(app, "_panels"):
            # 浮层（二维码/日志全屏）有自己的动画与滚动条，不做双抓比对：一次即成
            img = plain
            break
        again = _shot(app, 0)
        if _rect(app, 0) != rect:
            # 窗口在两次抓图之间被系统挪了位置（曾经撞见过：窗口一度半出屏，随后被挪回来）
            settle(app, 0.6)
            continue
        mean = ImageStat.Stat(plain).mean
        palette = plain.getcolors(maxcolors=1 << 16)
        print("  grab %-26s rect=%s mean=%s colors=%s" % (
            name, rect, [round(v) for v in mean],
            ">64k" if palette is None else len(palette)))
        if sum(mean) < 30 or (palette is not None and len(palette) < 64):
            print("    ! 这一帧没有画面（全黑/单色），重抓")
            settle(app, 0.6)
            continue
        if plain.size != again.size or ImageChops.difference(plain, again).getbbox() is not None:
            settle(app, 0.5)
            continue
        if bbox_pad:
            wide = _shot(app, bbox_pad)
            inner = wide.crop((bbox_pad, bbox_pad, bbox_pad + w, bbox_pad + h))
            if inner.size != plain.size or ImageChops.difference(inner, plain).getbbox() is not None:
                settle(app, 0.5)
                continue
            img = wide
        else:
            img = plain
        break
    if img is None:
        raise SystemExit("截图自检失败：%s 连抓 %d 次都没稳定（合成器在动？）" % (name, tries))
    path = OUT / name
    img.save(path)
    if bbox_pad == 0 and hasattr(app, "_panels"):
        dump_layout(app, name)
    print("shot %-28s %sx%s  %s" % (name, img.width, img.height, path))
    return path


def dump_layout(app, name: str) -> None:
    """把每块面板的设备像素矩形写成 layout-<截图名>.json —— 取证脚本靠它定位面板内部。"""
    import json
    ox, oy = app.winfo_rootx(), app.winfo_rooty()
    rects = {}
    for key, panel in app._panels.items():
        if not panel.winfo_ismapped():
            continue
        rects[key] = [panel.winfo_rootx() - ox, panel.winfo_rooty() - oy,
                      panel.winfo_width(), panel.winfo_height()]
    rects["primary"] = [app.btn_primary.winfo_rootx() - ox,
                        app.btn_primary.winfo_rooty() - oy,
                        app.btn_primary.winfo_width(), app.btn_primary.winfo_height()]
    rects["log_text"] = [app.log.winfo_rootx() - ox, app.log.winfo_rooty() - oy,
                         app.log.winfo_width(), app.log.winfo_height()]
    rects["lines"] = app._log_line_count() or 0
    rects["rows"] = app._log_rows
    stem = name.rsplit(".", 1)[0]
    (OUT / ("layout-%s.json" % stem)).write_text(json.dumps(rects, indent=1), encoding="utf-8")


def probe_layout(app) -> dict:
    """量一遍当前窗口：三张组卡 + 13 个芯片的设备像素矩形（相对窗口左上角）。"""
    ox, oy = app.winfo_rootx(), app.winfo_rooty()

    def rect(widget) -> list:
        return [widget.winfo_rootx() - ox, widget.winfo_rooty() - oy,
                widget.winfo_width(), widget.winfo_height()]

    cards, chips = [], []
    for group_index, (title, entries) in enumerate(dsh_gui.ACTION_GROUPS):
        card = app._groups[group_index]
        cards.append({"title": title, "rect": rect(card)})
        for _icon, text, name in entries:
            button = app._group_buttons[name]
            chips.append({"group": title, "text": text, "rect": rect(button)})
    return {"window": [app.winfo_width(), app.winfo_height()],
            "cards": cards, "chips": chips}


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    app = dsh_gui.ConsoleApp()
    app._status_provider = _quiet
    app._pids_provider = lambda: ([], None)
    app._port_open = lambda: False
    app._snapshot.invalidate()
    app.attributes("-topmost", True)
    app.lift()
    settle(app, 1.2)

    # 布局取证：四种情形各量一次（全新 960x700 → 900x900 → 640x900 → 回 960x700）。
    # 第三种会按 columns=2 摆两行组卡；第四种验证「窄→宽回落」不会残留上一次的行权重。
    scenarios = []

    def snapshot(tag: str) -> None:
        settle(app, 0.2)
        scenarios.append(dict(tag=tag, **probe_layout(app)))
        print("probe %-22s window=%s 卡高=%s"
              % (tag, scenarios[-1]["window"],
                 [c["rect"][3] for c in scenarios[-1]["cards"]]))

    snapshot("960x700-fresh")

    # 01 常态（未运行、空日志）
    clear_selection(app)
    grab(app, "01-stopped.png")

    # 02 运行中（4 行真实日志，高度 = clamp(4,6,26) = 6 行）
    app._apply_status(_running())
    app._append_log(["dsh web 已就绪 http://127.0.0.1:3080",
                     "token 已写入日志，可用二维码接管",
                     "队列空闲 · 3 个后台探针在位",
                     "PID 4321 · 端口 3080（在线）"])
    settle(app)
    clear_selection(app)
    grab(app, "02-running.png")

    # 03 异常态（端口被占用 → 「改为控制运行中的实例」）
    app._apply_status(_degraded())
    app._append_log(["端口 3080 被 PID 41544 占用", "可以「改为控制运行中的实例」接管它"])
    settle(app)
    clear_selection(app)
    grab(app, "03-degraded.png")

    # 03b 端口转发残留（琥珀色芯片：假活可见、点此清理）
    app._apply_status(_residue())
    app._append_log(["端口转发残留：转发规则还在，但本机 DSH 进程不在",
                     "点状态条上的琥珀色芯片即可清理"])
    settle(app)
    clear_selection(app)
    grab(app, "03b-residue.png")

    # 03c 启动中（秒数 + 最近一行启动日志，替代无限转圈）
    app._start_epoch = time.time()
    app._apply_status(_starting())
    app._append_log(["dsh web 正在启动…"])
    settle(app, 1.0)
    clear_selection(app)
    grab(app, "03c-starting.png")
    app._start_epoch = 0.0
    app._startup_done_at = None

    # 04 900x900 窄窗（2 列组卡 + 第三组通栏）
    app.geometry("900x900")
    settle(app, 0.8)
    snapshot("900x900")
    clear_selection(app)
    grab(app, "04-narrow-900x900.png")

    # 04b 640x900：真正掉到 2 列组卡（第三组独占一整行并通栏）
    app.geometry("640x900")
    settle(app, 0.8)
    snapshot("640x900")
    clear_selection(app)
    grab(app, "04b-narrow-640x900.png")

    # 05 二维码浮层
    app.geometry("%dx%d" % ui_theme.WINDOW_SIZE)
    settle(app, 0.6)
    snapshot("960x700-after-narrow")
    (OUT / "layout-scenarios.json").write_text(
        json.dumps(scenarios, indent=1), encoding="utf-8")
    app._token = "selftest-token"
    app.on_phone_access()
    settle(app, 0.5)
    if app._qr_overlay is not None:
        clear_selection(app)
        grab(app._qr_overlay, "05-qr-overlay.png")
        app._close_overlays()
        settle(app, 0.3)

    # 06 日志全屏：先灌到 2000 行上限，再开浮层
    app._append_log(["自检长文第 %d 行：滚动丢弃旧行的验证" % i for i in range(300)])
    settle(app)
    clear_selection(app)
    grab(app, "06-log-strip.png")
    app.on_expand_log()
    settle(app, 0.5)
    if app._log_overlay is not None:
        clear_selection(app)
        grab(app._log_overlay, "06-log-fullscreen.png")
        app._close_overlays()
        settle(app, 0.3)

    # 07 空态（清空日志 → 圆形头像空态 + LOG_ROWS_EMPTY 行高）
    app.log.configure(state="normal")
    app.log.delete("1.0", "end")
    app.log.configure(state="disabled")
    app._sync_log_empty(True)
    app._sync_log_rows()
    settle(app)
    clear_selection(app)
    grab(app, "07-empty-state.png")

    # 08/09 白底垫后 vs 10/11 黑底垫后：同一窗口、只有背后那张图不同。
    # 两次抓到的「主窗口自身像素」必须逐像素一致 —— 桌面上任何字形、任何系统浮窗
    # （输入法候选条真的闯进来过一次）都会让这条自检失败，所以它同时是重抓条件。
    back = ctk.CTkToplevel(app)
    back.overrideredirect(True)
    canvas = ctk.CTkCanvas(back, bg="#FFFFFF", highlightthickness=0)
    canvas.pack(fill="both", expand=True)

    cw, ch = app.winfo_width(), app.winfo_height()

    def backdrop(color: str, name: str) -> Image.Image:
        ink = "#000000" if color.upper() == "#FFFFFF" else "#FFFFFF"
        back.configure(fg_color=color)
        canvas.configure(bg=color)
        canvas.delete("all")
        for row in range(18):
            canvas.create_text(18, 24 + row * 44, anchor="nw", fill=ink,
                               font=("Consolas", 22),
                               text="acuhk.edu.cn/elearning/blog/courseware  Group Discussion Files")
        back.geometry("%dx%d+%d+%d" % (cw + 240, ch + 240,
                                       app.winfo_rootx() - 120, app.winfo_rooty() - 120))
        back.lower()
        # overrideredirect 的 Toplevel 在 Windows 上不总服从 lower()：把根窗口临时顶到最上层，
        # 否则抓到的是垫后窗口/桌面本身。
        app.attributes("-topmost", True)
        app.lift()
        settle(app, 0.7)
        clear_selection(app)
        with Image.open(grab(app, name, bbox_pad=120)) as full:
            return full.convert("RGB").crop((120, 120, 120 + cw, 120 + ch))

    white = backdrop("#FFFFFF", "08-white-backdrop.png")
    dark = backdrop("#000000", "10-black-backdrop.png")
    dump_layout(app, "09-white-backdrop-app.png")
    white.save(OUT / "09-white-backdrop-app.png")
    print("shot %-28s %s" % ("09-white-backdrop-app.png", OUT / "09-white-backdrop-app.png"))
    dump_layout(app, "11-black-backdrop-app.png")
    dark.save(OUT / "11-black-backdrop-app.png")
    print("shot %-28s %s" % ("11-black-backdrop-app.png", OUT / "11-black-backdrop-app.png"))
    # 09b 同一状态再抓一次：必须与 09 逐像素一致，否则差异来自重绘而不是桌面穿透
    backdrop("#FFFFFF", "09b-white-repeat.png").save(OUT / "09b-white-repeat-app.png")
    with Image.open(OUT / "09-white-backdrop-app.png") as a, \
            Image.open(OUT / "11-black-backdrop-app.png") as b:
        same = ImageChops.difference(a.convert("RGB"), b.convert("RGB")).getbbox() is None
    print("白底垫后 vs 黑底垫后：主窗口像素%s（判据见 verify_shots.py A1）"
          % ("完全一致" if same else "有差异 —— 桌面内容穿进来了"))
    app.attributes("-topmost", False)
    back.destroy()

    app.after(150, app.destroy)
    app.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
