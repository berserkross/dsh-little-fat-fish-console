"""DSH 控制台 - DeepSeek Harness 桌面图形界面 (customtkinter · 蓝鲸主题)

双击 exe / 运行本脚本即可打开窗口。功能与旧版一致：
  启动 Harness、开启手机访问（端口转发+信任来源）、恢复本机、复制手机地址、
  生成二维码（窗口内显示，刷新/关闭即清除，不落盘）、停止 Harness、实时查看状态。

UI 以 DeepSeek 品牌蓝 #4D6BFE 为主基调，深色科技风，头部展示 DeepSeek 鲸鱼娘图标。
"""
from __future__ import annotations

import os
import re
import shutil
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path
from tkinter import messagebox

import customtkinter as ctk
from PIL import Image

HARNESS = Path(r"C:\Users\Ibash\Documents\Codex\apps\deepseek-harness")
LAUNCH_PS1 = HARNESS / "launch-dsh.ps1"
SWITCH_PS1 = HARNESS / "switch-dsh-web.ps1"
TOKEN_LOG = HARNESS / "dsh-web.stdout.log"
ICON_FILE = "DeepSeekChan [256x256].ico"
SYSTEM_PS = "powershell.exe"
CREATE_NO_WINDOW = 0x08000000
PORT = 3080

# ---------------- 主题（DeepSeek 蓝） ----------------
PRIMARY = "#4D6BFE"        # DeepSeek 品牌蓝
PRIMARY_HOVER = "#3A55E0"
CYAN = "#35D5F4"
GREEN = "#2BB673"
GREEN_DARK = "#1E8F5B"
RED = "#F0526B"
RED_DARK = "#C93A52"
VIOLET = "#8B5CF6"
VIOLET_DARK = "#6F43D8"
TEAL = "#14B8A6"
TEAL_DARK = "#0D9488"
SLATE = "#44527A"
SLATE_DARK = "#34405E"
BG = "#070C1A"             # 窗口底色
CARD = "#0E1830"           # 卡片
CARD2 = "#152242"          # 次级卡片
BORDER = "#1D2B4F"
TEXT = "#E6EDF8"
DIM = "#8A97B8"
FAINT = "#5C6B8E"
WHITE_PANEL = "#FFFFFF"

FONT = "Microsoft YaHei UI"
MONO = "Consolas"


def _font(size: int, bold: bool = False) -> ctk.CTkFont:
    return ctk.CTkFont(family=FONT, size=size, weight="bold" if bold else "normal")


def _mono(size: int) -> ctk.CTkFont:
    return ctk.CTkFont(family=MONO, size=size)


# ---------------- 工具函数（与旧版一致） ----------------
def run_ps(script: Path, *args: str, timeout: int = 60) -> subprocess.CompletedProcess:
    return subprocess.run(
        [SYSTEM_PS, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script), *args],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        stdin=subprocess.DEVNULL, creationflags=CREATE_NO_WINDOW, timeout=timeout,
    )


def run_ps_cmd(command: str, timeout: int = 30) -> str:
    try:
        out = subprocess.run(
            [SYSTEM_PS, "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", command],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            stdin=subprocess.DEVNULL, creationflags=CREATE_NO_WINDOW, timeout=timeout,
        )
        return (out.stdout or "") + (out.stderr or "")
    except Exception as exc:  # noqa: BLE001
        return f"ERR {exc}"


def port_open(port: int = PORT, host: str = "127.0.0.1", timeout: float = 0.4) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def dsh_node_pids() -> list[int]:
    out = run_ps_cmd(
        "Get-CimInstance Win32_Process -Filter \"Name='node.exe'\" | "
        "Where-Object { $_.CommandLine -match 'bin\\.js web' } | "
        "Select-Object -ExpandProperty ProcessId"
    )
    return [int(x) for x in re.findall(r"\b\d{2,8}\b", out)]


