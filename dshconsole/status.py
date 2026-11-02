"""状态模型：把「一堆布尔与起来」换成「一个阶段 + 明确的未知」。

v1 用 running = port_open or pids、phone = portproxy and firewall 拼状态：任一探测
失败都落成 False，于是「查不到」被显示成「未运行 / 本机模式」。这里每个探测保留三态
（True / False / None），阶段由固定规则算出，未知的原因写进 notes 直接进日志框。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Callable

from . import probe

LOCAL_HOSTS = ("127.0.0.1", "localhost")


class Phase(str, Enum):
    STOPPED = "stopped"
    STARTING = "starting"
    RUNNING = "running"
    DEGRADED = "degraded"
    UNKNOWN = "unknown"

    @property
    def label(self) -> str:
        return _PHASE_LABELS[self]


_PHASE_LABELS = {
    Phase.STOPPED: "未运行",
    Phase.STARTING: "启动中",
    Phase.RUNNING: "运行中",
    Phase.DEGRADED: "异常（端口被占用）",
    Phase.UNKNOWN: "未知",
}


@dataclass(frozen=True)
class Status:
    """一次刷新的完整结论。None 一律表示「未判定」，不是 False。"""

    phase: Phase
    pids: list[int] | None = None                        # None = 进程列表未判定
    port_open: bool | None = None
    phone_open: bool | None = None                       # 端口转发指向本机端口 + 防火墙规则都在
    phone_targets: list[tuple[str, int]] | None = None   # 当前转发指向的 (地址, 端口)
    ts_ip: str | None = None
    lan_ips: list[str] | None = None
    notes: list[str] = field(default_factory=list)        # 人话：哪些项没查到、为什么
    others: list[tuple[int, str]] | None = None            # DEGRADED 时的占用者候选（pid, bin.js）


def _points_local(targets: list[tuple[str, int]], port: int) -> bool:
    return any(host.lower() in LOCAL_HOSTS and target_port == port
               for host, target_port in targets)


def phone_state(targets: list[tuple[str, int]] | None, firewall: bool | None,
                port: int) -> bool | None:
    """手机访问 = 转发指向本机这个端口 + 防火墙放行。任一未知就整项未知。"""
    if targets is None or firewall is None:
        return None
    return bool(_points_local(targets, port) and firewall)


def probe_phone(cfg, *, portproxy: Callable | None = None,
                firewall: Callable | None = None) -> tuple[bool | None, list[tuple[str, int]] | None, list[str]]:
    """(是否开启 / 未定, 转发目标, 说明)。GUI 的「等待手机访问生效」也走这里。"""
    get_proxy = portproxy or probe.portproxy_targets
    get_firewall = firewall or probe.firewall_rule
    port = int(cfg.port)
    notes: list[str] = []
    targets, proxy_err = get_proxy(port)
    allowed, firewall_err = get_firewall(port)
    if targets is None:
        notes.append(f"未知：端口转发查不到（{proxy_err}）")
    elif targets and not _points_local(targets, port):
        shown = "、".join(f"{host}:{target_port}" for host, target_port in targets)
        notes.append(f"端口 {port} 的转发指向 {shown}，不是本机 127.0.0.1:{port}，"
                     "手机访问不算开启。")
    if allowed is None:
        notes.append(f"未知：防火墙规则查不到（{firewall_err}）")
    elif not allowed and targets is not None and _points_local(targets, port):
        notes.append(f"防火墙里没有「{probe.FIREWALL_RULE.format(port=port)}」这条规则："
                     "手机能连到端口，但入站可能被防火墙挡住。")
    return phone_state(targets, allowed, port), targets, notes


def probe_status(cfg, *, processes: Callable | None = None, port_open: Callable | None = None,
                 portproxy: Callable | None = None, firewall: Callable | None = None,
                 tailscale: Callable | None = None, lan: Callable | None = None,
                 others: Callable | None = None) -> Status:
    """一次探测算出完整状态。所有探测函数可注入（测试用假数据驱动）。"""
    get_processes = processes or probe.dsh_processes
    get_port = port_open or probe.port_open
    get_tailscale = tailscale or probe.tailscale_ip
    get_lan = lan or probe.lan_ips
    get_others = others or probe.other_dsh_processes
    port = int(cfg.port)

    pids, pids_err = get_processes(cfg.bin_js)
    listening = get_port(port)
    phone, targets, phone_notes = probe_phone(cfg, portproxy=portproxy, firewall=firewall)

    primary: list[str] = []
    # 判定规则（顺序即优先级）：
    #   关键探测（进程列表 / 端口）任一为 None        -> UNKNOWN（查不到不等于没在跑）
    #   端口通 + 本机 PID 命中                        -> RUNNING
    #   端口通但本机 PID 明确为空                     -> DEGRADED（端口被别的程序占了）
    #   端口不通但进程在                               -> STARTING（进程起来了，端口还没监听）
    #   端口不通 + 没有进程                           -> STOPPED
    if pids is None or listening is None:
        phase = Phase.UNKNOWN
    elif listening and pids:
        phase = Phase.RUNNING
    elif listening:
        phase = Phase.DEGRADED
    elif pids:
        phase = Phase.STARTING
    else:
        phase = Phase.STOPPED

    foreign: list[tuple[int, str]] | None = None
    if phase is Phase.UNKNOWN:
        if pids is None:
            primary.append(f"未知：进程列表查不到（{pids_err}）")
        if listening is None:
            primary.append(f"未知：端口 {port} 探测没有得到结论")
    elif phase is Phase.DEGRADED:
        primary.append(f"端口 {port} 已被监听，但没有找到本机 bin.js 的 node 进程："
                       "可能是别的程序占用了端口。")
        foreign, foreign_err = get_others(cfg.bin_js)
        if foreign:
            shown = "；".join(f"PID {pid} → {probe.display_path(path)}" for pid, path in foreign[:3])
            primary.append(f"占用端口的可能是另一处安装的 DSH：{shown}")
        elif foreign is None and foreign_err:
            primary.append(f"未知：另一处安装的进程列表（{foreign_err}）")
    elif phase is Phase.STARTING:
        shown = "、".join(str(pid) for pid in pids or [])
        primary.append(f"进程在（PID {shown}），但端口 {port} 还没监听：可能正在启动。")

    tail_ips: list[str] = []
    ts_ip, ts_err = get_tailscale(cfg.tailscale)
    if ts_ip is None and ts_err:
        tail_ips.append(f"未知：Tailscale 地址（{ts_err}）")
    lan_list, lan_err = get_lan()
    if lan_list is None:
        tail_ips.append(f"未知：局域网地址（{lan_err}）")

    return Status(
        phase=phase,
        pids=pids,
        port_open=listening,
        phone_open=phone,
        phone_targets=targets,
        ts_ip=ts_ip,
        lan_ips=lan_list,
        notes=primary + phone_notes + tail_ips,
        others=foreign,
    )
