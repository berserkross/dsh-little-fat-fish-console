"""小肥鱼控制台 - DeepSeek Harness 桌面图形界面 (customtkinter · 蓝鲸主题)

双击 exe / 运行本脚本即可打开窗口。功能与旧版一致：
  启动 Harness、开启手机访问（端口转发+信任来源）、恢复本机、复制手机地址、
  生成二维码（窗口内显示，刷新/关闭即清除，不落盘）、停止 Harness、实时查看状态。

UI 以 DeepSeek 品牌蓝 #4D6BFE 为主基调，深色科技风，头部展示 DeepSeek 鲸鱼娘图标。
"""
from __future__ import annotations

import dataclasses
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path
from tkinter import filedialog, messagebox
from urllib.parse import urlsplit

import customtkinter as ctk
from PIL import Image

from dshconsole import (addresses, adopt, bridge, config, diagnostics, errors, logtail, phone,
                        probe, psrun, resources, single, snapshot, status, tailscale, tasks,
                        textutil, tray, ui_theme, widgets)
from dshconsole.ui_theme import (ACTION_H, AMBER, AMBER_DARK, BADGE_SIZE, BG, BORDER,
                                 BORDER_STRONG, CARD, CARD2, CARD3, CARD_RADIUS, CHIP,
                                 CHIP_HOVER, CHIP_RADIUS, CYAN, DIM, EMPTY_LOG_HINT, FAINT,
                                 FONT, GAP, GREEN, GRID_BTN_H, GRID_PAD, HEADER_H, HERO_SIZE,
                                 LOG_LINE_PX, LOG_ROWS_EMPTY, LOG_ROWS_MAX, LOG_ROWS_MIN,
                                 LOG_TEXT, MONO, PAD, PANEL_DEEP, PHASE_STYLE, PHASE_WORD,
                                 PRIMARY, PRIMARY_GLOW, PRIMARY_HOVER, PRIMARY_RADIUS, RED,
                                 RED_DARK, SLATE, SLATE_DARK, TEXT, WINDOW_ALPHA, WINDOW_MIN,
                                 WINDOW_SIZE, grid_columns, log_rows, log_rows_with_empty,
                                 type_size)

CFG = config.resolve()          # 本机探测结果；缺项为 None，探测失败不抛异常
HARNESS = CFG.harness
LAUNCH_PS1 = resources.launch_ps1()      # 随包发布的脚本，不再依赖外部 harness 目录
SWITCH_PS1 = resources.switch_ps1()
TOKEN_LOG = CFG.token_log
ICON_FILE = resources.icon_path()
CREATE_NO_WINDOW = 0x08000000      # 自检里伪造进程时别闪出控制台窗口
PORT = CFG.port
APP_TITLE = "小肥鱼控制台"          # 单实例守卫靠窗口标题找回已有窗口，两处必须一致
_APP = None                        # 当前窗口实例：未捕获异常写日志用（见 _report）
MAX_LOG_LINES = 2000               # 日志框行数上限：超过就从顶部滚动丢弃旧行
LOG_POLL_INTERVAL = 0.4            # 跟随真实日志的轮询间隔（秒，≥0.3，不许 busy loop）
STATUS_TTL = 3.0                   # 状态缓存：连点刷新不重复扫描，手动刷新穿透

# ---------------- 主题（DeepSeek 蓝） ----------------
# 配色 / 尺寸 / 五态样式集中在 dshconsole/ui_theme.py，上面 import 已带进本模块作用域。
# 未运行是中性灰而不是红：正常停机不是报警，红环会把「待机」渲染成「出事」。


def primary_action(phase) -> tuple[str, str, str, str]:
    """五态各自的主操作 -> (按钮文案, 回调名, 颜色, 悬停色)。

    一屏只留这一颗主按钮：十颗按钮并排时，用户得自己判断哪颗现在能用。
    回调名与原有的 on_start / on_stop 同名，所以点下去的业务与改动前完全一致。
    """
    if phase is status.Phase.STOPPED:
        return "启动 DSH", "start", PRIMARY, PRIMARY_HOVER
    if phase is status.Phase.DEGRADED:
        return "修复/重启", "restart", AMBER, AMBER_DARK
    if phase is status.Phase.UNKNOWN:
        return "重新探测", "refresh", SLATE, SLATE_DARK
    return "停止 DSH", "stop", RED, RED_DARK      # 启动中 / 运行中


# 功能网格：三组语义分组，组内每项一颗按钮。全部平铺在首屏 —— 没有「⋯ 更多」，
# 也没有抽屉；用户的原话是「主要功能全折叠了根本找不到」。
# 顺序按「先做什么」排：服务最常用放第一组，手机访问其次，工具与退出最后。
# 每项是 (图标, 文案, 回调名)：图标用 BMP 符号（▶ ■ ↻ ⚙ ▦ ⧉ ⌂ ⇄ ↺ ⤓ ⏸ ✕ ⊗ ⏻），
# 微软雅黑 UI 与系统符号字体都覆盖得到，不额外打包图标文件。
# 「启动 DSH / 停止 DSH」不在这里：启停只留主按钮那一颗（见 primary_action），
# 同一个动作有两个入口时，用户得先判断该点哪个 —— 服务组只管重启/刷新/换端口这类
# 「不该有第二次确认」的从属动作。
def _candidates_for(state: "status.Status", port: int, port_owner, log) -> list:
    """端口被占用时找「该接管哪处安装」：先问这个端口是谁在听，再退回命令行扫描。

    旧版只按命令行里的 bin.js 认候选，npx 缓存或换过 node 路径的实例会漏掉，
    于是按钮压根不出现 —— 端口明明被占着，用户却只能手改 config.json。
    端口占用者是最硬的线索（它就是正在应答这个端口的那一个），所以排第一位。
    port_owner 为 None（控件替身 / 自检场景）就只走命令行这一路。
    """
    if state.phase is not status.Phase.DEGRADED:
        return []
    found = adopt.from_processes(state.others)
    if state.port_open and port_owner is not None:
        try:
            owner, why = port_owner(port)
        except Exception as exc:      # noqa: BLE001 - 探测炸了不该带崩刷新
            owner, why = None, f"查端口占用者失败：{exc}"
        if owner is not None:
            found = adopt.merge([owner], found)
        elif why:
            log(why)
    return adopt.merge(found)


ACTION_GROUPS: tuple = (
    ("服务", (
        ("↻", "重启 DSH", "on_restart"),
        ("◌", "刷新状态", "on_refresh"),
        ("⚙", "切换 Web 端口…", "on_change_port"),
        ("■", "关闭 DSH", "on_stop"),
    )),
    ("手机访问", (
        ("▦", "手机访问二维码", "on_phone_access"),
        ("⧉", "复制手机访问地址", "on_copy"),
        ("⌂", "复制本机地址", "on_copy_local"),
        ("⇄", "开启手机访问（UAC）", "on_phone_on"),
        ("⇥", "免 token 直连：关", "on_toggle_relay"),
        ("↺", "恢复本机模式（UAC）", "on_phone_off"),
    )),
    ("工具", (
        ("⤓", "导出诊断包", "on_export_diag"),
        ("⏸", "暂停日志跟随", "on_toggle_log_follow"),
        ("✕", "关闭窗口时：收进托盘", "on_toggle_close_mode"),
        ("⊗", "取消排队", "on_cancel_queue"),
        ("⏻", "退出程序", "_quit"),
    )),
)

# 列骨架：窗口上来就切 6 个等宽子列，3/2/1 列布局各自按 2/3/6 跨列，永远吃满宽度。
GRID_SUBCOLS = 6
# 按钮悬停时的泛光亮边：品牌蓝混进按钮底色，既提亮又不抢戏。
CHIP_EDGE = widgets.blend(PRIMARY_GLOW, CHIP, 0.5)


def _font(size: int, bold: bool = False) -> ctk.CTkFont:
    return ctk.CTkFont(family=FONT, size=type_size(size), weight="bold" if bold else "normal")


def _mono(size: int) -> ctk.CTkFont:
    return ctk.CTkFont(family=MONO, size=type_size(size))


def _icon_candidates() -> list[Path]:
    icon = CFG.icon or ICON_FILE
    return [icon] if icon else []


def _ps_args(include_chrome: bool = False) -> list[str]:
    """ps1 的值参数一律显式传；缺项不传，由脚本自己回退。"""
    pairs = [("-Harness", HARNESS), ("-NodeExe", CFG.node), ("-BinJs", CFG.bin_js),
             ("-DshHome", CFG.dsh_home), ("-Port", PORT)]
    if include_chrome:
        pairs.append(("-Chrome", CFG.chrome))
    args: list[str] = []
    for flag, value in pairs:
        if value:
            args += [flag, str(value)]
    return args


def truncate_logs(*paths) -> list[str]:
    """启动前清空日志，返回没能清空的那些。

    为什么放在 Python 里而不是塞进 PowerShell 的 Set-Content：被别的进程占着的日志会让
    Set-Content 静默失败（-ErrorAction SilentlyContinue），旧 token 就留在文件里，扫码必然 401。
    这里失败要能被看见，好让调用方明确告诉用户「token 不可信」。
    """
    failed: list[str] = []
    for path in paths:
        if not path:
            continue
        try:
            Path(path).write_bytes(b"")
        except OSError:
            failed.append(str(path))
    return failed


def build_direct_start_command(node, bin_js, harness, trusted, log_out, log_err,
                                dsh_home: str = "") -> str:
    """Start-Process 拉起 dsh web 的命令行；_start_direct 与测试共用这一份。

    与 launch-dsh.ps1:88-90 等价，另补一处：把 DSH_HOME 交给子进程（脚本第 38 行做的那件事）。
    --trusted-host 由调用方传进来，脚本那一版从来不传，重启出来的 DSH 认不得 tailnet 域名，
    手机访问直接 401。日志清空不在命令行里做 —— 那一步必须能失败上报，见 truncate_logs()。
    """
    argv = [str(bin_js), "web", "--no-open", "--port", str(PORT)] + list(trusted)
    quoted = ", ".join("'" + str(item) + "'" for item in argv)
    prefix = ""
    if dsh_home:
        prefix += f"$env:DSH_HOME='{dsh_home}'; "
    redirects = ""
    if log_out:
        redirects += f" -RedirectStandardOutput '{log_out}'"
    if log_err:
        redirects += f" -RedirectStandardError '{log_err}'"
    return (prefix + f"Start-Process -FilePath '{node}' -ArgumentList @({quoted}) "
            f"-WorkingDirectory '{harness}' -WindowStyle Hidden{redirects}")


# ---------------- 探测与 ps 调用（统一走 psrun / probe，失败原因不再被吞） ----------------
def run_ps(script: Path, *args: str, timeout: int = 60) -> psrun.PsResult:
    """跑随包发布的 ps1；成功与否看返回对象，不从输出里抠值。"""
    return psrun.run_ps(script, *args, timeout=timeout)


def port_open(port: int | None = None) -> bool:
    return probe.port_open(PORT if port is None else port)


def dsh_pids() -> tuple[list[int] | None, str | None]:
    """命令行里带本机 bin.js 的 node 进程；None = 查不到（不是「没在跑」）。"""
    return probe.dsh_processes(CFG.bin_js)


def _report(text: str) -> None:
    """未捕获异常的出口：有窗口就写日志框，没有窗口就写 stderr —— 绝不静默。"""
    app = _APP
    if app is not None:
        try:
            app.log_async(text)
            return
        except Exception:  # noqa: BLE001 - 窗口已销毁：退回 stderr
            pass
    try:
        print(text, file=sys.stderr)
    except Exception:  # noqa: BLE001
        pass


def _info_blocking(title: str, message: str) -> None:
    """没有窗口可用时的一次性说明框；连 Tk 都起不来就只写 stderr。"""
    try:
        root = ctk.CTk()
        root.withdraw()
        try:
            messagebox.showinfo(title, message, parent=root)
        finally:
            root.destroy()
    except Exception:  # noqa: BLE001
        print(message, file=sys.stderr)


def phone_ready() -> tuple[bool | None, str | None]:
    """手机访问是否真的开启：端口转发指向本机端口 + 防火墙规则都在。"""
    ok, _targets, notes = status.probe_phone(CFG)
    return ok, (notes[0] if notes else None)


def token_suffix(url: str) -> str:
    """从带 token 的地址里抠出 token 本身（剪贴板放完整地址是功能）。"""
    return url.split("token=", 1)[1] if "token=" in url else url


def token_url() -> str | None:
    if TOKEN_LOG is None:
        return None
    try:
        text = TOKEN_LOG.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    m = re.search(rf"dsh web: (http://127\.0\.0\.1:{PORT}/\?token=[A-Za-z0-9_\-]+)", text)
    return m.group(1) if m else None



def make_qr(url: str):
    """生成二维码 PIL 图像（仅在内存中，不落盘）。"""
    import qrcode  # 本地 venv 已安装

    qr = qrcode.QRCode(border=2, box_size=7)
    qr.add_data(url)
    qr.make(fit=True)
    return qr.make_image(fill_color="black", back_color="white").get_image()


NO_PHONE_ROW = "（没有手机可达地址）"


def phone_rows(plan_obj) -> list:
    """手机候选地址行（服务端给什么顺序就是什么顺序）：[(显示文本, Candidate)]。"""
    if plan_obj is None:
        return []
    return [(cand.display(), cand) for cand in getattr(plan_obj, "candidates", ())]


def phone_default_row(plan_obj) -> "str | None":
    """默认选中的那条：二维码计划（qr_url）对应的优先，否则第一条；没候选就是 None。"""
    rows = phone_rows(plan_obj)
    if not rows:
        return None
    want = getattr(plan_obj, "qr_url", None)
    for text, cand in rows:
        if want and cand.url == want:
            return text
    return rows[0][0]


def phone_candidate(plan_obj, choice=None):
    """按下拉文本找回候选；给不出手机能打开的地址就返回 None（绝不换一条顶替）。"""
    rows = phone_rows(plan_obj)
    if not rows:
        return None
    if choice is None:
        want = getattr(plan_obj, "qr_url", None)
        found = (next((cand for _t, cand in rows if want and cand.url == want), None)
                 or rows[0][1])
    else:
        found = next((cand for text, cand in rows if text == choice), None)
    if found is None or not found.phone_reachable or addresses.is_loopback(found.host):
        return None
    return found


def phone_candidate_url(cand, token: "str | None") -> "str | None":
    """候选 → 手机能打开的地址。回环/不可用/没 token 一律 None：手机打不开就不给。"""
    if cand is None or not token:
        return None
    if not cand.phone_reachable or addresses.is_loopback(cand.host):
        return None
    if "token=" in cand.url:
        return cand.url
    sep = "&" if "?" in cand.url else "?"
    return f"{cand.url}{sep}token={token_suffix(token)}"


def phone_reason_text(plan_obj) -> str:
    """tailscale 给的结构化失败原因，原样拼成多行（不替它改文案）。"""
    if plan_obj is None:
        return ""
    return "\n".join(reason.text for reason in getattr(plan_obj, "failures", ()))


def phone_next_steps(plan_obj) -> str:
    """没有手机可达地址时的下一步：计划自己说的下一步 + 判定清单 + 原因，一行一条。"""
    if plan_obj is None:
        return ("手机访问探测失败：这次没拿到 tailscale 的状态。\n"
                "点「开启手机访问（UAC）」重试，原因见日志。")
    lines = [plan_obj.next_step] if plan_obj.next_step else []
    lines.extend(phone.phone_checklist(plan_obj))
    lines.extend(phone_reason_text(plan_obj).splitlines())
    return "\n".join(line for line in lines if line)