def token_url() -> str | None:
    try:
        text = TOKEN_LOG.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    m = re.search(r"dsh web: (http://127\.0\.0\.1:3080/\?token=[A-Za-z0-9_\-]+)", text)
    return m.group(1) if m else None


def tailscale_ip() -> str | None:
    out = run_ps_cmd("& 'C:\\Program Files\\Tailscale\\tailscale.exe' ip -4")
    m = re.search(r"(\d+\.\d+\.\d+\.\d+)", out)
    return m.group(1) if m else None


def lan_ips() -> list[str]:
    ips: list[str] = []
    out = run_ps_cmd(
        "Get-NetIPAddress -AddressFamily IPv4 | Where-Object { $_.IPAddress -match '^(10|192\\.168|172\\.(1[6-9]|2\\d|3[01]))\\.' -and $_.IPAddress -notmatch '^100\\.' } | "
        "Select-Object -ExpandProperty IPAddress -Unique"
    )
    for ip in re.findall(r"\b(?:\d{1,3}\.){3}\d{1,3}\b", out):
        if ip not in ips and not ip.startswith("127."):
            ips.append(ip)
    return ips


def portproxy_enabled() -> bool:
    out = run_ps_cmd("netsh interface portproxy show all")
    return bool(re.search(r"\d+\.\d+\.\d+\.\d+\s+3080\s+127\.0\.0\.1\s+3080", out))


def firewall_rule() -> bool:
    out = run_ps_cmd("netsh advfirewall firewall show rule name=\"DSH Web 3080 access\"")
    return "DSH Web 3080 access" in out


def make_qr(url: str):
    """生成二维码 PIL 图像（仅在内存中，不落盘）。"""
    import qrcode  # 本地 venv 已安装

    qr = qrcode.QRCode(border=2, box_size=7)
    qr.add_data(url)
    qr.make(fit=True)
    return qr.make_image(fill_color="black", back_color="white").get_image()