def switch_args(plan_obj=None) -> list:
    """切手机模式的脚本参数：serve 已就绪就把域名和默认端口交给 -ServeHost（trusted-host）。"""
    args = list(_ps_args())
    host = getattr(plan_obj, "serve_host", "") or ""
    if host:
        scheme = getattr(plan_obj, "scheme", addresses.SCHEME_HTTP)
        port = addresses.SCHEME_PORTS.get(scheme, addresses.SCHEME_PORTS[addresses.SCHEME_HTTP])
        args += ["-ServeHost", addresses.host_port(host, port)]
    return args


def _selftest_phone_plan(port: int = 3080):
    """自检用的手机访问计划：注入域名 + 100.x 两条候选，走纯计算，不碰真 tailscale。"""
    facts = tailscale.Facts(backend_state=tailscale.RUNNING,
                            dns_name="selftest.tail1234.ts.net",
                            tailscale_ips=("100.101.102.103",),
                            magic_dns_enabled=True, cert_domains=())
    detection = tailscale.Detection(cli="tailscale.exe", facts=facts)
    return phone.plan(port, detection=detection, addresses_list=[])


def mascot_image() -> Image.Image | None:
    """读取 DeepSeek 鲸鱼娘图标（256x256 RGBA，取最大帧）。"""
    candidates = _icon_candidates()
    for ico in candidates:
        try:
            if ico.is_file():
                img = Image.open(ico)
                sizes = list(img.info.get("sizes") or [])
                if sizes:
                    idx = max(range(len(sizes)), key=lambda i: sizes[i][0] * sizes[i][1])
                    img.seek(idx)
                else:
                    img.seek(0)
                return img.convert("RGBA")
        except Exception:  # noqa: BLE001
            continue
    return None