def mascot_image() -> Image.Image | None:
    """读取 DeepSeek 鲸鱼娘图标（256x256 RGBA，取最大帧）。"""
    candidates = [
        Path(getattr(sys, "_MEIPASS", "")) / ICON_FILE,
        HARNESS / ICON_FILE,
    ]
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
        self.title("DSH 控制台")
        self._set_icon()
        self.geometry("720x880")
        self.minsize(660, 780)
        self.configure(fg_color=BG)
        self._busy = False
        self._qr_photo = None
        self._token: str | None = None
        self._build()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.after(150, self.refresh)

    def _on_close(self) -> None:
        """关闭窗口时清掉二维码缓存（内存引用一并释放，不落盘）。"""
        self.clear_qr()
        self.destroy()

    def _set_icon(self) -> None:
        candidates = [
            Path(getattr(sys, "_MEIPASS", "")) / ICON_FILE,
            HARNESS / ICON_FILE,
        ]
        for ico in candidates:
            try:
                if ico.is_file():
                    self.iconbitmap(default=str(ico))
                    return
            except Exception:  # noqa: BLE001
                pass

    # ---------------- UI ----------------
    def _build(self) -> None:
        # --- 头部：鲸鱼娘 + 标题 ---
        head = ctk.CTkFrame(self, fg_color=CARD, corner_radius=14,
                            border_width=1, border_color=BORDER)
        head.pack(fill="x", padx=14, pady=(14, 8))
        mascot = mascot_image()
        if mascot is not None:
            ctk.CTkLabel(head, text="", image=ctk.CTkImage(light_image=mascot, dark_image=mascot, size=(56, 56))).pack(side="left", padx=(16, 12), pady=12)
        title_box = ctk.CTkFrame(head, fg_color="transparent")
        title_box.pack(side="left", pady=10)
        ctk.CTkLabel(title_box, text="DeepSeek Harness 控制台", font=_font(17, True),
                     text_color=TEXT, anchor="w").pack(anchor="w")
        ctk.CTkLabel(title_box, text="本地入口 · 手机访问管理", font=_font(11),
                     text_color=DIM, anchor="w").pack(anchor="w")

        # --- 状态卡片 ---
        card = ctk.CTkFrame(self, fg_color=CARD, corner_radius=14,
                            border_width=1, border_color=BORDER)
        card.pack(fill="x", padx=14, pady=6)
        self.lbl_service = ctk.CTkLabel(card, text="服务状态：--", font=_font(12, True),
                                        text_color=FAINT, anchor="w")
        self.lbl_service.pack(fill="x", padx=14, pady=(12, 4))
        self.lbl_phone = ctk.CTkLabel(card, text="手机访问：--", font=_font(12, True),
                                      text_color=FAINT, anchor="w")
        self.lbl_phone.pack(fill="x", padx=14, pady=4)
        self.lbl_net = ctk.CTkLabel(card, text="网络：--", font=_font(11),
                                    text_color=DIM, anchor="w", justify="left")
        self.lbl_net.pack(fill="x", padx=14, pady=(4, 12))

        # --- 按钮区 ---
        grid = ctk.CTkFrame(self, fg_color="transparent")
        grid.pack(fill="x", padx=14, pady=6)
        for col in range(2):
            grid.columnconfigure(col, weight=1)
        buttons = [
            ("▶  启动 DeepSeek Harness", self.on_start, PRIMARY, PRIMARY_HOVER),
            ("⏹  停止 DeepSeek Harness", self.on_stop, RED, RED_DARK),
            ("📱  开启手机访问（需 UAC）", self.on_phone_on, GREEN, GREEN_DARK),
            ("🏠  恢复本机模式（需 UAC）", self.on_phone_off, SLATE, SLATE_DARK),
            ("📋  复制手机地址", self.on_copy, VIOLET, VIOLET_DARK),
            ("🔳  Tailscale 二维码", self.on_qr_ts, TEAL, TEAL_DARK),
            ("🔳  局域网 二维码", self.on_qr_lan, TEAL, TEAL_DARK),
            ("🔄  刷新状态", self.refresh, SLATE, SLATE_DARK),
        ]
        for i, (text, cmd, color, hover) in enumerate(buttons):
            btn = ctk.CTkButton(grid, text=text, command=cmd, fg_color=color,
                                hover_color=hover, text_color="#FFFFFF",
                                font=_font(12, True), height=42, corner_radius=10,
                                cursor="hand2")
            btn.grid(row=i // 2, column=i % 2, sticky="nsew", padx=4, pady=4)

        # --- 二维码卡片 ---
        qr_card = ctk.CTkFrame(self, fg_color=CARD, corner_radius=14,
                               border_width=1, border_color=BORDER)
        qr_card.pack(fill="x", padx=14, pady=6)
        ctk.CTkLabel(qr_card, text="手机地址二维码", font=_font(12, True),
                     text_color=TEXT, anchor="w").pack(fill="x", padx=14, pady=(10, 4))
        self.qr_label = ctk.CTkLabel(
            qr_card, text="点「二维码」按钮生成，直接显示在这里；\n刷新状态或关闭窗口后自动清除",
            font=_font(11), text_color=FAINT, width=252, height=252,
            fg_color=WHITE_PANEL, corner_radius=10)
        self.qr_label.pack(pady=(2, 12))

        # --- 日志卡片 ---
        log_card = ctk.CTkFrame(self, fg_color=CARD, corner_radius=14,
                                border_width=1, border_color=BORDER)
        log_card.pack(fill="both", expand=True, padx=14, pady=6)
        ctk.CTkLabel(log_card, text="运行日志", font=_font(12, True),
                     text_color=TEXT, anchor="w").pack(fill="x", padx=14, pady=(10, 4))
        self.log = ctk.CTkTextbox(log_card, height=150, fg_color="#0A1226",
                                  text_color="#C7D3EA", font=_mono(12),
                                  corner_radius=10, border_width=1, border_color=BORDER,
                                  wrap="word", state="disabled")
        self.log.pack(fill="both", expand=True, padx=12, pady=(0, 12))

        # --- 底栏 ---
        foot = ctk.CTkFrame(self, fg_color="transparent")
        foot.pack(fill="x", padx=14, pady=(0, 12))
        ctk.CTkLabel(foot, text="本机：http://127.0.0.1:3080", font=_font(11),
                     text_color=DIM, anchor="w").pack(side="left")
        ctk.CTkButton(foot, text="复制本机地址", command=self.on_copy_local, width=110,
                      height=28, corner_radius=8, fg_color=CARD2, hover_color="#1D2D55",
                      text_color=TEXT, font=_font(11), cursor="hand2").pack(side="right")

    # ---------------- helpers ----------------
    def logline(self, msg: str) -> None:
        self.log.configure(state="normal")
        self.log.insert("end", time.strftime("[%H:%M:%S] ") + msg + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def log_async(self, msg: str) -> None:
        """线程安全写日志：委托回 Tk 主线程，避免跨线程操作控件。"""
        self.after(0, self.logline, msg)

    def _thread(self, fn, *args) -> None:
        if self._busy:
            self.logline("上一操作还在进行中，请稍候…")
            return
        self._busy = True
        threading.Thread(target=self._wrap, args=(fn, *args), daemon=True).start()

    def _wrap(self, fn, *args) -> None:
        try:
            fn(*args)
        except Exception as exc:  # noqa: BLE001
            self.after(0, self.logline, f"出错：{exc}")
        finally:
            self._busy = False
            self.after(0, self.refresh)

    # ---------------- status ----------------
    def refresh(self) -> None:
        self.clear_qr()  # 刷新即清除旧二维码，避免堆积/残留
        def work() -> None:
            try:
                open_ = port_open()
                pids = dsh_node_pids()
                running = open_ or bool(pids)
                phone = portproxy_enabled() and firewall_rule()
                ts = tailscale_ip() or "未检测到"
                lans = ", ".join(lan_ips()) or "未检测到"
                token = token_url()
                self.after(0, lambda: self._apply_status(running, phone, ts, lans, token))
            except Exception as exc:  # noqa: BLE001
                self.after(0, self.logline, f"状态刷新失败：{exc}")
        threading.Thread(target=work, daemon=True).start()

    def _apply_status(self, running: bool, phone: bool, ts: str, lans: str, token: str | None) -> None:
        self.lbl_service.configure(
            text=("●  服务状态：运行中" if running else "○  服务状态：未运行"),
            text_color=(GREEN if running else RED))
        self.lbl_phone.configure(
            text=("●  手机访问：已开启（Tailscale / 局域网可访问）" if phone else "○  手机访问：本机模式"),
            text_color=(GREEN if phone else DIM))
        self.lbl_net.configure(
            text=f"Tailscale：{ts}\n局域网：{lans}\nToken：{'已获取（点「复制手机地址」发送）' if token else '未获取（启动后生成）'}")
        self._token = token

    # ---------------- actions ----------------
    def on_start(self) -> None:
        self._thread(self._start)

    def _start(self) -> None:
        self.log_async("正在启动 DeepSeek Harness…")
        r = run_ps(LAUNCH_PS1, timeout=90)
        out = (r.stdout or "").strip()
        if out:
            self.log_async(out[-300:])
        self.log_async("启动完成。")

    def on_stop(self) -> None:
        if not messagebox.askyesno("停止确认", "确定要停止 DeepSeek Harness 吗？\n（当前网页会断开，会话已存档可重开）"):
            return
        self._thread(self._stop)

    def _stop(self) -> None:
        pids = dsh_node_pids()
        if not pids:
            self.log_async("没有找到正在运行的 DSH 进程。")
            return
        for pid in pids:
            out = run_ps_cmd(f"Stop-Process -Id {pid} -Force -ErrorAction SilentlyContinue; 'done'")
            if "done" in out:
                self.log_async(f"已发出停止命令：node.exe PID {pid}")
            else:
                self.log_async(f"停止 PID {pid} 失败：{out.strip()[:200]}")
        for _ in range(20):
            time.sleep(0.3)
            if not port_open():
                break
        if port_open():
            left = dsh_node_pids()
            self.log_async(f"警告：3080 仍在监听，未完全停止（剩余 PID：{left or '未知'}）。")
        else:
            self.log_async("DeepSeek Harness 已停止。")

    def on_phone_on(self) -> None:
        self._thread(self._phone_on)

    def _phone_on(self) -> None:
        self.log_async("正在开启手机访问（将弹出 UAC 提权窗口，请点“是”并等待）…")
        r = run_ps(SWITCH_PS1, "-NoPause", timeout=90)
        self.log_async((r.stdout or "").strip()[-400:] or "切换脚本已在后台运行。")
        for _ in range(40):
            time.sleep(0.5)
            if portproxy_enabled():
                self.log_async("手机访问已开启。用“复制手机地址”把地址发到手机。")
                return
        self.log_async("等待超时：请检查弹窗是否已确认提权。")

    def on_phone_off(self) -> None:
        if not messagebox.askyesno("恢复本机", "确定恢复本机模式并关闭手机访问吗？\n（会重启 DSH 服务，当前网页会断开）"):
            return
        self._thread(self._phone_off)

    def _phone_off(self) -> None:
        self.log_async("正在恢复本机模式（UAC 提权窗口请点“是”）…")
        r = run_ps(SWITCH_PS1, "-Restore", "-NoPause", timeout=90)
        self.log_async((r.stdout or "").strip()[-300:] or "已提交。")

    def on_copy(self) -> None:
        token = getattr(self, "_token", None) or token_url()
        if not token:
            messagebox.showinfo("提示", "还没有可用的 token：请先启动 Harness。")
            return
        ips = ([tailscale_ip()] if tailscale_ip() else []) + lan_ips()
        urls = [f"http://{ip}:{PORT}/?token={token.split('token=')[1]}" for ip in ips]
        if not urls:
            messagebox.showinfo("提示", "未检测到可用的网络地址。")
            return
        self.clipboard_clear()
        self.clipboard_append("\n".join(urls))
        self.logline("手机地址已复制到剪贴板：\n  " + "\n  ".join(urls))

    def on_copy_local(self) -> None:
        token = getattr(self, "_token", None) or token_url()
        if not token:
            messagebox.showinfo("提示", "还没有可用的 token：请先启动 Harness。")
            return
        self.clipboard_clear()
        self.clipboard_append(token)
        self.logline("本机地址已复制：" + token)

    def on_qr_ts(self) -> None:
        token = getattr(self, "_token", None) or token_url()
        if not token:
            messagebox.showinfo("提示", "还没有可用的 token：请先启动 Harness。")
            return
        ts = tailscale_ip()
        if not ts:
            messagebox.showinfo("提示", "未检测到 Tailscale 地址。")
            return
        url = f"http://{ts}:{PORT}/?token={token.split('token=')[1]}"
        self._qr(url, "Tailscale")

    def on_qr_lan(self) -> None:
        token = getattr(self, "_token", None) or token_url()
        if not token:
            messagebox.showinfo("提示", "还没有可用的 token：请先启动 Harness。")
            return
        lans = lan_ips()
        if not lans:
            messagebox.showinfo("提示", "未检测到局域网地址。")
            return
        ip = lans[0]
        if len(lans) > 1:
            dialog = ctk.CTkInputDialog(
                text="检测到多个局域网地址，请输入要用的 IP：\n" + "\n".join(lans),
                title="选择地址")
            chosen = dialog.get_input()
            if not chosen:
                return
            ip = chosen.strip()
        url = f"http://{ip}:{PORT}/?token={token.split('token=')[1]}"
        self._qr(url, "局域网")

    def _qr(self, url: str, label: str) -> None:
        try:
            img = make_qr(url)
            ctk_img = ctk.CTkImage(light_image=img, dark_image=img,
                                   size=(img.width, img.height))
            self._qr_photo = ctk_img  # 保持引用防 GC
            self.qr_label.configure(image=ctk_img, text="", width=252, height=252,
                                    fg_color=WHITE_PANEL)
            self.logline(f"{label}二维码已显示在窗口中（仅在内存，刷新/关闭即清除）。")
        except Exception as exc:  # noqa: BLE001
            self.logline(f"二维码生成失败：{exc}")

    def clear_qr(self) -> None:
        """清除窗口内二维码（内存引用一并释放，不产生任何文件）。"""
        self._qr_photo = None
        try:
            self.qr_label.configure(image=None,
                                    text="点「二维码」按钮生成，直接显示在这里；\n刷新状态或关闭窗口后自动清除",
                                    width=252, height=252, fg_color=WHITE_PANEL)
        except Exception:  # noqa: BLE001
            pass


def selftest() -> int:
    app = ConsoleApp()
    # 先让启动时的自动刷新（150ms 后）跑完，再验证二维码显示/清除
    time.sleep(0.6)
    app.update()
    app._qr("http://100.124.206.105:3080/?token=selftest", "自检")
    app.update()
    ok_qr = app._qr_photo is not None
    app.clear_qr()
    app.update()
    ok_clear = app._qr_photo is None
    app.after(200, app.destroy)
    app.mainloop()
    marker = Path(os.environ.get("TEMP", ".")) / "dsh-gui-selftest.txt"
    marker.write_text(f"OK {time.strftime('%Y-%m-%d %H:%M:%S')} qr={ok_qr} clear={ok_clear}\n", encoding="utf-8")
    if sys.stdout:
        print("SELFTEST OK")
    return 0


def stop_selftest() -> int:
    """模拟完整点击路径：伪造 node 进程 → 跳过确认框 → on_stop → 验证被杀。"""
    import tkinter
    node = shutil.which("node.exe") or r"D:\Program Files\nodejs\node.exe"
    fake = subprocess.Popen(
        [node, "-e", "setTimeout(()=>{},60000)", "bin.js", "web"],
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        creationflags=CREATE_NO_WINDOW)
    lines: list[str] = [f"fake_pid={fake.pid}"]
    try:
        time.sleep(1.2)
        lines.append(f"detected={dsh_node_pids()}")
        real_dsh_node_pids = dsh_node_pids
        # 只杀伪造进程，绝不碰真实 584
        globals()["dsh_node_pids"] = lambda: [fake.pid]
        tkinter.messagebox.askyesno = lambda *a, **k: True  # type: ignore[assignment]
        app = ConsoleApp()
        app.withdraw()
        app.on_stop()
        stopped = False
        for _ in range(40):  # 最多 8 秒：先把 after 回调跑完，再判定
            app.update()
            time.sleep(0.2)
            if "已停止" in app.log.get("1.0", "end"):
                stopped = True
                break
            if fake.poll() is not None and not stopped:
                continue  # 进程已死但日志回调还没跑，继续 update
        alive = fake.poll() is None
        lines.append(f"fake_alive_after_click={alive}")
        lines.append(f"log_has_stopped={stopped}")
        lines.append(f"log_snippet={app.log.get('1.0', 'end')[:400]!r}")
        app.destroy()
        globals()["dsh_node_pids"] = real_dsh_node_pids
        if alive:
            fake.kill()
    finally:
        if fake.poll() is None:
            fake.kill()
    marker = Path(os.environ.get("TEMP", ".")) / "dsh-stop-selftest.txt"
    marker.write_text("OK\n" + "\n".join(lines) + "\n", encoding="utf-8")
    if sys.stdout:
        print("STOP SELFTEST DONE")
    return 0


def main() -> int:
    if "--selftest" in sys.argv:
        return selftest()
    if "--stop-selftest" in sys.argv:
        return stop_selftest()
    app = ConsoleApp()
    app.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