# ---------------- 主窗口 ----------------
class ConsoleApp(ctk.CTk):
    def __init__(self) -> None:
        super().__init__()
        self.title(APP_TITLE)
        self._set_icon()
        self.geometry("%dx%d" % WINDOW_SIZE)
        self.minsize(*WINDOW_MIN)
        self.configure(fg_color=BG)
        # 整窗 alpha=1.0：玻璃改为「画」出来（衬底渐变 + 近实心卡面 + 亮边 + 柔影），
        # 桌面内容一律不参与成像 —— 上一轮 0.96 让浏览器里的字在卡片背后读得出来。
        try:
            self.attributes("-alpha", WINDOW_ALPHA)
        except Exception:      # noqa: BLE001 - 无合成器（远程桌面 / 极简 WM）
            pass
        self._qr_photo = None
        self._qr_url: str | None = None          # 真正编码进二维码的地址（自检要证据）
        self._phone_now = None                   # 最近一次手机访问计划：浮层与复制共用
        self._qr_overlay: widgets.QrOverlay | None = None
        self._log_overlay: widgets.LogOverlay | None = None
        self._log_rows = LOG_ROWS_MIN           # 日志区露几行（按内容长，要更多走浮层）
        self._log_follow = True                  # 日志跟随开关，网格里同一颗按钮切
        self._primary_name = "start"             # 主按钮当前绑的回调名
        self._token: str | None = None
        self._candidates: list[adopt.Candidate] = []   # 端口被占用时查到的别的 DSH 进程
        self._adopt_shown = False
        self._last_net = ""                     # 上次写进日志的网络行，避免重复刷屏
        self._last_status: status.Status | None = None  # 上次探测结果：刷新时先显示它
        self._last_raw = None                          # 上次的原始探测数据，只给诊断包用
        # 可注入的探测口：自检用替身，不再改写模块全局（B2-3）
        self._pids_provider = dsh_pids
        self._port_open = port_open
        self._status_provider = self._load_status
        self._phone_planner = phone.detect_plan     # tailscale 探测/编排入口
        self._port_owner = adopt.from_port_owner    # 「这个端口是谁在听」：探测层可注入
        self._serve_reset = tailscale.reset_serve    # 恢复本机前先撤掉 serve
        self._run_switch = run_ps                    # 提权切换脚本入口
        self._snapshot = snapshot.Snapshot(lambda: self._status_provider(), ttl=STATUS_TTL)
        self._queue = tasks.TaskQueue(post=self._post, on_change=self._on_queue_change)
        self._activator = single.Activator()    # 第二个实例叫醒窗口用（见 _poll_activate）
        self._tray: tray.Tray | None = None
        self._tail: logtail.LogTailer | None = None
        self._close_to_tray = config.close_to_tray()
        self.report_callback_exception = self._on_callback_error
        self._build()
        self.logline(f"DSH：{HARNESS or '未检测到'}  ·  端口 {PORT}  ·  node：{CFG.node or '未检测到'}")
        self._start_tray()
        self._start_log_tail()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.after(150, self.refresh)
        self.after(400, self._poll_activate)

    # ---------------- 线程投递 / 关闭 / 托盘 ----------------
    def _post(self, fn, *args) -> None:
        """把工作线程或托盘线程的回调投递回 Tk 主线程（跨线程碰控件是禁忌）。"""
        try:
            self.after(0, fn, *args)
        except Exception:      # noqa: BLE001 - 窗口已销毁：没人需要这个回调了
            pass

    def _start_log_tail(self) -> None:
        """跟随真实日志文件（dsh-web.stdout.log / .stderr.log）。"""
        self._log_follow = True
        try:
            self._tail = logtail.LogTailer(CFG.log_files, self._on_tail_lines,
                                           interval=LOG_POLL_INTERVAL)
            self._tail.start()
            self.logline("正在跟随日志：" + "、".join(Path(p).name for p in CFG.log_files))
        except Exception as exc:      # noqa: BLE001 - 跟随失败不该影响主功能
            self._tail = None
            self.logline(f"日志跟随没能启动：{exc}（只显示界面事件）")

    def _on_tail_lines(self, path, lines) -> None:
        """后台线程回调：内容已经脱敏（logtail 里过过 redact_text），这里只投递。"""
        self._post(self._append_log, lines, f"[{Path(path).name}] ")

    def _start_tray(self) -> bool:
        if not self._close_to_tray:
            return False                # 用户选了「关闭即退出」：不起托盘
        self._tray = tray.Tray(post=self._post, on_lost=self._on_tray_lost)
        ok, why = self._tray.start(self._tray_items())
        if ok:
            self.logline("托盘已就绪：关闭按钮会收进托盘，真退出请用托盘菜单「退出」。")
            return True
        self._tray = None
        self._close_to_tray = False     # 起不来就退回普通窗口，别把用户锁在托盘里
        self._sync_close_hint()
        self.logline(f"{why}：本次按普通窗口运行，关闭按钮＝退出。")
        return False

    def _on_tray_lost(self, reason: str) -> None:
        """托盘线程没了：立刻退回普通窗口，否则用户会以为程序还在。"""
        self.logline(f"{reason}：退回普通窗口，关闭按钮＝退出。")
        self._tray = None
        self._close_to_tray = False
        self._sync_close_hint()

    def _tray_items(self):
        return [
            (self._window_label, self._toggle_window),
            ("复制手机访问地址", self._tray_copy),
            ("停止 DSH", self.on_stop),
            ("退出", self._quit),
        ]

    def _tray_copy(self) -> None:
        """托盘里点「复制」：不走弹窗（托盘场景下用户可能看不见窗口）。"""
        known, _unknown = self._address_options()
        token = self._current_token()
        if not token or not known:
            self.logline("还没有可复制的手机地址：先启动 Harness 并确认地址。")
            return
        addr = known[0][1]
        url = f"{addr.url(PORT)}?token={token_suffix(token)}"
        self.clipboard_clear()
        self.clipboard_append(url)
        self.logline(f"已复制（{addr.label}）：" + textutil.redact(url))

    def _window_label(self) -> str:
        try:
            return "隐藏主窗口" if self.state() == "normal" else "显示主窗口"
        except Exception:      # noqa: BLE001
            return "显示主窗口"

    def _show_window(self) -> None:
        """从托盘/最小化里把窗口显示出来并聚焦（收进托盘时是 withdraw 状态）。"""
        try:
            self.deiconify()
            self.lift()
            self.focus_force()
        except Exception:      # noqa: BLE001
            return

    def _toggle_window(self) -> None:
        """托盘菜单的显示/隐藏（在主线程执行，见 Tray 的 post）。"""
        try:
            if self.state() == "normal":
                self.withdraw()
            else:
                self._show_window()
        except Exception:      # noqa: BLE001
            return
        if self._tray is not None:
            self._tray.update_menu(self._tray_items())

    def _poll_activate(self) -> None:
        """轮询「叫醒」事件：另一个实例双击时，收在托盘里的窗口要自己回来。"""
        try:
            if self._activator.wait(0):
                self._show_window()
                if self._tray is not None:
                    self._tray.update_menu(self._tray_items())
                self.logline("另一个实例请求显示窗口，已显示并聚焦。")
        except Exception:      # noqa: BLE001 - 轮询本身不该炸掉事件循环
            pass
        try:
            self.after(500, self._poll_activate)
        except Exception:      # noqa: BLE001 - 窗口已销毁
            pass

    def _sync_close_hint(self) -> None:
        """底栏一行当前行为；网格里那颗开关的文案跟着一起变（开关本体在网格里）。"""
        text = "关闭按钮：收进托盘" if self._close_to_tray else "关闭按钮：退出程序"
        try:
            self.lbl_close_hint.configure(text=text)
        except Exception:      # noqa: BLE001 - 控件替身/未建好
            pass
        self._sync_group_labels()

    def _sync_group_labels(self) -> None:
        """两颗带状态的开关按钮，文案对齐当前状态（网格里只有它们会变）。"""
        buttons = getattr(self, "_group_buttons", None) or {}
        pairs = (
            ("on_toggle_log_follow",
             "暂停日志跟随" if self._log_follow else "恢复日志跟随"),
            ("on_toggle_close_mode",
             "关闭窗口时：收进托盘" if self._close_to_tray else "关闭窗口时：退出程序"),
        )
        for name, text in pairs:
            button = buttons.get(name)
            if button is None:
                continue
            try:
                button.configure(text=text)
            except Exception:      # noqa: BLE001 - 控件替身
                pass

    def on_toggle_close_mode(self) -> None:
        """一键在「关闭收进托盘」与「关闭即退出」之间切换，并写回 config.json。"""
        want = not self._close_to_tray
        self._close_to_tray = want
        try:
            config.set_close_to_tray(want)
        except Exception as exc:      # noqa: BLE001 - 写不进去也要让本次生效
            self.logline(f"关闭行为没能写进 config.json：{exc}（本次仍然生效）")
        if want:
            if self._tray is None or not self._tray.running:
                self._start_tray()
            self.logline("关闭按钮＝收进托盘。")
        else:
            if self._tray is not None:
                self._tray.stop()
                self._tray = None
            self.logline("关闭按钮＝退出程序。")
        self._sync_close_hint()

    def _close_overlays(self) -> None:
        """收起浮层，并释放二维码的内存引用（不产生任何文件）。"""
        for attr in ("_qr_overlay", "_log_overlay"):
            layer = getattr(self, attr, None)
            if layer is None:
                continue
            try:
                layer.close()
            except Exception:      # noqa: BLE001 - 已经在销毁路径上
                pass
            setattr(self, attr, None)
        self.clear_qr()

    def _on_close(self) -> None:
        """关闭按钮：收进托盘（可一键改回退出），绝不悄悄退掉。"""
        if self._close_to_tray and self._tray is not None:
            self._close_overlays()
            try:
                self.withdraw()
            except Exception:      # noqa: BLE001
                self._quit()
                return
            self._tray.update_menu(self._tray_items())
            self.logline("已收进托盘；要退出请用托盘右键菜单「退出」。")
            return
        self._quit()

    def _quit(self) -> None:
        """真退出：先停后台线程（日志跟随、托盘），再销毁窗口。"""
        self._close_overlays()
        tail, self._tail = self._tail, None
        if tail is not None:
            tail.stop()
        tray_icon, self._tray = self._tray, None
        if tray_icon is not None:
            tray_icon.stop()
        relay, self._relay = getattr(self, "_relay", None), None
        if relay is not None:
            relay.stop()
        try:
            self.destroy()
        except Exception:      # noqa: BLE001 - 已经在销毁路径上
            pass

    def _set_icon(self) -> None:
        """标题栏图标：自绘 logo（PNG）优先，缺失回退仓库里的 .ico。"""
        if widgets.apply_window_icon(self):
            return
        candidates = _icon_candidates()
        for ico in candidates:
            try:
                if ico.is_file():
                    self.iconbitmap(default=str(ico))
                    return
            except Exception:  # noqa: BLE001
                pass

    # ---------------- UI ----------------
    # ---------------- 主界面 ----------------
    # 六段式单列信息流，全部直接 grid 在窗口上，不套中间容器：容器会把窗口底色铺满，
    # 玻璃背景板就透不出来了 —— 间隙必须留在窗口自己身上。
    # 列骨架固定 GRID_SUBCOLS 个等宽子列：3 列组卡各占 2 个、2 列各占 3 个、1 列占满 6 个，
    # 任何宽度下组卡都吃得满宽度，右边不会留一块洞。
    def _build(self) -> None:
        """头部 → 主操作 → 条件槽 → 功能网格 → 常驻日志 → 底栏。

        只有日志区有权拉伸（它的那一行 weight=1），窗口变高是日志变高，
        功能网格和主操作永远不会被挤掉。
        """
        # 整窗纵向滚动：所有区块挂在 self._page 上，窗口矮到放不下（最小 620x560）时
        # 由 CTkScrollableFrame 出滚动条，而不是把底栏裁到窗口外。
        self._page = ctk.CTkScrollableFrame(
            self, fg_color=BG, corner_radius=0,
            scrollbar_button_color=CARD3, scrollbar_button_hover_color=SLATE)
        self._page.place(x=0, y=0, relwidth=1, relheight=1)
        try:
            self._page._scrollbar.configure(width=10)
            # 内部画布尺寸一变就把内容高度钉成 max(视口, 内容最小高)：
            # 放得下时内容跟着窗口缩（不出现滚动条），放不下时才滚。
            self._page._parent_canvas.bind("<Configure>", self._on_page_resize, add="+")
        except Exception:      # noqa: BLE001 - CTk 内部结构变了
            pass
        for index in range(GRID_SUBCOLS):
            self._page.grid_columnconfigure(index, weight=1, uniform="col")
        self._columns = 0
        self._groups: list = []
        self._group_buttons: dict = {}
        self._panels: dict = {}
        self._glass_job = None
        self._badge_base = ""
        self._badge_photo = None
        self._log_empty = True
        # 玻璃背景板先建，之后建的控件自然叠在它上面（Tk 的叠放顺序 = 创建顺序）。
        self._backdrop = widgets.GlassBackdrop(self._page)
        self._backdrop.place(x=0, y=0, relwidth=1, relheight=1)
        self._build_header()
        self._build_primary()
        self._build_adopt()
        self._build_grid()
        self._build_log()
        self._build_foot()
        self._sync_group_labels()
        self._sync_log_rows()
        self._sync_log_empty()
        self._layout_group_cards()          # 建完就铺一次：等不到 Configure 也不会留空壳
        self.after_idle(self._layout_group_cards)
        self.bind("<Configure>", self._on_resize)
        self.after(60, self._schedule_glass)

    def _px(self, value: float) -> int:
        """逻辑像素 → 实际像素：150% 下截图里才不会把徽章与插画缩成一小坨。"""
        try:
            scale = self._get_window_scaling() or 1.0
        except Exception:      # noqa: BLE001 - 控件替身
            scale = 1.0
        return max(1, int(round(value * scale)))

    def _build_header(self) -> None:
        """头部：鲸鱼娘圆形玻璃徽章 + 标题 + 状态（灯/状态词/PID·端口），右端手机访问模式。"""
        header = ctk.CTkFrame(self._page, fg_color=CARD, corner_radius=CARD_RADIUS, height=HEADER_H)
        header.grid(row=0, column=0, columnspan=GRID_SUBCOLS, sticky="ew",
                    padx=PAD, pady=(PAD, 0))
        header.grid_propagate(False)
        header.grid_columnconfigure(2, weight=1)   # 弹性空列：把手机访问那块顶到右端
        # 两行都给 weight：多余的 24px 上下均分，徽章在 88px 的框里正好居中
        # （上一轮行高合计 68 > 头部 64，父框把玻璃圆盘的下弧裁掉了）。
        header.grid_rowconfigure(0, weight=1)
        header.grid_rowconfigure(1, weight=1)
        self._panels["header"] = header
        size = self._px(BADGE_SIZE)
        # corner_radius=size//2：底盘的四角跟面板同色，圆图之外不留方块
        self._badge_label = ctk.CTkLabel(header, text="", fg_color=CARD, width=size,
                                         height=size, corner_radius=size // 2)
        self._badge_label.grid(row=0, column=0, rowspan=2, padx=(11, 12), pady=0)
        ctk.CTkLabel(header, text=APP_TITLE, font=_font(13, True), text_color=TEXT,
                     anchor="w").grid(row=0, column=1, columnspan=2, sticky="w", pady=(10, 0))
        line = ctk.CTkFrame(header, fg_color=CARD)
        line.grid(row=1, column=1, sticky="w", pady=(0, 10))
        self.lamp = widgets.StatusLamp(line, bg=CARD)
        self.lamp.pack(side="left", padx=(0, 7))
        self.lbl_service = ctk.CTkLabel(line, text=PHASE_WORD[status.Phase.UNKNOWN],
                                        font=_font(15, True), text_color=TEXT, anchor="w")
        self.lbl_service.pack(side="left")
        # PID 与端口用等宽字体：数字在状态变化时不左右跳。
        self.lbl_detail = ctk.CTkLabel(line, text="PID — · 端口 —", font=_mono(11),
                                       text_color=DIM, anchor="w")
        self.lbl_detail.pack(side="left", padx=(12, 0))
        # 端口转发残留芯片：只在残留态 pack 进来（见 _apply_status），平时不占位置。
        self.lbl_residue = ctk.CTkLabel(line, text="", font=_font(11, True),
                                        text_color=AMBER, anchor="w", cursor="hand2")
        self.lbl_residue.bind("<Button-1>", lambda _event: self._on_residue_click())
        self.lbl_phone = ctk.CTkLabel(header, text="手机访问：—", font=_font(12),
                                      text_color=FAINT, anchor="e")
        self.lbl_phone.grid(row=0, column=3, rowspan=2, sticky="e", padx=(10, 14))
        self.lamp.set_status(status.Phase.UNKNOWN)

    def _build_primary(self) -> None:
        """主操作：通栏一颗，位置永远固定（第 2 行整行），宽度不随状态跳。

        启动/停止只留这一颗 —— 功能网格里的同名按钮已经删掉，同一个动作不再有两个入口。
        """
        self.btn_primary = ctk.CTkButton(
            self._page, text="启动 DSH", command=self._run_primary, height=ACTION_H,
            corner_radius=PRIMARY_RADIUS, font=_font(15, True), fg_color=PRIMARY,
            hover_color=PRIMARY_HOVER, text_color="#FFFFFF", border_width=2,
            border_color=PRIMARY, cursor="hand2")
        self.btn_primary.grid(row=1, column=0, columnspan=GRID_SUBCOLS, sticky="ew",
                              padx=PAD, pady=(GAP, 0))
        self._glow_hover(self.btn_primary)

    def _glow_hover(self, button) -> None:
        """悬停泛光：CTk 没有外发光，用 2px 亮边提亮代理（不动几何，不会跳）。"""
        def enter(_event=None) -> None:
            try:
                button.configure(border_color=CHIP_EDGE)
            except Exception:      # noqa: BLE001 - 已销毁
                pass

        def leave(_event=None) -> None:
            try:
                button.configure(border_color=button.cget("fg_color"))
            except Exception:      # noqa: BLE001
                pass

        button.bind("<Enter>", enter, add="+")
        button.bind("<Leave>", leave, add="+")

    def _build_adopt(self) -> None:
        """条件槽：异常时冒出「改为控制运行中的实例」，正常时整行收成 0 高。"""
        self._slot = ctk.CTkFrame(self._page, fg_color=CARD, height=0)
        self._slot.grid(row=2, column=0, columnspan=GRID_SUBCOLS, sticky="ew",
                        padx=PAD, pady=(6, 0))
        self._slot.grid_propagate(False)
        self._slot.grid_rowconfigure(0, weight=1)
        self._slot.grid_columnconfigure(0, weight=1)
        self.btn_adopt = ctk.CTkButton(
            self._slot, text="改为控制运行中的实例", command=self.on_adopt,
            fg_color=CARD2, hover_color=CARD3, text_color=TEXT, border_width=1,
            border_color=BORDER_STRONG, font=_font(12, True), height=GRID_BTN_H - 2,
            corner_radius=CHIP_RADIUS, cursor="hand2")

    def _build_grid(self) -> None:
        """功能网格：三组语义分组，组内 2 列按钮，列宽可测量且三组一致。

        三张组卡放在同一个容器里（容器左右内缩 PAD-GAP//2，每张卡左右各留 GAP//2）：
        于是每张卡的宽度都等于「列宽 - GAP」，卡间距是 GAP，最外侧仍是 PAD —— 三组卡
        等宽是构造出来的，不是碰巧对上的。
        """
        holder = ctk.CTkFrame(self._page, fg_color=BG)
        self._grid_holder = holder
        for index in range(GRID_SUBCOLS):
            holder.grid_columnconfigure(index, weight=1, uniform="grp")
        # 三张组卡由 _layout_group_cards() 用 place 摆放：卡宽必须严格相等，
        # 交给 grid 的 uniform 分列时余下的 1~2 像素会被 Tk 摊给某几列，
        # 同一列的 chip 右沿就会 441/442 混着。重摆由根窗口的 <Configure> 驱动 ——
        # CTkFrame.bind 只把回调挂到内部 canvas 上，容器自己的 <Configure> 一次都不会来。

        # 三组按钮行数取最大值（手机访问 5 项 = 3 行）：行数少的组把多出来的一行留白，
        # 于是同一窗口里每颗 chip 的高度处处相同 —— 否则「服务」2 行会被拉成「手机访问」
        # 3 行的 1.5 倍高，看着像两种控件。
        self._grid_rows_max = max(max(1, (len(entries) + 1) // 2)
                                  for _title, entries in ACTION_GROUPS)
        for group_index, (title, entries) in enumerate(ACTION_GROUPS):
            card = ctk.CTkFrame(holder, fg_color=CARD, corner_radius=CARD_RADIUS)
            # 组卡不跟内容要宽度：否则「开启手机访问（UAC）」这类长文案会把中间那张卡
            # 顶宽 22px，三组列宽就对不齐了。宽度完全由等宽列决定，内容只影响高度。
            card.grid_propagate(False)
            card.configure(height=self._px(
                30 + self._grid_rows_max * (GRID_BTN_H + GRID_PAD)))
            card.grid_columnconfigure(0, weight=1, uniform="chip")
            card.grid_columnconfigure(1, weight=1, uniform="chip")
            ctk.CTkLabel(card, text=title, font=_font(11, True), text_color=FAINT,
                         anchor="w").grid(row=0, column=0, columnspan=2, sticky="ew",
                                          padx=12, pady=(9, 6))
            for index, (icon, text, name) in enumerate(entries):
                row, column = divmod(index, 2)
                # 末行只剩一项 → 通栏：不留半行空洞
                alone = column == 0 and index == len(entries) - 1
                button = ctk.CTkButton(
                    card, text=f"{icon}  {text}", height=GRID_BTN_H,
                    corner_radius=CHIP_RADIUS, fg_color=CHIP, hover_color=CHIP_HOVER,
                    text_color=TEXT, border_width=1, border_color=BORDER,
                    # 11 号而非 12 号：3 列布局下片宽约 135 逻辑像素，最长文案
                    # 「关闭窗口时：收进托盘」在 12 号时会溢出裁掉末字。
                    font=_font(11), anchor="w", cursor="hand2",
                    command=getattr(self, name))
                button.grid(row=row + 1, column=column,
                            columnspan=2 if alone else 1, sticky="nsew",
                            padx=(10, 10) if alone else (10, 5) if column == 0 else (5, 10),
                            pady=(0, GRID_PAD))
                card.grid_rowconfigure(row + 1, weight=1, uniform="chiprow")
                self._glow_hover(button)
                self._group_buttons[name] = button
            # 空行也参与分配并共用 uniform：三组永远是同样多的行、行高相同，
            # 于是三组 chip 的高度处处一致（不会出现某组按钮被拉高一截）。
            for spare in range(len(entries) // 2 + 1, self._grid_rows_max + 1):
                card.grid_rowconfigure(spare, weight=1, uniform="chiprow")
            self._groups.append(card)
            self._panels["group%d" % group_index] = card

    def _build_log(self) -> None:
        """常驻日志：高度 = clamp(实际行数, 6, 26) 行，不再吸收剩余高度。

        剩余高度归三组卡那一行（root 第 3 行 weight=1）。日志卡自身只占「抬头 + 正文」，
        所以「4 行日志 + 40% 空区」这种场面不会再有：行数少，这一块就矮。
        """
        card = ctk.CTkFrame(self._page, fg_color=CARD, corner_radius=CARD_RADIUS)
        self._log_card = card
        self._panels["log"] = card
        card.grid_columnconfigure(0, weight=1)
        head = ctk.CTkFrame(card, fg_color=CARD)
        head.grid(row=0, column=0, sticky="ew", padx=12, pady=(8, 5))
        ctk.CTkLabel(head, text="运行日志", font=_font(12, True), text_color=TEXT,
                     anchor="w").pack(side="left")
        # 队列的即时说明是标题的注脚，贴着标题放，不单独占一行。
        self.lbl_queue = ctk.CTkLabel(head, text="", font=_font(11), text_color=DIM, anchor="w")
        self.lbl_queue.pack(side="left", padx=(10, 0))
        ctk.CTkButton(head, text="展开全屏", width=78, height=24, corner_radius=8,
                      fg_color=CHIP, hover_color=CHIP_HOVER, text_color=DIM,
                      border_width=1, border_color=BORDER, font=_font(11), cursor="hand2",
                      command=self.on_expand_log).pack(side="right")
        self.lbl_log_hint = ctk.CTkLabel(head, text="", font=_font(11), text_color=FAINT,
                                         anchor="e")
        self.lbl_log_hint.pack(side="right", padx=(0, 10))
        self.log = ctk.CTkTextbox(card, height=self._log_rows * LOG_LINE_PX,
                                  fg_color=PANEL_DEEP, text_color=LOG_TEXT, font=_mono(12),
                                  corner_radius=10, border_width=0, wrap="word",
                                  state="disabled")
        # sticky="ew" 而不是 "nsew"：正文不许再被父格拉高，高度只由行数决定
        self.log.grid(row=1, column=0, sticky="ew", padx=10, pady=(0, 10))
        self._harden_log_text()
        # 空态：同一格里盖一张插画 + 一句提示。素材缺失时 widgets 已经回退成矢量鲸鱼，
        # 所以这里永远有图形可看，不会出现「图片加载失败」的空框。
        self._empty = ctk.CTkFrame(card, fg_color=PANEL_DEEP, corner_radius=10)
        self._empty.grid(row=1, column=0, sticky="nsew", padx=10, pady=(0, 10))
        self._empty.grid_columnconfigure(0, weight=1)
        self._empty.grid_rowconfigure(0, weight=1)
        self._empty.grid_rowconfigure(3, weight=1)
        hero_px = self._px(HERO_SIZE)
        self._hero_photo = ctk.CTkImage(light_image=widgets.hero_picture(hero_px, PANEL_DEEP),
                                        dark_image=widgets.hero_picture(hero_px, PANEL_DEEP),
                                        size=(hero_px, hero_px))
        ctk.CTkLabel(self._empty, text="", image=self._hero_photo,
                     fg_color=PANEL_DEEP).grid(row=1, column=0, pady=(0, 0))
        ctk.CTkLabel(self._empty, text=EMPTY_LOG_HINT, font=_font(12), text_color=DIM,
                     fg_color=PANEL_DEEP, justify="center").grid(row=2, column=0, pady=(8, 0))


    def _harden_log_text(self) -> None:
        """把日志框的三种系统选中色钉死到调色板，并让选中区不参与剪贴板同步。

        上一轮截图在正文下沿有一条全宽 (0,115,208) 的蓝带 —— 那是 Tk Text 的**系统**
        选中背景（Windows 高亮色）透出来的：末行一旦被选中，选中区会铺满控件宽度。
        这里把 selectbackground / selectforeground / inactiveselectbackground 全换成
        主题色，insertwidth 归零（没有闪烁的插入光标），exportselection=False（焦点离开
        时不会保留高亮选区），并在每次写日志后主动清掉可能残留的 "sel" 标签。
        """
        try:
            inner = self.log._textbox
            inner.configure(selectbackground=CARD3, selectforeground=TEXT,
                            inactiveselectbackground=CARD2, exportselection=False,
                            insertwidth=0, insertbackground=LOG_TEXT, takefocus=0,
                            highlightthickness=0, borderwidth=0)
        except Exception:      # noqa: BLE001 - 控件替身 / CTk 内部结构变了
            return
        self._clear_log_selection()

    def _clear_log_selection(self) -> None:
        """清掉日志里的选中区：截图里那条蓝带就是它铺满整行造成的。"""
        try:
            self.log.tag_remove("sel", "1.0", "end")
        except Exception:      # noqa: BLE001 - 控件替身 / 已销毁
            pass

    def _build_foot(self) -> None:
        """底栏：本机入口 + 关闭按钮当前行为。做成一条玻璃条，不再是两截悬空的字。"""
        foot = ctk.CTkFrame(self._page, fg_color=CARD, corner_radius=CARD_RADIUS)
        self._foot = foot
        self._panels["foot"] = foot
        ctk.CTkLabel(foot, text="本机", font=_font(11), text_color=FAINT).pack(
            side="left", padx=(12, 6), pady=7)
        ctk.CTkLabel(foot, text="http://127.0.0.1:%d" % PORT, font=_mono(11),
                     text_color=DIM).pack(side="left")
        self.lbl_close_hint = ctk.CTkLabel(foot, text="", font=_font(11), text_color=FAINT,
                                           anchor="e")
        self.lbl_close_hint.pack(side="right", padx=(0, 12))
        self._sync_close_hint()

    # ---------------- 玻璃底图 / 重排 ----------------
    def _on_resize(self, event) -> None:
        """窗口尺寸变了：先重排列数（列数没变就什么都不做），再防抖重绘玻璃底图。"""
        if event.widget is not self:
            return
        self._reflow(event.width)
        # 列数没变时 _reflow 会早退，但卡宽/卡高仍要跟着容器走 —— 每次 Configure 都摆一遍；
        # 同一个 Configure 里容器尺寸可能还没结算，等空闲再摆一次收口。
        # 日志行数也在这里重算：它按「可用余高」取 clamp，不重算就会出现
        # 「窄高时撑到 15 行，再拉宽拉矮仍停 15 行」的残留，卡片被挤到 276 高、芯片被切。
        self._sync_log_rows()
        self._layout_group_cards()
        self.after_idle(self._sync_log_rows)
        self.after_idle(self._layout_group_cards)
        self._schedule_glass()

    def _reflow(self, width_px: int) -> None:
        """按可用宽度把三组卡片摆成 3 / 2 / 1 列，并把日志与底栏挪到卡片下方。"""
        try:
            scale = self._get_window_scaling() or 1.0
        except Exception:      # noqa: BLE001 - 控件替身 / 窗口已销毁
            scale = 1.0
        columns = grid_columns(width_px / scale)
        if columns == self._columns:
            return
        self._columns = columns
        rows = max(1, (len(self._groups) + columns - 1) // columns)
        holder = self._grid_holder
        # 容器左右内缩 PAD-GAP//2、每张卡左右各 GAP//2：卡宽 = 列宽 - GAP（三组严格等宽），
        # 卡间距 = GAP，最外侧正好落在 PAD 上，与头部/主按钮/底栏同一条竖线。
        holder.grid(row=3, column=0, columnspan=GRID_SUBCOLS, sticky="nsew",
                    padx=PAD - GAP // 2, pady=(0, 0))
        # 行权重要整体重置，不能只配当前 rows：窄→宽回落后（3 组从 2 行变回 1 行）
        # 上一次留下的空壳行仍是 weight=1，会和唯一那行平分高度，卡片被夹扁、芯片整组消失。
        for row_index in range(GRID_SUBCOLS):
            live = row_index < rows
            holder.grid_rowconfigure(row_index, weight=1 if live else 0,
                                     uniform="grow" if live else "")
        self._layout_group_cards()
        log_row = 4
        self._log_card.grid(row=log_row, column=0, columnspan=GRID_SUBCOLS, sticky="ew",
                            padx=PAD, pady=(GAP, 0))
        self._foot.grid(row=log_row + 1, column=0, columnspan=GRID_SUBCOLS, sticky="ew",
                        padx=PAD, pady=(GAP, PAD))
        # 剩余高度只给组卡那一行（第 3 行）；日志行与底栏都按内容高
        for row_index in range(log_row + 2):
            self._page.grid_rowconfigure(row_index, weight=1 if row_index == 3 else 0)

    def _layout_group_cards(self) -> None:
        """把三张组卡按当前列数铺进容器：等宽列 + sticky="nsew" 交给 grid 拉伸。

        不能用 place(width=..., height=...) —— CustomTkinter 的 place 直接抛
        ValueError("'width' and 'height' arguments must be passed to the constructor
        of the widget, not the place method")，而绕过它去 configure(width=...) 又会按
        逻辑像素再乘一次缩放，150% DPI 下卡片被放大 1.5 倍溢出窗口。
        等宽靠 uniform="g" + weight=1 保证：各列最大差 1 设备像素，三组同一列的
        chip 右沿实测完全一致（559 相对卡左沿逐像素相同）。
        """
        holder = self._grid_holder
        cards = self._groups
        cols = self._columns or 3
        if not cards:
            return
        span = max(1, GRID_SUBCOLS // cols)
        for slot in range(GRID_SUBCOLS):
            holder.grid_columnconfigure(slot, weight=1, uniform="grow")
        for index, card in enumerate(cards):
            row, column = divmod(index, cols)
            in_row = min(cols, len(cards) - row * cols)
            alone = column == 0 and in_row == 1
            card.grid(row=row, column=column * span,
                      columnspan=GRID_SUBCOLS - column * span if alone else span,
                      sticky="nsew", padx=(GAP // 2, GAP // 2), pady=(0, 0))

    def _schedule_glass(self) -> None:
        """<Configure> 会被拖动窗口逐像素触发：防抖，停手 140ms 后再画一次。"""
        job = getattr(self, "_glass_job", None)
        if job is not None:
            try:
                self.after_cancel(job)
            except Exception:      # noqa: BLE001
                pass
        try:
            self._glass_job = self.after(140, self._paint_glass)
        except Exception:      # noqa: BLE001 - 窗口已销毁
            self._glass_job = None

    def _paint_glass(self) -> None:
        """按当前真实几何重画整窗底图，并把每块面板的采样色回填给控件。"""
        self._glass_job = None
        try:
            page = getattr(self, "_page", None) or self
            width, height = page.winfo_width(), page.winfo_height()
            if width < 120 or height < 120:
                return
            scale = self._get_window_scaling() or 1.0
            origin_x, origin_y = self.winfo_rootx(), self.winfo_rooty()
            panels = []
            for key, panel in self._panels.items():
                if not panel.winfo_ismapped() or panel.winfo_height() < 8:
                    continue
                panels.append((key, "panel",
                               panel.winfo_rootx() - origin_x,
                               panel.winfo_rooty() - origin_y,
                               panel.winfo_width(), panel.winfo_height(), CARD_RADIUS))
            button = self.btn_primary
            panels.append(("primary", "glow",
                           button.winfo_rootx() - origin_x,
                           button.winfo_rooty() - origin_y,
                           button.winfo_width(), button.winfo_height(), PRIMARY_RADIUS))
            colors = self._backdrop.paint(width, height, scale, panels)
            for key, color in colors.items():
                panel = self._panels.get(key)
                if panel is not None and color and panel.cget("fg_color") != color:
                    panel.configure(fg_color=color)
            self._sync_badge(colors.get("header") or CARD)
            # 窗口高度变了 → 日志能占的像素也变了，重算一次行数（行数没变会早退）
            self._sync_log_rows()
        except Exception:      # noqa: BLE001 - 无显示环境 / 已销毁 / PhotoImage 失败
            return

    def _sync_badge(self, base: str) -> None:
        """徽章底盘的底色跟着面板采样色走，否则圆图的四角会在面板上留一个方块。"""
        size = self._px(BADGE_SIZE)
        if base == self._badge_base and self._badge_photo is not None:
            return
        self._badge_base = base
        picture = widgets.badge(size, base)
        self._badge_photo = ctk.CTkImage(light_image=picture, dark_image=picture,
                                         size=(size, size))
        try:
            self._badge_label.configure(image=self._badge_photo, fg_color=base,
                                        width=size, height=size)
        except Exception:      # noqa: BLE001
            pass

    def _min_page_height(self) -> int:
        """内容再压也压不下的最小高度（设备像素），低于它就出滚动条。

        按每个区块的真实请求高度求和，不再猜常量：芯片实际高度远大于
        GRID_BTN_H，用常量估会给出偏小的结论，导致最小窗口里卡片被压扁、
        滚动条又不出。日志卡按 LOG_ROWS_MIN 行的定值算，避免行数回写
        请求高度造成尺寸自激。
        """
        scale = self._get_window_scaling() or 1.0
        blocks = [self._panels.get("header"), self.btn_primary, self._slot,
                  self._grid_holder, self._panels.get("foot")]
        total = int((PAD * 2 + GAP * 5) * scale)
        total += int((LOG_ROWS_MIN * LOG_LINE_PX + 56) * scale)
        for block in blocks:
            if block is None:
                continue
            try:
                total += max(1, block.winfo_reqheight())
            except Exception:      # noqa: BLE001 - 已销毁
                continue
        return total

    def _on_page_resize(self, event) -> None:
        """把滚动宿主的内容高度钉在 max(视口高, 内容最小高)。"""
        try:
            need = self._min_page_height()
            height = max(int(event.height), need)
            self._page._parent_canvas.itemconfigure(self._page._create_window_id, height=height)
            # 放得下就把滚动条收起来（CTk 默认常显），放不下才露出来
            if height > int(event.height):
                self._page._scrollbar.grid()
            else:
                self._page._scrollbar.grid_remove()
        except Exception:      # noqa: BLE001 - 控件替身 / CTk 内部结构变了
            return

    def _log_room(self) -> float:
        """日志正文最多能占多少逻辑像素。

        绝不能按日志卡自己的位置/高度量：组卡那一行 weight=1 会吃掉剩余高度，日志卡就
        坐在它下面，「按自己的位置算」量到的其实是自己当前的高度 —— 自己证明自己，
        行数被自己锁死在 6 行。所以只按**固定栈**算：窗口高 - 头部 - 主按钮 - 条件槽 -
        组卡的自然高度（组内 2 列 N 行时的高度）- 底栏，再减日志卡自己的抬头行与内边距。
        """
        try:
            win_h = self.winfo_height()
            scale = self._get_window_scaling() or 1.0
        except Exception:      # noqa: BLE001 - 控件替身 / 还没布局
            return 10 ** 6
        if win_h <= 120:
            return 10 ** 6
        # 其它区块的占位一律取实测请求高度：用 GRID_BTN_H 这类常量估算会比芯片真实
        # 高度小一半，日志就会以为自己还有余量、擅自长到 10 行，把组卡压成一条缝。
        log_min = int((LOG_ROWS_MIN * LOG_LINE_PX + 56) * scale)
        fixed = self._min_page_height() - log_min
        return (win_h - fixed) / scale - 56                    # 56 = 抬头行 + 上下内边距

    def _log_line_count(self) -> int | None:
        """控件里真实的文本行数（Text 的 index("end-1c") 行号）；控件替身返回 None。"""
        try:
            return int(str(self.log.index("end-1c")).split(".")[0])
        except Exception:      # noqa: BLE001 - 控件替身 / 已销毁
            return None

    def _sync_log_rows(self) -> None:
        """日志区高度 = clamp(控件实际行数, LOG_ROWS_MIN, LOG_ROWS_MAX) 行。

        行数只认 Text 自己数的（index("end-1c")），所以 marker 里的 rows 与截图里的行数
        说的是同一件事。空态另有一条下限（LOG_ROWS_EMPTY）：不然 140px 的圆形头像会被
        6 行 = 96px 的格子裁掉。
        """
        total = self._log_line_count()
        if total is None:
            return
        # 空 Text 的 index("end-1c") 是 "1.0"（连空行都算 1 行），所以"空"不能只看行号：
        # 没有字就按 0 行走空态下限，否则 140px 的头像会被 6 行挤掉。
        empty = total <= 1 and not str(self.log.get("1.0", "end-1c")).strip()
        rows = log_rows_with_empty(0 if empty else total,
                                   self._log_room())      # 两边都是逻辑像素
        # 说明行每次都要刷新：首次布局时行数没变，若跟着早退回退就永远没文案。
        hint = getattr(self, "lbl_log_hint", None)
        if hint is not None:
            try:
                hint.configure(text="区域 %d 行 · 上限 %d 行" % (rows, MAX_LOG_LINES))
            except Exception:      # noqa: BLE001 - 控件替身
                pass
        if rows == self._log_rows:
            return
        self._log_rows = rows
        try:
            self.log.configure(height=rows * LOG_LINE_PX)
        except Exception:      # noqa: BLE001
            pass

    def _sync_log_empty(self, empty: bool | None = None) -> None:
        """空态：日志没字时把插画摆出来，有字就收起（同一格，永远只有一块可见）。"""
        if empty is None:
            try:
                empty = not self.log.get("1.0", "end-1c").strip()
            except Exception:      # noqa: BLE001 - 控件替身
                return
        if bool(empty) is bool(self._log_empty):
            return
        self._log_empty = bool(empty)
        try:
            if self._log_empty:
                self._empty.grid()
                self._empty.tkraise()
            else:
                self._empty.grid_remove()
        except Exception:      # noqa: BLE001
            pass
    # ---------------- helpers ----------------
    def logline(self, msg: str) -> None:
        self.log.configure(state="normal")
        self.log.insert("end", time.strftime("[%H:%M:%S] ") + msg + "\n")
        self._clear_log_selection()
        self._sync_log_empty(False)
        self._sync_log_rows()
        self._scroll_log_to_end()
        self._mirror_log()
        self.log.configure(state="disabled")

    def log_async(self, msg: str) -> None:
        """线程安全写日志：委托回 Tk 主线程，避免跨线程操作控件。

        窗口已销毁时 Tk 会拒绝投递（RuntimeError/TclError），此时退回 stderr，
        绝不让工作线程自己炸掉。
        """
        try:
            self.after(0, self.logline, msg)
        except Exception:  # noqa: BLE001 - 退出路径上窗口可能已经没了
            print(msg, file=sys.stderr)

    def _append_log(self, lines, prefix: str = "", limit: int = MAX_LOG_LINES) -> None:
        """往日志框追加若干行，超过上限就从顶部丢（滚动丢弃旧行）。"""
        try:
            self.log.configure(state="normal")
            for line in lines:
                self.log.insert("end", prefix + line + "\n")
            self._trim_log(limit)
            self._clear_log_selection()
            self._sync_log_empty(False)
            self._sync_log_rows()
            self._scroll_log_to_end()
            self._mirror_log()
            self.log.configure(state="disabled")
        except Exception:  # noqa: BLE001 - 窗口已销毁：没人看日志了
            pass

    def _scroll_log_to_end(self) -> None:
        """滚到末尾。用 yview_moveto 而不是 see("end")：see 要先算出末尾的 bbox，
        实测一次能吃掉 56 ms（日志几千行时更久），yview_moveto 近乎免费。"""
        try:
            self.log.yview_moveto(1.0)
        except Exception:  # noqa: BLE001 - 控件替身/已销毁
            try:
                self.log.see("end")
            except Exception:  # noqa: BLE001
                pass

    def _trim_log(self, limit: int = MAX_LOG_LINES) -> None:
        try:
            total = int(str(self.log.index("end-1c")).split(".")[0])
        except Exception:  # noqa: BLE001 - 控件替身/已销毁
            return
        if total <= limit:
            return
        try:
            self.log.delete("1.0", f"{total - limit + 1}.0")
        except Exception:  # noqa: BLE001
            pass

    def _mirror_log(self) -> None:
        """把主日志框的内容搬到全屏窗：内容早就在主框里打码并截断过，这里只搬运。"""
        overlay = self._log_overlay
        if overlay is None:
            return
        try:
            overlay.fill(self.log.get("1.0", "end-1c"))
            overlay.follow()
        except Exception:      # noqa: BLE001 - 浮层已关
            pass

    # ---------------- 串行队列（替代原来的全局 _busy） ----------------
    def _submit(self, name: str, work, on_done=None):
        """把一个后台操作放进串行队列：界面保持可点，排队中的还能取消。"""
        def run():
            try:
                return work()
            except Exception as exc:  # noqa: BLE001 - 后台异常必须显式落到日志
                self.log_async(f"出错：{exc}\n"
                               + errors.summarize(type(exc), exc, exc.__traceback__))
                raise
            finally:
                self._snapshot.invalidate()   # 操作之后的状态不该从旧缓存里拿
                self._post(self.refresh)
        return self._queue.submit(name, run, on_done)

    def _on_queue_change(self) -> None:
        """队首/排队数变了就更新一行说明；按钮从不因此被禁用。"""
        try:
            running = self._queue.running
            pending = self._queue.pending()
        except Exception:  # noqa: BLE001
            return
        if running is None and not pending:
            text = ""
        elif running is not None:
            text = f"⏳ 执行中：{running.name}"
            if pending:
                text += f"；排队中 {len(pending)} 个（可以取消）"
        else:
            text = f"⏳ 排队中（前面还有 {len(pending)} 个）"
        try:
            self.lbl_queue.configure(text=text)
        except Exception:  # noqa: BLE001
            pass

    def on_cancel_queue(self) -> None:
        """取消所有还在排队的任务（正在执行的不强杀，等它自己结束）。"""
        count = self._queue.cancel_all_pending()
        if count:
            self.logline(f"已取消 {count} 个排队中的任务；正在执行的那个会跑完。")
        else:
            self.logline("没有排队中的任务可取消。")

    def _on_callback_error(self, exc_type, exc, tb) -> None:
        """Tk 回调里的异常：写脱敏 traceback，绝不静默吞掉。"""
        text = errors.summarize(exc_type, exc, tb)
        try:
            self.logline("界面回调异常：\n" + text)
        except Exception:  # noqa: BLE001 - 日志框都坏了也不能把异常吞掉
            print("界面回调异常：\n" + text, file=sys.stderr)

    # ---------------- status ----------------
    def _load_status(self) -> "status.Status":
        """一次探测：原始数据留给诊断包，状态留给界面。"""
        raw = probe.probe_all(int(PORT), CFG.tailscale)
        state = status.probe_status_batch(CFG, raw=raw)
        self._last_raw = raw
        return state

    def on_refresh(self) -> None:
        """手动刷新：强制穿透缓存 —— 用户点它就是要看现在的真相。"""
        self.refresh(force=True)

    def refresh(self, force: bool = False) -> None:
        """非阻塞刷新：先显示上次结果 + 「刷新中…」，后台跑完再回填。

        探测要 spawn PowerShell（本机约 2 秒），绝不能放在主线程上：窗口打开、
        点刷新、任务结束时的刷新都走这条路，界面一次都不该冻住。
        """
        # 二维码不再随刷新清除：它住在浮层里，关掉浮层才清（否则刷一次闪一下）。
        self._show_refreshing()

        def work() -> None:
            try:
                state, _cached = self._snapshot.get(force=force)
            except Exception as exc:  # noqa: BLE001
                self.log_async(f"状态刷新失败：{exc}\n"
                               + errors.summarize(type(exc), exc, exc.__traceback__))
                self._post(self._show_refresh_failed, str(exc))
                return
            # token 要在后台线程里读：主线程读日志 + 正则会和探测线程抢 GIL
            self._post(self._apply_status, state, token_url())

        threading.Thread(target=work, daemon=True, name="dsh-refresh").start()

    def _show_refreshing(self) -> None:
        """刷新中：状态词保留，后面挂一句安静的「刷新中」，颜色不跳（避免闪）。"""
        try:
            if self._last_status is None:
                self.lbl_service.configure(text="检测中…", text_color=CYAN)
                return
            style = PHASE_STYLE[self._last_status.phase]
            self.lbl_service.configure(text=f"{self._last_status.phase.label} · 刷新中…",
                                       text_color=style.color)
        except Exception:  # noqa: BLE001 - 窗口已销毁
            pass

    def _show_refresh_failed(self, why: str) -> None:
        try:
            self.lbl_service.configure(text=f"状态未知（刷新失败：{why[:40]}）",
                                       text_color=FAINT)
        except Exception:  # noqa: BLE001
            pass

    def _apply_status(self, state: "status.Status", token: "str | None" = None) -> None:
        """回填一次状态：所有控件改动压在一次回调里，且每个控件只 configure 一次。

        这个函数跑在 Tk 主线程上，探测线程还在收尾时会跟它抢 GIL —— 实测空闲时
        一次 ~15 ms，抢 GIL 时一次 Tk 调用就要 20 ms 上下。所以这里的原则是
        「少调用」：能后台算的（token）都在后台算，网络细节只在变化时进日志。
        """
        self._last_status = state
        style = PHASE_STYLE[state.phase]
        self.lbl_service.configure(text=state.phase.label, text_color=style.color)
        self._sync_primary(state.phase)          # 主按钮的文案与颜色跟着状态走
        lamp = getattr(self, "lamp", None)
        if lamp is not None:
            lamp.set_status(state.phase)         # 灯：颜色 + 弧长 + 状态词
        self._sync_detail(state)
        if state.phone_open is None:
            phone_text, phone_color = "手机访问：未知", FAINT
        elif state.phone_open:
            phone_text, phone_color = "手机访问：已开启", GREEN
        else:
            phone_text, phone_color = "手机访问：本机模式", DIM
        self.lbl_phone.configure(text=phone_text, text_color=phone_color)
        residue_lbl = getattr(self, "lbl_residue", None)
        if residue_lbl is not None:
            if state.residue:
                residue_lbl.configure(text="端口转发残留 · 点此清理", text_color=AMBER,
                                      cursor="hand2")
                if not getattr(self, "_residue_shown", False):
                    residue_lbl.pack(side="left", padx=(12, 0))
                    self._residue_shown = True
            else:
                residue_lbl.configure(text="", cursor="")
                if getattr(self, "_residue_shown", False):
                    residue_lbl.pack_forget()
                    self._residue_shown = False
        self._token = token if token is not None else token_url()
        if state.notes:
            stamp = time.strftime("[%H:%M:%S] ")
            self._append_log([stamp + note for note in state.notes])
        self._log_net_once(state)
        self._candidates = _candidates_for(state, PORT,
                                           getattr(self, "_port_owner", None),
                                           self.logline)
        self._sync_adopt_button()
        auto_relay = getattr(self, "_maybe_auto_relay", None)
        if auto_relay is not None:      # 控件替身（tests/test_gui_hooks 的 FakeApp）没有这一手
            auto_relay(state)

    def _sync_detail(self, state: "status.Status") -> None:
        """状态条中段：PID 与端口。数字走等宽字体，刷新时宽度不抖。"""
        label = getattr(self, "lbl_detail", None)
        if label is None:            # 控件替身 / 还没建好
            return
        pids = "、".join(str(pid) for pid in (state.pids or [])) or "—"
        port = f"{PORT}（在线）" if state.port_open else f"{PORT}（离线）"
        try:
            label.configure(text=f"PID {pids} · 端口 {port}")
        except Exception:      # noqa: BLE001
            pass

    def _log_net_once(self, state: "status.Status") -> None:
        """网络细节（Tailscale / 局域网 / Token）只在变化时写日志。

        它们原来占状态卡三行，现在状态条只留一眼看得到的三个字段；细节不值得
        常驻占高度，但也不能凭空消失，所以变化时落到日志里。
        """
        ts = state.ts_ip or "未知"
        lans = "、".join(state.lan_ips) if state.lan_ips else "未知"
        line = (f"网络：Tailscale {ts} · 局域网 {lans} · "
                f"Token {'已获取' if self._token else '未获取'}")
        if line == getattr(self, "_last_net", ""):
            return
        self._last_net = line
        self.logline(line)

    def _sync_adopt_button(self) -> None:
        """异常（端口被占用）且查到占用者时才摆出采纳按钮；状态一正常就收起。

        按钮所在那一行（self._slot）跟着长高 / 收成 0：没有候选时不留空格子。
        控件替身（tests/test_gui_hooks.py 的 FakeApp）没有 _slot，getattr 直接跳过。
        """
        shown = bool(self._candidates)
        if shown:
            count = len(self._candidates)
            text = (f"改为控制运行中的实例（PID {self._candidates[0].pid}）" if count == 1
                    else f"改为控制运行中的实例（{count} 个候选，点击后选择）")
            self.btn_adopt.configure(text=text)
            if not self._adopt_shown:
                self.btn_adopt.pack(fill="both", expand=True)
                self._adopt_shown = True
        elif self._adopt_shown:
            self.btn_adopt.pack_forget()
            self._adopt_shown = False
        slot = getattr(self, "_slot", None)
        if slot is not None:
            try:
                slot.configure(height=GRID_BTN_H - 2 if shown else 0)
            except Exception:      # noqa: BLE001 - 控件替身
                pass

    # ---------------- 主操作 / 日志 / 浮层 ----------------
    def _run_primary(self) -> None:
        """主按钮：永远调当前状态对应的那颗老回调（不新写业务）。"""
        handler = getattr(self, "on_" + self._primary_name, None)
        if handler is not None:
            handler()

    def _sync_primary(self, phase) -> None:
        """按状态换主按钮的文案与颜色；文案是主体，颜色只是辅助。"""
        label, name, color, hover = primary_action(phase)
        self._primary_name = name
        button = getattr(self, "btn_primary", None)
        if button is None:          # 控件替身 / 还没建好
            return
        try:
            # 描边与底色同色：静息时看不见，悬停时由 _glow_hover 提亮成泛光。
            button.configure(text=label, fg_color=color, hover_color=hover,
                             border_color=color)
        except Exception:      # noqa: BLE001
            pass

    def on_toggle_log_follow(self) -> None:
        """日志跟随开关：关掉只是不再读新行，框里已有的内容照旧留着。"""
        if not self._log_follow:
            self._log_follow = True
            self._start_log_tail()
            self.logline("已恢复日志跟随。")
        else:
            tail, self._tail = self._tail, None
            self._log_follow = False
            if tail is not None:
                tail.stop()
            self.logline("已暂停日志跟随（再点一次同一颗按钮恢复）。")
        self._sync_group_labels()

    def on_expand_log(self) -> None:
        """全屏看日志：与主框同一份内容，关掉就回到末尾 15 行。"""
        overlay = self._log_overlay
        if overlay is not None:
            overlay.show()
            self._mirror_log()
            return
        self._log_overlay = widgets.LogOverlay(self, limit=MAX_LOG_LINES,
                                               on_close=self._on_log_overlay_closed)
        self._log_overlay.show()
        self._mirror_log()

    def _on_log_overlay_closed(self) -> None:
        self._log_overlay = None

    def on_change_port(self) -> None:
        """切换 Web 端口：写回 config.json 并刷新（新的端口下次启动生效）。"""
        global CFG, PORT
        dialog = ctk.CTkInputDialog(title="切换 Web 端口",
                                    text=f"当前端口 {PORT}，新端口（1-65535）：")
        raw = dialog.get_input()
        if raw is None:
            return
        try:
            port = addresses.validate_port(raw)
        except ValueError as exc:
            messagebox.showinfo("端口不合法", str(exc))
            return
        try:
            new_cfg = dataclasses.replace(CFG, port=port)
            config.save(new_cfg)
        except Exception as exc:      # noqa: BLE001 - 写不进去就别假装成功
            messagebox.showinfo("没能保存", f"{exc}")
            return
        CFG = new_cfg
        PORT = port
        self._snapshot.invalidate()
        self.logline(f"Web 端口已改为 {port}（下次启动 DSH 生效）。")
        self.refresh(force=True)

    def on_restart(self) -> None:
        """重启 = 停止 + 启动：两条既有路径按顺序走，不新增业务分支。"""
        self._submit("重启 DSH", self._restart)

    def _wait_port(self, want_open: bool, timeout: float) -> bool:
        """等端口变成想要的样子；超时就返回当下的真实状态（调用方据此说真话）。"""
        deadline = time.time() + timeout
        while True:
            current = bool(self._port_open())
            if current is want_open:
                return True
            if time.time() >= deadline:
                return False
            time.sleep(0.4)

    def _restart(self) -> None:
        """重启 = 真的先停再起：停完看到端口关掉才起，起完看到端口打开才报完成。

        旧版停在「_stop() 之后直接 _start()」：而 _start() 有一条「端口在线就别再拉」
        的守卫，上一份进程退得慢（或端口其实被另一处安装占着）时它静默跳过，
        于是重启看起来完全没反应。现在两步各自验证，失败就说清失败在哪。
        """
        pids, err = self._pids_provider()
        if pids is None:
            self.log_async(f"未知：node 进程查不到（{err}），重启前不结束任何进程。")
            return
        if not pids and self._port_open():
            self.log_async("重启中止：端口已被占用，但未确认 DSH 进程身份。请先刷新状态或接管实例。")
            return
        if not pids:
            self.log_async("没有正在运行的 DSH，直接启动。")
        else:
            listing = "\n".join(f"    PID {pid}" for pid in pids)
            if not self._ask_main(messagebox.askyesno, "重启确认",
                                  f"将先结束以下 node 进程再重新启动：\n{listing}\n\n"
                                  "当前网页会断开（会话已存档可重开）。继续吗？"):
                self.log_async("已取消重启，未结束任何进程。")
                return
            self._stop(pids)
            if not self._wait_port(False, 10.0):
                self.log_async(f"重启中止：{PORT} 仍然被占用，没有再拉起第二份 DSH。"
                               "若占用者是另一处安装，点「改为控制运行中的实例」接管它；"
                               "否则先「关闭 DSH」或手动结束占用进程。")
                self.refresh(force=True)
                return
        self._start(force=True)
        if self._wait_port(True, 25.0):
            left, _err = self._pids_provider()
            if not left:
                self.log_async("重启尚未验证：端口在线，但无法确认本机 DSH 进程。")
                self.refresh(force=True)
                return
            shown = "、".join(str(pid) for pid in left)
            self.log_async(f"重启完成：{PORT} 已在线（PID {shown}）。")
        else:
            self.log_async(f"重启未完成：{PORT} 在 25 秒内没有恢复监听，原因见上方启动输出。")
        self.refresh(force=True)

    def on_phone_access(self) -> None:
        """手机访问浮层：地址下拉 + 二维码 + 复制；主界面不再常驻二维码。"""
        if self._qr_overlay is not None:
            self._qr_overlay.show()
            return
        token = self._current_token()
        if not token:
            messagebox.showinfo("提示", "还没有可用的 token：请先启动 Harness。")
            return
        # 手里的 token 可能是过期的（DSH 被别处重启过）：先问一句服务，如实写进日志。
        # 这里不弹模态框 —— 自检会走这条路径，模态框会把 --selftest 挂死。
        stale = probe.token_accepted(PORT, token_suffix(token)) is False
        if stale:
            self.log_async("手机访问：token 被当前实例拒绝（401）——扫码只会看到认证失败。"
                           "多半是现在的 DSH 不是本控制台启动的；点「重启 DSH」可重签一把。")
        overlay = widgets.QrOverlay(self, on_close=self._on_qr_overlay_closed)
        self._qr_overlay = overlay
        try:
            overlay.hint.configure(text="token 可能已过期（当前实例不认这把钥匙），"
                                        "扫码会失败；点「重启 DSH」重签。"
                                   if stale else "正在探测手机可达地址…")
        except Exception:      # noqa: BLE001 - 浮层刚建就被关
            pass
        self._fill_qr_addresses()
        try:
            overlay.picker.configure(command=self._on_qr_pick)
            overlay.bind_actions(self.on_copy)
        except Exception:      # noqa: BLE001 - 浮层刚建就被关
            pass
        overlay.show()

    def _phone_plan_for_ui(self):
        """算一次手机访问计划；探测炸了返回 None（原因进日志，界面不许塌）。"""
        try:
            plan_obj = self._phone_planner(PORT, self.log_async)
        except Exception as exc:      # noqa: BLE001 - tailscale 没装/超时也不该带崩界面
            self.log_async(f"手机访问探测失败：{exc}")
            plan_obj = None
        self._phone_now = plan_obj
        return plan_obj

    def _fill_qr_addresses(self) -> None:
        """把手机访问计划的候选灌进下拉，并先画一张；一条都没有就说清下一步。"""
        overlay = self._qr_overlay
        if overlay is None:
            return
        plan_obj = self._phone_plan_for_ui()
        rows = phone_rows(plan_obj)
        choices = [text for text, _cand in rows] or [NO_PHONE_ROW]
        try:
            overlay.picker.configure(values=choices)
            overlay.picker.set(phone_default_row(plan_obj) or NO_PHONE_ROW)
        except Exception:      # noqa: BLE001 - 浮层刚建就被关
            pass
        self._on_qr_pick(phone_default_row(plan_obj) or NO_PHONE_ROW)

    def _on_qr_pick(self, choice: str = "") -> None:
        """选中哪条就画哪条；手机打不开的一律不画码，只写下一步。"""
        plan_obj = self._phone_now
        cand = phone_candidate(plan_obj, choice) if choice else phone_candidate(plan_obj)
        url = phone_candidate_url(cand, self._current_token())
        if url is None:
            self._show_phone_steps(plan_obj)
            return
        self._qr(url, "手机访问")

    def _show_phone_steps(self, plan_obj=None) -> None:
        """画不出二维码时：把「接下来该做什么」写进浮层那一格，旧码必须清掉。"""
        self._qr_photo = None
        self._qr_url = None
        text = phone_next_steps(plan_obj if plan_obj is not None else self._phone_now)
        overlay = self._qr_overlay
        if overlay is not None:
            try:
                overlay.image_label.configure(image=None, text=text, wraplength=232)
                overlay.hint.configure(text="二维码只在手机能打开时生成")
            except Exception:      # noqa: BLE001 - 浮层已销毁
                pass
        self.logline("手机二维码未生成：" + " / ".join(text.splitlines()))

    def _on_qr_overlay_closed(self) -> None:
        self._qr_overlay = None
        self.clear_qr()

    # ---------------- actions ----------------
    def on_adopt(self) -> None:
        """采纳正在跑的那处安装：把它的 harness 写回 config.json。"""
        self._submit("采纳运行中的实例", self._adopt)

    def _adopt(self) -> None:
        global CFG, HARNESS, TOKEN_LOG, PORT
        cands = list(self._candidates)
        if not cands:
            self.log_async("没有可采纳的候选进程（先刷新状态再试）。")
            return
        if len(cands) == 1:
            chosen = cands[0]
        else:
            index = self._ask_main(self._pick_candidate, cands)
            if index is None:
                self.log_async("已取消，config.json 未改动。")
                return
            chosen = cands[index]
        new_cfg, reason = adopt.adopt(CFG, chosen)
        if new_cfg is None:
            self.log_async(reason)
            self._ask_main(messagebox.showerror, "无法采纳", reason)
            return
        CFG, HARNESS, PORT = new_cfg, new_cfg.harness, new_cfg.port
        TOKEN_LOG = new_cfg.token_log
        self.log_async(reason)
        # 接管完要当场说清「接管到的这处到底在不在线」：config 指过去不等于它在跑。
        # （控件替身没有 _port_open，跳过这句判定，别为了测试把真实探测塞进去。）
        port_open = getattr(self, "_port_open", None)
        if port_open is None:
            pass
        elif port_open():
            self.log_async(f"接管完成：{PORT} 正在应答，后续启停都作用于这处安装。")
        else:
            self.log_async(f"注意：配置已指向 {new_cfg.harness}，但 {PORT} 现在没有应答"
                           "（那处实例可能刚好退出；直接点「启动 DSH」即可）。")
        # 采纳成功就没得选了：先把按钮收起来，别让用户对着一个过时的按钮再点一次。
        # （完整重探由 _wrap 的 finally 触发，探测要十几秒，等它回来才收太迟钝。）
        self._candidates = []
        self.after(0, self._sync_adopt_button)

    def _pick_candidate(self, cands: list) -> "int | None":
        """多个候选时让用户选序号，不默认第一个（选错就去控制错误的实例了）。"""
        listing = "\n".join(f"{i + 1}. {c.label}" for i, c in enumerate(cands))
        dialog = ctk.CTkInputDialog(
            text=f"检测到 {len(cands)} 处正在运行的 DSH，请输入要接管的序号：\n{listing}",
            title="选择要控制的实例")
        raw = dialog.get_input()
        if not raw:
            return None
        try:
            index = int(raw.strip()) - 1
        except ValueError:
            return None
        return index if 0 <= index < len(cands) else None
    def on_start(self) -> None:
        self._submit("启动 DeepSeek Harness", self._start)

    def _serve_host_arg(self) -> str:
        """当前 tailnet 的 MagicDNS 域名:80；查不到就空串（不猜地址）。

        为什么要它：tailscale serve 把请求转给 127.0.0.1，但 Host 头仍是域名。
        DSH 只放行 --trusted-host 里的 host，域名不在名单里就会 401/拒绝 ——
        以前只有「开启手机访问」那条路会传 -ServeHost，用户直接点「启动 DSH」
        时域名永远进不了名单，于是域名二维码怎么扫都不通。
        """
        try:
            detection = tailscale.detect()
        except Exception:      # noqa: BLE001 - 探测失败不该拦住启动
            return ""
        facts = getattr(detection, "facts", None)
        name = (getattr(facts, "dns_name", "") or "").strip()
        if not name:
            return ""
        return addresses.host_port(name, addresses.SCHEME_PORTS[addresses.SCHEME_HTTP])

    def _port_owner_text(self) -> str:
        """谁在听这个端口：给日志一行，查不到就说查不到（不猜）。"""
        owner = getattr(self, "_port_owner", None)
        if owner is None:
            return "占用者未知"
        try:
            candidate, why = owner(PORT)
        except Exception as exc:        # noqa: BLE001 - 探测失败只影响文案
            return f"占用者查不到（{exc}）"
        return candidate.label if candidate is not None else f"占用者查不到（{why or '没有匹配的进程'}）"

    def _token_is_fresh(self) -> bool:
        """日志是不是本次启动写的：不是就说明这把 token 属于别的实例，扫码只会 401。"""
        floor = getattr(self, "_start_epoch", 0.0)
        if not floor or TOKEN_LOG is None:
            return True
        try:
            return TOKEN_LOG.stat().st_mtime >= floor - 2.0
        except OSError:
            return False

    def _verify_token_after_start(self) -> None:
        """启动后立刻用日志里的 token 去问一次服务：认不认，当场说清。"""
        if not self._token_is_fresh():
            self.log_async("启动日志没有被这次启动刷新（多半被别的进程占着）：token 不可信，先别扫码。")
            return
        url = token_url()
        if not url:
            self.log_async("手机访问：启动日志里没有 token，二维码此时不可信（先点刷新状态）。")
            return
        state = probe.token_accepted(PORT, token_suffix(url))
        if state is True:
            self.log_async("手机访问：token 已验证通过（当前实例就是这次启动的）。")
        elif state is False:
            self.log_async(f"手机访问：token 被当前实例拒绝（401）——{PORT} 上答话的不是"
                           f"这次启动的进程（{self._port_owner_text()}），先「关闭 DSH」再启动一次。")
        else:
            self.log_async("手机访问：token 暂时验证不了（端口没应答），状态刷新后再说。")

    def _start(self, force: bool = False) -> None:
        # 「启动 DSH」现在是常驻可点的一颗按钮（不再只能从主按钮进去），
        # 所以这里加一道守卫：端口已经在线就不再加拉一份 DSH。
        # force=True 只给重启用：重启已经自己确认过端口关掉了，守卫在这儿会把它挡死。
        if self._port_open():
            self.log_async(f"{PORT} 已在监听：{self._port_owner_text()}。"
                           "不再起第二份 —— 起了也只会撞出 EADDRINUSE。要换成控制台这份，先点「关闭 DSH」。")
            return
        self.log_async("正在启动 DeepSeek Harness…")
        # 启动串行化闸：GUI/ps1/切换/重启四条路径互斥，同一时刻只有一个入口在拉起 DSH。
        lock = single.acquire_start_lock()
        if lock.blocked:
            self.log_async(f"启动被闸门拦住：{lock.reason}。稍后再点一次即可。")
            return
        try:
            # 主路径不走 ps1：launch-dsh.ps1 上有参数绑定、提权、「端口在线就只开浏览器」几道门，
            # 在控制台的非交互上下文里任何一道都会变成「点了没反应」。直接 Start-Process 拉起最短也最可控，
            # 参数与日志文件仍与 ps1 约定一致，所以 token 照样可读、二维码照样可用。
            if not self._start_direct():
                self.log_async("直接启动没成功，回退到随包脚本…")
                r = run_ps(LAUNCH_PS1, *_ps_args(include_chrome=True), timeout=90)
                out = (r.stdout or "").strip()
                if out:
                    self.log_async(out[-300:])
                if not r.ok:
                    detail = ((r.why() or "") + " " + (r.stderr or "").strip()[-300:]).strip()
                    self.log_async(f"启动脚本返回失败：{detail or '没有更详细的输出'}")
            if not self._wait_port(True, 20.0):
                self.log_async("启动失败：端口 20 秒内没有起来，请查看 dsh-web.stderr.log。")
                return
            started_pids, started_err = self._pids_provider()
            if not started_pids:
                self.log_async(f"启动尚未验证：端口在线，但无法确认 DSH 进程（{started_err or '未匹配'}）。")
                return
            self.log_async("启动完成：已识别本机 DSH 进程并确认端口在线。")
            self._verify_token_after_start()
        finally:
            lock.release()

    def _start_direct(self) -> bool:
        """用 PowerShell Start-Process 直接拉起 dsh web，绕开 ps1 的全部门槛。返回是否拉起。"""
        node, bin_js, harness = CFG.node, CFG.bin_js, CFG.harness
        if not (node and bin_js and harness):
            self.log_async("直接启动失败：没探测到 node / bin.js / harness。")
            return False
        # 清日志要早于启动，且必须知道清没清掉：清不掉就是「文件里躺着上一次的 token」。
        self._start_epoch = time.time()
        stale = truncate_logs(TOKEN_LOG, CFG.stderr_log)
        if stale:
            self.log_async("这些日志没能清空（被别的进程占着）：" + "、".join(stale) +
                           " —— 里面的 token 可能是上一次的，扫码前先看一眼日志时间。")
        trusted = ["--trusted-host", f"127.0.0.1:{PORT}", "--trusted-host", f"localhost:{PORT}"]
        serve = self._serve_host_arg()
        if serve:
            trusted += ["--trusted-host", serve]
        command = build_direct_start_command(node, bin_js, harness, trusted,
                                             TOKEN_LOG or "", CFG.stderr_log or "",
                                             CFG.dsh_home or "")
        result = psrun.run_ps_cmd(command, timeout=30)
        if result.ok:
            self.log_async("已直接拉起 DSH（绕开启动脚本，参数与日志路径一致）。")
            return True
        self.log_async(f"直接启动失败：{result.why() or result.text.strip()[:200]}")
        return False

    def on_stop(self) -> None:
        """先查出将被结束的 PID 让用户确认，再动手；不确定就一个都不杀。"""
        self._submit("停止 DeepSeek Harness", self._stop_prepare)

    def _stop_prepare(self) -> None:
        pids, err = self._pids_provider()
        if pids is None:
            self.log_async(f"未知：node 进程查不到（{err}），已取消停止，避免误杀。")
            self._ask_main(messagebox.showerror, "无法停止",
                           f"查不到正在运行的 node 进程：\n{err}\n\n"
                           "无法确认哪些进程是 DSH，本次没有结束任何进程。")
            return
        if not pids:
            self.log_async("没有找到正在运行的 DSH 进程，未做任何操作。")
            self._ask_main(messagebox.showinfo, "未在运行", "没有找到正在运行的 DSH 进程。")
            return
        listing = "\n".join(f"    PID {pid}" for pid in pids)
        bin_js = str(CFG.bin_js) if CFG.bin_js else "（未探测到 bin.js）"
        if not self._ask_main(messagebox.askyesno, "停止确认",
                              f"将结束以下 node 进程：\n{listing}\n\n"
                              f"识别依据：命令行里含\n    {bin_js}\n\n"
                              "当前网页会断开（会话已存档可重开）。继续吗？"):
            self.log_async("已取消停止，未结束任何进程。")
            return
        self.log_async(f"准备结束 PID：{'、'.join(str(p) for p in pids)}")
        self._stop(pids)

    def _stop(self, pids: list[int]) -> None:
        for pid in pids:
            result = psrun.run_ps_cmd(
                f"Stop-Process -Id {int(pid)} -Force -ErrorAction Stop; 'stopped'")
            if result.ok and "stopped" in result.stdout:
                self.log_async(f"已结束 node.exe PID {pid}")
            else:
                self.log_async(f"停止 PID {pid} 失败：{result.why() or result.text.strip()[:200]}")
        for _ in range(20):
            time.sleep(0.3)
            if not self._port_open():
                break
        if self._port_open():
            left, err = self._pids_provider()
            if left is None:
                self.log_async(f"警告：{PORT} 仍在监听，且剩余进程查不到（{err}）。")
            else:
                shown = "、".join(str(pid) for pid in left) or "无"
                self.log_async(f"警告：{PORT} 仍在监听，未完全停止（剩余 PID：{shown}）。")
            # 端口还在监听但已无 DSH 进程：通常是手机访问的端口转发残留。
            # 自动清理（切换脚本自带 UAC 提权；取消提权则保留原警告）。
            self._cleanup_residue()
        else:
            self.log_async("DeepSeek Harness 已停止。")

    def _on_residue_click(self) -> None:
        """状态条残留芯片的点击入口：清一遍转发残留，结果进日志。"""
        self._cleanup_residue()

    def _cleanup_residue(self) -> None:
        """检测并清理端口转发残留：成功/失败都如实写日志，最后强制刷新状态。"""
        targets, proxy_err = probe.portproxy_targets(int(PORT))
        if not targets:
            if proxy_err:
                self.log_async(f"端口转发状态查不到（{proxy_err}），未自动清理。")
            return
        self.log_async("检测到端口转发残留，正在清理（如弹出 UAC 请点「是」）…")
        result = self._run_switch(SWITCH_PS1, *_ps_args(), "-CleanupOnly", "-NoPause", timeout=120)
        if result.ok:
            self.log_async("端口转发残留清理完成。")
        else:
            self.log_async(f"端口转发残留清理失败：{result.why() or '没有更详细的输出'}。"
                           "可点「恢复本机模式」重试，或手动执行 netsh 清理。")
        self.refresh(force=True)

    def _ask_main(self, fn, *args):
        """在工作线程里等主线程弹一次对话框（Tk 控件只能主线程碰）。"""
        box: dict[str, object] = {}
        done = threading.Event()

        def call() -> None:
            try:
                box["value"] = fn(*args)
            finally:
                done.set()

        self.after(0, call)
        done.wait(timeout=120)
        return box.get("value")
    def on_phone_on(self) -> None:
        self._submit("开启手机访问", self._phone_on)

    def _phone_on(self) -> None:
        """开启手机访问：serve 已就绪就不提权；否则把 tailscale 的原话摆出来再跑脚本。"""
        plan_obj = self._phone_plan_for_ui()
        if plan_obj is not None and plan_obj.mode == phone.MODE_SERVE:
            self.log_async("tailscale serve 已就绪，不需要提权：" +
                           (plan_obj.qr_url or plan_obj.url or ""))
            return
        for line in phone_reason_text(plan_obj).splitlines():
            self.log_async("tailscale 说：" + line)     # 结构化 reason 原样展示
        self.log_async("正在开启手机访问（将弹出 UAC 提权窗口，请点“是”并等待）…")
        result = self._run_switch(SWITCH_PS1, *switch_args(plan_obj), "-NoPause", timeout=120)
        self.log_async((result.stdout or "").strip()[-400:] or "切换脚本已在后台运行。")
        warned = False
        for _ in range(40):
            time.sleep(0.5)
            ok, why = phone_ready()
            if ok is True:
                self.log_async("手机访问已开启。用“复制手机地址”把地址发到手机。")
                return
            if ok is None and not warned:
                self.log_async(f"未知：{why}（继续等待）")
                warned = True
        self.log_async("等待超时：请检查弹窗是否已确认提权。")
    def _maybe_auto_relay(self, state: "status.Status") -> None:
        """免 token 直连更常用，所以拿到 tailscale IP 就自动开一次（芯片仍可随时关）。

        只自动开一次：用户手动关掉之后不再偷偷打开 —— 那会让人怀疑开关是假的。
        """
        if getattr(self, "_relay_auto_done", False):
            return
        if getattr(self, "_relay", None) is not None:
            self._relay_auto_done = True
            return
        ip = getattr(state, "ts_ip", None)
        if not ip:
            return
        # 上一次运行留下的监听可能还没退干净（换 exe 重启时就是这样），一次失败不该
        # 让这条开关整场都打不开：给三轮回旋余地，真的还是占着才放弃。
        tries = getattr(self, "_relay_auto_tries", 0) + 1
        self._relay_auto_tries = tries
        relay = bridge.Relay(ip, dsh_port=PORT, token_provider=self._relay_token)
        try:
            relay.start()
        except OSError as exc:
            if tries < 3:
                self.logline(f"免 token 直连暂时开不起来：{exc}（{bridge.RELAY_PORT} 被占，稍后自动重试）")
                return
            self._relay_auto_done = True
            self.logline(f"免 token 直连没能自动开启：{exc}（端口 {bridge.RELAY_PORT} 被占）")
            return
        self._relay_auto_done = True
        self._relay = relay
        self.logline(f"免 token 直连已自动开启：手机打开 {relay.url}（仅 tailnet；点芯片可关）")
        self.after(0, self._sync_relay_chip)

    def on_toggle_relay(self) -> None:
        """免 token 直连：在 tailnet IP 上开一个只做 302 的小门（默认关）。"""
        self._submit("免 token 直连", self._toggle_relay)

    def _toggle_relay(self) -> None:
        relay = getattr(self, "_relay", None)
        if relay is not None and relay.running:
            relay.stop()
            self._relay = None
            self.log_async("已关闭免 token 直连（回到扫码/带 token 的地址）。")
        else:
            state = getattr(self, "_last_status", None)
            ip = getattr(state, "ts_ip", None) if state is not None else None
            if not ip:
                self.log_async("没探测到 Tailscale IP：先点「刷新状态」，再开直连。")
                return
            relay = bridge.Relay(ip, dsh_port=PORT, token_provider=self._relay_token)
            try:
                relay.start()
            except OSError as exc:
                self.log_async(f"免 token 直连起不来：{exc}（端口 {bridge.RELAY_PORT} 被占？先关掉再试）")
                return
            self._relay = relay
            self.log_async(f"免 token 直连已开启：手机打开 {relay.url} —— 只对 tailnet 成员开放，"
                           "它会把请求转成一把带 token 的地址，之后 :3080 也能直接开。")
        self.after(0, self._sync_relay_chip)

    def _relay_token(self) -> "str | None":
        """每次请求现取：DSH 重启换 token 后，直连自动跟上，不用重开开关。

        不新鲜就别给：宁可让手机看到「去点重启」那一页，也不要把一把失效的 token 跳过去。
        """
        if not self._token_is_fresh():
            return None
        url = token_url()
        return token_suffix(url) if url else None

    def _sync_relay_chip(self) -> None:
        button = getattr(self, "_group_buttons", {}).get("on_toggle_relay")
        if button is None:
            return
        relay = getattr(self, "_relay", None)
        running = bool(relay is not None and relay.running)
        try:
            button.configure(text=("⇥  免 token 直连：开" if running else "⇥  免 token 直连：关"),
                             border_color=(AMBER if running else BORDER))
        except Exception:      # noqa: BLE001 - 控件替身/已销毁
            pass

    def on_phone_off(self) -> None:
        if not messagebox.askyesno("恢复本机", "确定恢复本机模式并关闭手机访问吗？\n（会重启 DSH 服务，当前网页会断开）"):
            return
        self._submit("恢复本机模式", self._phone_off)

    def _phone_off(self) -> None:
        """恢复本机：先撤 tailscale serve（失败原样说），再撤端口转发与防火墙。"""
        self.log_async("正在恢复本机模式（UAC 提权窗口请点“是”）…")
        reason = self._serve_reset()
        if reason is not None:
            self.log_async("tailscale 说：" + reason.text)   # 不自己编文案
        r = self._run_switch(SWITCH_PS1, *_ps_args(), "-Restore", "-NoPause", timeout=120)
        self.log_async((r.stdout or "").strip()[-300:] or "已提交。")

    # ---------------- 地址选择（C4：下拉 + 可改端口，不再手输 IP） ----------------
    def _current_token(self) -> "str | None":
        return getattr(self, "_token", None) or token_url()

    def _address_options(self, kinds=None) -> "tuple[list, list[str]]":
        """(可选地址行, 未知项说明)。用最近一次状态，没刷新过就只给本机。"""
        state = self._last_status
        if state is None:
            rows = [(addr.display(PORT), addr)
                    for addr in addresses.build(None, None, None, port=PORT)]
        else:
            rows = addresses.menu(state.ts_ip, state.lan_ips, state.lan_sources,
                                  port=PORT, ts_error=state.ts_error,
                                  lan_error=state.lan_error)
        known = [(text, addr) for text, addr in rows if addr is not None]
        if kinds:
            known = [(text, addr) for text, addr in known if addr.kind in kinds]
        unknown = [text for text, addr in rows if addr is None]
        return known, unknown

    def _ask_address(self, title: str, kinds=None, rows=None,
                     editable_port: bool = True) -> "tuple | None":
        """选地址（可选改端口）。返回 (地址项, port)；取消或没有可选项返回 None。

        rows 直接给候选（手机访问的 Candidate）：端口由候选自带，不再让人改。
        """
        if rows is not None:
            known, unknown = list(rows), []
        else:
            known, unknown = self._address_options(kinds)
        if not known:
            detail = "；".join(unknown) or "探测结果为空"
            messagebox.showinfo("没有可用地址", f"未检测到可用地址：\n{detail}")
            return None
        picked: dict = {}
        win = ctk.CTkToplevel(self)
        win.title(title)
        win.geometry("560x310" if editable_port else "560x230")
        win.resizable(False, False)
        win.configure(fg_color=BG)
        win.transient(self)
        ctk.CTkLabel(win, text=title, font=_font(14, True), text_color=TEXT,
                     anchor="w").pack(fill="x", padx=18, pady=(16, 8))
        ctk.CTkLabel(win, text="访问地址", font=_font(11), text_color=DIM,
                     anchor="w").pack(fill="x", padx=18)
        displays = [text for text, _addr in known]
        menu = ctk.CTkOptionMenu(win, values=displays, width=520, height=34,
                                 fg_color=CARD2, button_color=SLATE,
                                 button_hover_color=SLATE_DARK, text_color=TEXT,
                                 font=_font(11), dropdown_font=_font(11),
                                 dynamic_resizing=False)
        menu.set(displays[0])
        menu.pack(padx=18, pady=(2, 10))
        port_entry = None
        if editable_port:
            port_row = ctk.CTkFrame(win, fg_color="transparent")
            port_row.pack(fill="x", padx=18, pady=(0, 8))
            ctk.CTkLabel(port_row, text="端口", font=_font(11), text_color=DIM,
                         width=60, anchor="w").pack(side="left")
            port_entry = ctk.CTkEntry(port_row, width=120, height=32, fg_color=CARD2,
                                      border_color=BORDER, text_color=TEXT,
                                      font=_font(11))
            port_entry.insert(0, str(PORT))
            port_entry.pack(side="left", padx=(0, 10))
            ctk.CTkLabel(port_row, text="1-65535，默认 3080", font=_font(10),
                         text_color=FAINT, anchor="w").pack(side="left")
        if unknown:
            # 探测失败必须显式写原因，不许静默给个空列表
            ctk.CTkLabel(win, text="；".join(unknown), font=_font(10),
                         text_color=FAINT, anchor="w", justify="left",
                         wraplength=500).pack(fill="x", padx=18)
        err = ctk.CTkLabel(win, text="", font=_font(10), text_color=RED, anchor="w")
        err.pack(fill="x", padx=18, pady=(4, 0))

        def confirm() -> None:
            index = displays.index(menu.get()) if menu.get() in displays else 0
            if not editable_port:
                picked["value"] = (known[index][1], PORT)   # 候选自带端口
                win.destroy()
                return
            try:
                port = addresses.validate_port(port_entry.get())
            except ValueError as exc:
                err.configure(text=str(exc))     # 就地提示，不弹第二个窗口
                return
            picked["value"] = (known[index][1], port)
            win.destroy()

        buttons = ctk.CTkFrame(win, fg_color="transparent")
        buttons.pack(fill="x", padx=18, pady=(8, 14))
        ctk.CTkButton(buttons, text="取消", width=96, height=32, corner_radius=8,
                      fg_color=CARD2, hover_color=SLATE_DARK, text_color=TEXT,
                      font=_font(11), command=win.destroy,
                      cursor="hand2").pack(side="right")
        ctk.CTkButton(buttons, text="确定", width=96, height=32, corner_radius=8,
                      fg_color=PRIMARY, hover_color=PRIMARY_HOVER, text_color="#FFFFFF",
                      font=_font(11, True), command=confirm,
                      cursor="hand2").pack(side="right", padx=(0, 10))
        win.bind("<Return>", lambda _e: confirm())
        win.bind("<Escape>", lambda _e: win.destroy())
        try:
            win.wait_visibility()
            win.grab_set()
        except Exception:  # noqa: BLE001 - 无窗口管理器/已销毁
            pass
        self.wait_window(win)
        return picked.get("value")

    def _pick_phone_address(self, rows, default=None):
        """候选选择框：只有一条就直接用，不拿弹窗打扰用户。"""
        if not rows:
            return None
        if len(rows) == 1:
            return rows[0][1]
        picked = self._ask_address("复制手机访问地址", rows=rows, editable_port=False)
        return picked[0] if picked else None

    def on_copy(self) -> None:
        """复制手机访问地址：只列手机能打开的候选，日志里 token 打码。"""
        token = self._current_token()
        if not token:
            messagebox.showinfo("提示", "还没有可用的 token：请先启动 Harness。")
            return
        plan_obj = self._phone_plan_for_ui()
        rows = [(text, cand) for text, cand in phone_rows(plan_obj) if cand.phone_reachable]
        if not rows:
            detail = phone_next_steps(plan_obj)
            for line in detail.splitlines():
                self.logline("手机地址不可用：" + line)
            messagebox.showinfo("没有手机可达地址", detail)
            return
        picked = self._pick_phone_address(rows, phone_default_row(plan_obj))
        if picked is None:
            self.logline("已取消，剪贴板没有改动。")
            return
        url = phone_candidate_url(picked, token)
        if url is None:
            self.logline("这条地址手机打不开，没有复制：" + picked.display())
            return
        self.clipboard_clear()
        self.clipboard_append(url)               # 剪贴板放完整地址：这是功能
        self.logline(f"已复制（{picked.label}）：" + textutil.redact(url))

    # ---------------- 诊断包（C3：整包脱敏） ----------------
    def on_export_diag(self) -> None:
        """导出脱敏诊断包：内容在写进 zip 之前就全部打码（见 diagnostics.build）。"""
        default = f"dsh-console-diag-{time.strftime('%Y%m%d-%H%M%S')}.zip"
        try:
            path = filedialog.asksaveasfilename(
                title="保存诊断包", defaultextension=".zip", initialfile=default,
                filetypes=[("ZIP 压缩包", "*.zip")])
        except Exception as exc:      # noqa: BLE001 - 没有可用的文件对话框
            self.logline(f"选择保存位置失败：{exc}")
            return
        if not path:
            return
        state, raw = self._last_status, self._last_raw

        def work() -> str:
            return str(diagnostics.export(path, cfg=CFG, status=state, raw=raw))

        self._submit("导出诊断包", work, on_done=self._on_diag_done)

    def _on_diag_done(self, task) -> None:
        if task.state is not tasks.State.DONE:
            reason = str(task.error or "未知原因")
            self.logline(f"诊断包导出失败：{reason}")
            messagebox.showerror("导出失败", f"没能生成诊断包：\n{reason}")
            return
        self.logline(f"诊断包已保存：{task.result}（token / 密钥已打码）")
        messagebox.showinfo("诊断包已生成",
                            f"{task.result}\n\n包里不含明文 token、cookie 或 API key。")

    def on_copy_local(self) -> None:
        token = self._current_token()
        if not token:
            messagebox.showinfo("提示", "还没有可用的 token：请先启动 Harness。")
            return
        self.clipboard_clear()
        self.clipboard_append(token)             # 剪贴板放完整地址
        self.logline("本机地址已复制：" + textutil.redact(token))

    def _qr(self, url: str, label: str) -> None:
        """生成二维码放进浮层：只在内存，关掉浮层即清除，不落盘。"""
        try:
            img = make_qr(url)
            ctk_img = ctk.CTkImage(light_image=img, dark_image=img,
                                   size=(img.width, img.height))
            self._qr_photo = ctk_img      # 保持引用防 GC
            self._qr_url = url           # 实际编码进二维码的地址
            overlay = self._qr_overlay
            if overlay is not None:
                overlay.image_label.configure(image=ctk_img, text="")
                overlay.hint.configure(text=f"{label} · {textutil.redact(url)}")
            self.logline(f"{label}二维码已生成（仅在内存，关闭浮层即清除）。")
        except Exception as exc:  # noqa: BLE001
            self.logline(f"二维码生成失败：{exc}")

    def clear_qr(self) -> None:
        """清除二维码（内存引用一并释放，不产生任何文件）。"""
        self._qr_photo = None
        self._qr_url = None
        overlay = self._qr_overlay
        if overlay is None:
            return
        try:
            overlay.image_label.configure(image=None, text="")
            overlay.hint.configure(text="")
        except Exception:      # noqa: BLE001 - 浮层已销毁
            pass

def _quiet_status() -> "status.Status":
    """自检用的状态替身：不探测本机、不受真实 DSH 影响，CI 里也不会拖慢。"""
    return status.Status(phase=status.Phase.STOPPED, pids=[], port_open=False,
                         phone_open=False, ts_ip=None, lan_ips=None, notes=[])


def _degraded_status(pid: int = 4321) -> "status.Status":
    """自检用：假装端口被另一处安装占着，用来验证采纳按钮的露出与收起。"""
    return status.Status(
        phase=status.Phase.DEGRADED, pids=[], port_open=True, phone_open=False,
        ts_ip=None, lan_ips=None, notes=[],
        others=[(pid, "C:\\自检\\node_modules\\@deepseek-ai\\dsh\\lib\\bin.js")])


def _running_status(pid: int = 4321) -> "status.Status":
    """自检用：五态里挑「运行中」验收状态环与主按钮（不碰真实进程）。"""
    return status.Status(phase=status.Phase.RUNNING, pids=[pid], port_open=True,
                         phone_open=True, ts_ip="100.124.206.105",
                         lan_ips=["192.168.1.20"], notes=[])


def selftest() -> int:
    """无窗口交互的自检：状态灯 / 主操作 / 功能网格 / 日志 / 浮层 / 布局。

    marker 字段名沿用批次 D 的格式（ring= 现在报的是状态灯的状态词，
    menu_items= 报的是功能网格里的按钮数），只在其后追加新字段。
    """
    app = ConsoleApp()
    app._status_provider = _quiet_status      # 自检不依赖本机真实端口与进程
    app._snapshot.invalidate()
    # 先让启动时的自动刷新（150ms 后）跑完，再逐块验证
    time.sleep(0.6)
    app.update()
    try:
        alpha_now = app.attributes("-alpha")      # 必须在 mainloop 之前取：窗口销毁后拿不到
    except Exception:      # noqa: BLE001 - 无合成器
        alpha_now = "-"

    # 状态灯 + 单主按钮：灯旁必须写着状态词（不能只靠颜色区分），按钮文案跟着变
    app._apply_status(_running_status())
    app.update()
    try:
        ring_text = app.lamp.phase_text
    except Exception:      # noqa: BLE001 - 拿不到就直接判失败
        ring_text = ""
    ok_ring = ring_text == PHASE_WORD[status.Phase.RUNNING]
    try:
        ok_primary = app.btn_primary.cget("text") == "停止 DSH"
    except Exception:      # noqa: BLE001
        ok_primary = False

    # 采纳按钮：异常（端口被占用）且有候选时露出，状态恢复正常后收起
    app._apply_status(_degraded_status())
    app.update()
    ok_adopt_shown = bool(app._candidates) and app._adopt_shown
    try:
        ok_primary_deg = app.btn_primary.cget("text") == "修复/重启"
    except Exception:      # noqa: BLE001
        ok_primary_deg = False
    app._apply_status(_quiet_status())
    app.update()
    ok_adopt_hidden = not app._candidates and not app._adopt_shown

    # 二维码住浮层：主界面不常驻，弹层关掉就清干净
    app._token = "selftest-token"    # 必须在最后一次 _apply_status 之后（否则被真 token 覆盖）
    # 手机访问替身：域名 + 100.x 两条候选，走纯计算，不碰真 tailscale
    app._phone_planner = lambda *args, **kwargs: _selftest_phone_plan(PORT)
    app.on_phone_access()
    app.update()
    ok_qr = app._qr_photo is not None
    plan_now = getattr(app, "_phone_now", None)
    phone_mode = getattr(plan_now, "mode", phone.MODE_NONE)
    phone_candidates = len(getattr(plan_now, "candidates", ()) or ())
    phone_qr = getattr(plan_now, "qr_url", None)
    phone_netloc = urlsplit(phone_qr).netloc if phone_qr else "none"
    phone_copy = phone_candidate_url(phone_candidate(plan_now), "selftest-token")
    # 有非回环候选时，二维码编进去的地址和「复制手机访问地址」都不许是 127.0.0.1
    ok_phone_qr = bool(phone_candidates and phone_qr and app._qr_url
                       and "127.0.0.1" not in phone_qr
                       and "127.0.0.1" not in app._qr_url)
    ok_phone_copy = bool(phone_copy) and "127.0.0.1" not in phone_copy
    ok_overlay_open = app._qr_overlay is not None
    app._close_overlays()
    app.update()
    ok_overlay_closed = app._qr_overlay is None and app._log_overlay is None
    ok_clear = app._qr_photo is None

    # 功能网格：全部操作平铺可见（没有「⋯」抽屉），每颗按钮都真的接上了回调
    try:
        buttons = dict(app._group_buttons)
        menu_items = len(buttons)
        texts = [button.cget("text") for button in buttons.values()]
        ok_menu = (menu_items == sum(len(entries) for _t, entries in ACTION_GROUPS)
                   and all(texts) and all(button.cget("command")
                                          for button in buttons.values()))
        # 文案前面带图标（例如「⇄  开启手机访问（UAC）」），断言按子串走。
        ok_phone_on = any("开启手机访问（UAC）" in (text or "") for text in texts)
        ok_toggle_label = "关闭窗口时：" in (buttons["on_toggle_close_mode"].cget("text") or "")
    except Exception:      # noqa: BLE001
        menu_items, ok_menu, ok_phone_on, ok_toggle_label = -1, False, False, False
    groups = len(getattr(app, "_groups", []))

    # 布局：三组卡片整块落在日志上方，日志不能被挤没，底栏不能掉出窗口
    app.update_idletasks()
    try:
        columns = app._columns
        root_y, win_h = app.winfo_rooty(), app.winfo_height()
        cards = [card for card in app._groups if card.winfo_ismapped()]
        grid_bottom = max(card.winfo_rooty() + card.winfo_height() - root_y
                          for card in cards)
        log_top = app.log.winfo_rooty() - root_y
        foot_bottom = (app.lbl_close_hint.winfo_rooty()
                       + app.lbl_close_hint.winfo_height() - root_y)
        # 卡片整块在日志上方、卡片与底栏都在窗口内、日志没被挤成一条缝
        ok_fit = (bool(cards) and grid_bottom <= log_top and foot_bottom <= win_h
                  and app.log.winfo_height() >= LOG_ROWS_MIN * LOG_LINE_PX * 0.8)
        # 主按钮通栏：右边缘要顶到窗口内边距，右侧不留死空间
        primary_right = app.btn_primary.winfo_x() + app.btn_primary.winfo_width()
        ok_primary_full = primary_right >= app.winfo_width() - 2 * PAD - 2
        # 日志高度按内容自适应，且永远落在上下限之内
        ok_rows = LOG_ROWS_MIN <= app._log_rows <= LOG_ROWS_MAX
        # 空态插画块与「日志是否为空」的实际值一致（该露就露，该收就收）
        ok_empty = app._log_empty == (not app.log.get("1.0", "end-1c").strip())
        # 玻璃背景板真的画出来了（不是空画布）
        ok_glass = getattr(app._backdrop, "_photo", None) is not None
        # marker 里的 rows 必须与视觉一致：行数由控件自己数（Text 的 index("end-1c")），
        # 高度由同一份行数算出。下面这一量发生在灌 2100 行之前 —— 那才是截图看到的一屏。
        rows_lines = app._log_line_count() or 0
        rows_shown = app._log_rows
        ok_rows = ok_rows and rows_shown == log_rows_with_empty(rows_lines, app._log_room())
        # ico 证据：文件路径 + 圆遮罩参数 + 徽章的实际设备像素
        icon_path = resources.icon_path()
        ico_field = ("%s|cut=cx%d,cy%d,r%d|dev=%dpx" % (
            icon_path.name if icon_path is not None else "none",
            widgets.AVATAR_CENTER[0], widgets.AVATAR_CENTER[1], widgets.AVATAR_RADIUS,
            app._px(BADGE_SIZE)))
    except Exception:      # noqa: BLE001
        columns, ok_fit, ok_primary_full, ok_rows, ok_empty, ok_glass = (
            -1, False, False, False, False, False)
        rows_lines, rows_shown, ico_field = -1, -1, "none"

    # 日志滚动上限：塞 2100 行后行数必须回到上限以内（C2）
    app._append_log([f"自检第 {i} 行" for i in range(MAX_LOG_LINES + 100)])
    app.update()
    try:
        log_lines = int(str(app.log.index("end-1c")).split(".")[0])
    except Exception:      # noqa: BLE001 - 取不到就直接判失败
        log_lines = -1
    ok_trim = 0 < log_lines <= MAX_LOG_LINES
    # 灌满 2000 行之后再量一次：日志长到上限也不许把页脚挤出窗口
    app.update_idletasks()
    try:
        root_y, win_h = app.winfo_rooty(), app.winfo_height()
        foot_bottom = (app.lbl_close_hint.winfo_rooty()
                       + app.lbl_close_hint.winfo_height() - root_y)
        scale = app._get_window_scaling() or 1.0
        shown = app.log.winfo_height() / scale
        ok_fit_full = (foot_bottom <= win_h
                       and app._log_rows * LOG_LINE_PX <= app._log_room() + 1
                       # 真被裁掉半行时：实际可用高度会小于声称的行数所需
                       and shown + 1 >= app._log_rows * LOG_LINE_PX)
    except Exception:      # noqa: BLE001
        ok_fit_full = False

    # 日志区高度由内容决定（不再是固定 15 行），展开全屏就是同一份内容
    app.on_expand_log()
    app.update()
    try:
        log_expanded = app._log_overlay is not None and app._log_overlay.line_count > 0
    except Exception:      # noqa: BLE001
        log_expanded = False
    log_collapsed = app._log_rows
    app._close_overlays()
    app.update()

    # 地址下拉：本机那一项永远在（C4 不该给出空列表）
    try:
        ok_addr = bool(app._address_options()[0])
    except Exception:      # noqa: BLE001
        ok_addr = False

    app.after(200, app.destroy)
    app.mainloop()
    ok = all([ok_qr, ok_clear, ok_adopt_shown, ok_adopt_hidden, ok_trim, ok_addr,
              ok_ring, ok_primary, ok_primary_deg, ok_menu, ok_overlay_open,
              ok_overlay_closed, ok_rows, log_expanded, ok_phone_on,
              ok_toggle_label, ok_fit, ok_primary_full, ok_empty, ok_glass,
              ok_fit_full, ok_phone_qr, ok_phone_copy])
    marker = Path(os.environ.get("TEMP", ".")) / "dsh-gui-selftest.txt"
    marker.write_text(
        f"OK {time.strftime('%Y-%m-%d %H:%M:%S')} qr={ok_qr} clear={ok_clear} "
        f"adopt_shown={ok_adopt_shown} adopt_hidden={ok_adopt_hidden} "
        f"log_lines={log_lines} trim={ok_trim} addresses={ok_addr} "
        f"ring={ring_text or '无'} menu_items={menu_items} "
        f"overlay_open={ok_overlay_open} overlay_closed={ok_overlay_closed} "
        f"log_collapsed={log_collapsed} log_expanded={log_expanded} "
        f"groups={groups} columns={columns} fit={ok_fit} "
        f"phone_on={ok_phone_on} toggle_label={ok_toggle_label} "
        # 以下是批次 F 追加的字段（旧字段名与顺序不动）
        f"primary_full={ok_primary_full} rows={rows_shown} rows_lines={rows_lines} "
        f"rows_ok={ok_rows} empty_state={ok_empty} glass={ok_glass} fit_full={ok_fit_full} "
        f"hero_art={widgets.art_image('hero') is not None} "
        f"ico={ico_field} "
        f"alpha={alpha_now} "
        # 手机访问那几项（phone-v2 接入后追加，前面的字段不动）
        f"phone_mode={phone_mode} phone_url={phone_netloc} "
        f"phone_reachable={bool(phone_qr)} phone_candidates={phone_candidates} "
        f"phone_qr_ok={ok_phone_qr} phone_copy_ok={ok_phone_copy} "
        "\n", encoding="utf-8")
    if sys.stdout:
        print(f"SELFTEST {'OK' if ok else 'FAILED'}")
    return 0 if ok else 1


def stop_selftest() -> int:
    """模拟完整点击路径：伪造 node 进程 → 跳过确认框 → on_stop → 验证被杀。

    替身走实例上的 _pids_provider / _status_provider（探测层本来就可注入），
    不再改写模块全局，也绝不碰真实的 DSH 进程。
    """
    node = shutil.which("node.exe") or r"D:\Program Files\nodejs\node.exe"
    fake = subprocess.Popen(
        [node, "-e", "setTimeout(()=>{},60000)", "bin.js", "web"],
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        creationflags=CREATE_NO_WINDOW)
    lines: list[str] = [f"fake_pid={fake.pid}"]
    alive, stopped, busy_left = True, False, True
    try:
        time.sleep(1.2)
        lines.append(f"detected={dsh_pids()}")     # 真探测层：伪造进程不该被认成本机 DSH
        app = ConsoleApp()
        app.withdraw()
        app._status_provider = _quiet_status
        app._snapshot.invalidate()
        # 只杀伪造进程：探测口返回它，进程一死就返回空
        app._pids_provider = lambda: ([] if fake.poll() is not None else [fake.pid], None)
        app._port_open = lambda: False            # 端口探测也注入，自检不受本机真实 3080 影响
        app._ask_main = lambda fn, *args: True     # 确认框一律「是」，自检不阻塞
        captured = {"log": "", "queue_idle": False}
        deadline = time.monotonic() + 12

        def finish() -> None:
            captured["log"] = app.log.get("1.0", "end")
            captured["queue_idle"] = app._queue.idle()   # 队列必须回到空闲（C5）
            app.destroy()

        def poll() -> None:
            # 真实事件循环在跑，工作线程投递回来的日志与状态都在这里被消费
            if "已停止" in app.log.get("1.0", "end") or time.monotonic() > deadline:
                app.after(300, finish)
            else:
                app.after(200, poll)

        app.after(0, app.on_stop)
        app.after(400, poll)
        app.mainloop()          # 必须进 mainloop：否则 after() 从工作线程投递会被 Tk 拒绝
        alive = fake.poll() is None
        stopped = "已停止" in captured["log"]
        busy_left = not captured["queue_idle"]
        lines.append(f"fake_alive_after_click={alive}")
        lines.append(f"log_has_stopped={stopped}")
        lines.append(f"queue_idle={not busy_left} pending={app._queue.pending()}")
        lines.append(f"log_snippet={captured['log'][:400]!r}")
        if alive:
            fake.kill()
    finally:
        if fake.poll() is None:
            fake.kill()
    marker = Path(os.environ.get("TEMP", ".")) / "dsh-stop-selftest.txt"
    marker.write_text("OK\n" + "\n".join(lines) + "\n", encoding="utf-8")
    ok = (not alive) and stopped and not busy_left
    if sys.stdout:
        print(f"STOP SELFTEST {'OK' if ok else 'FAILED'}")
    return 0 if ok else 1


def ensure_ready() -> bool:
    """探测不到 harness/node 时让用户选目录，写进 config.json 再继续。"""
    global CFG, HARNESS, TOKEN_LOG, PORT
    if CFG.ready:
        return True
    root = ctk.CTk()
    root.withdraw()
    chosen = ""
    try:
        messagebox.showinfo(
            "首次运行：DSH 装在哪？",
            "没有自动找到 DeepSeek Harness（它应含有 node_modules\\@deepseek-ai\\dsh 目录）。\n"
            "下一步请选择它的安装目录；选好后会记到 config.json，下次不再询问。",
            parent=root)
        chosen = filedialog.askdirectory(title="选择 DeepSeek Harness 安装目录", parent=root)
    finally:
        root.destroy()
    if chosen:
        CFG = config.resolve(explicit_harness=chosen)
        if CFG.ready:
            config.save(CFG)
            HARNESS, TOKEN_LOG, PORT = CFG.harness, CFG.token_log, CFG.port
            return True
    root = ctk.CTk()
    root.withdraw()
    try:
        messagebox.showerror(
            "无法启动",
            "仍然找不到可用的 DeepSeek Harness，或系统里没有 Node.js。\n"
            "请先装好 DSH 与 Node.js 再重新打开本程序；\n"
            "也可以直接编辑 config.json 指定 harness / node 路径。\n\n点「确定」退出。",
            parent=root)
    finally:
        root.destroy()
    return False


def _cli_error(message: str) -> None:
    """参数不合法：先写 stderr，双击启动（无控制台）时再弹窗，避免静默退出。"""
    print(message, file=sys.stderr)
    try:
        root = ctk.CTk()
        root.withdraw()
        try:
            messagebox.showerror("参数错误", message, parent=root)
        finally:
            root.destroy()
    except Exception:
        pass


def _utf8_stdio() -> None:
    """把 stdout/stderr 掰成 UTF-8：GBK 代码页下中文会显示成乱码。"""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError, OSError):
            pass  # 被重定向、已关闭或不是 TextIOWrapper：保持原样


def main() -> int:
    _utf8_stdio()
    if "--selftest" in sys.argv:
        return selftest()
    if "--stop-selftest" in sys.argv:
        return stop_selftest()
    global CFG, HARNESS, TOKEN_LOG, PORT, _APP
    try:
        want_harness, want_port = config.parse_cli(sys.argv[1:])
    except config.CliError as exc:
        _cli_error(str(exc))
        return 2
    # 单实例：双击第二次时把已有窗口拉到前台，绝不弹第二个主窗口。
    # 放在探测与首次运行询问之前 —— 第二个实例不该再问一遍「DSH 装在哪」。
    guard = single.acquire()
    if guard.blocked:
        # 已有实例可能收在托盘里：先发「叫醒」事件，它自己会显示并聚焦
        woken = single.signal_activate()
        if woken or single.focus_window(APP_TITLE):
            # 已经把它拉到眼前了，再弹一个「你在重复打开」的对话框只是多要一次点击。
            print("已经有一个 小肥鱼控制台 在运行，已把它的窗口显示出来；这个窗口不再打开。")
        else:
            _info_blocking(APP_TITLE,
                           "已经有一个 小肥鱼控制台 在运行（没能把它切到前台，请从任务栏打开）。"
                           "\n这个窗口不再打开。")
        return 0
    if want_harness is not None or want_port is not None:
        CFG = config.resolve(explicit_harness=want_harness, explicit_port=want_port)
        HARNESS, TOKEN_LOG, PORT = CFG.harness, CFG.token_log, CFG.port
    if not ensure_ready():
        return 1
    app = ConsoleApp()
    _APP = app
    errors.install(_report)      # sys / threading 两处钩子；Tk 回调那处由 app 自己挂
    if guard.acquired is None:
        app.logline(f"单实例检查已跳过：{guard.reason}")
    app.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
