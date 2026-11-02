"""手机访问策略层：serve 优先、失败自动回退端口转发，产出一份可直接渲染的 PhonePlan。

为什么不写在 dsh_gui.py：界面入口由 UI 组并行改，策略必须有独立、可单测的落点。
plan() 本身是纯策略（给定事实就给定结论），要问机器状态的是 detect_plan()。

两条路的代价差得很远，这是「serve 优先」的全部理由：
  · serve —— tailscaled 自己监听 80/443 并代理到 127.0.0.1:PORT。不需要管理员权限、
    不需要 netsh 端口转发、不需要动防火墙、地址是 MagicDNS 域名（手机不用签证书）。
  · 端口转发 —— 要 UAC、要按网卡 IP 逐条 netsh、要防火墙放行，而且校园网常带设备隔离。
"""
from __future__ import annotations

import shutil
from dataclasses import dataclass

from . import addresses, tailscale

MODE_SERVE = "serve"
MODE_PROXY = "portproxy"
MODE_NONE = "none"

NEXT_READY = "已就绪：手机连上 tailnet 后直接扫下面的二维码即可打开。"
NEXT_HTTPS = ("想要 https：去 Tailscale 管理台 DNS 页打开 HTTPS Certificates，"
              "然后重试；不打开也能用 http://<域名>/（tailnet 内本来就是加密的 WireGuard）。")
NEXT_LOGIN = "让手机和电脑登录同一个 tailnet：电脑上 tailscale up 登录，手机装 Tailscale 并登录同一账号。"
NEXT_LAN = "手机与电脑连同一个 Wi-Fi 时还能走局域网地址；校园网/公司网常开设备隔离，直连可能不通。"
NEXT_SERVE_FAIL = "serve 起不来，已回退端口转发：手机需装 Tailscale 并登录同一账号（或与电脑同一局域网）。"
# 回退时按失败原因挑一句最该被读到的话，而不是一律说「serve 起不来」。
_FALLBACK_NEXT = {
    tailscale.NOT_LOGGED_IN: NEXT_LOGIN,
    tailscale.CLI_MISSING: "这台电脑没装 Tailscale：现在只能走局域网地址，" + NEXT_LAN,
    tailscale.DAEMON_DOWN: "Tailscale 没在跑：先启动它（或重启 Tailscale 服务），再回来重试。",
    tailscale.NO_MAGICDNS: "tailnet 没开 MagicDNS：去管理台 DNS 页打开 MagicDNS 才能用 <节点>.ts.net。",
}


@dataclass(frozen=True)
class PhonePlan:
    """一次「手机怎么打开」的完整结论。界面只渲染，不再自己判断。"""

    port: int = addresses.DEFAULT_PORT
    mode: str = MODE_NONE
    candidates: tuple[addresses.Candidate, ...] = ()
    failures: tuple[tailscale.Reason, ...] = ()
    next_step: str = ""
    serve_host: str | None = None
    scheme: str = addresses.SCHEME_HTTP
    trusted_hosts: tuple[str, ...] = ()

    @property
    def primary(self) -> addresses.Candidate | None:
        return self.candidates[0] if self.candidates else None

    @property
    def url(self) -> str | None:
        first = self.primary
        return first.url if first else None

    @property
    def qr_url(self) -> str | None:
        """二维码只允许编码这个：手机可达且已排序的第一条；没有就是 None（宁可不画）。"""
        first = self.primary
        return first.url if first and first.phone_reachable else None

    @property
    def degraded(self) -> bool:
        return bool(self.failures)


def _from_facts(facts: tailscale.Facts | None, items) -> list[addresses.Address]:
    """调用方没给网卡地址时，至少把 Tailscale 自己的 IP 变成候选。"""
    if items:
        return list(items)
    if facts is None:
        return []
    return [addresses.Address(ip, addresses.TAILSCALE_LABEL, "tailscale")
            for ip in facts.tailscale_ips]


def plan(port: int = addresses.DEFAULT_PORT, log=None, *, token: str | None = None,
         detection: tailscale.Detection | None = None,
         addresses_list=None, spawn=None,
         serve_blocked: tailscale.Reason | None = None) -> PhonePlan:
    """给出手机访问计划。detection 传进来就是纯计算（测试用），不传就去问机器。"""
    if detection is None:
        detection = tailscale.detect(spawn=spawn)
    facts = detection.facts
    failures: list[tailscale.Reason] = []

    http_block = tailscale.http_reason(facts) if detection.error is None else detection.error
    https_block = tailscale.https_reason(facts) if detection.error is None else detection.error

    serve_host: str | None = None
    scheme = addresses.SCHEME_HTTP
    mode = MODE_NONE
    next_step = ""

    if http_block is None and facts is not None and serve_blocked is None:
        serve_host = facts.dns_name
        mode = MODE_SERVE
        if https_block is None:
            scheme = addresses.SCHEME_HTTPS
            next_step = NEXT_READY
        else:
            failures.append(https_block)
            next_step = NEXT_HTTPS
    else:
        if http_block is not None:
            failures.append(http_block)
        if serve_blocked is not None:
            failures.append(serve_blocked)   # serve 装不上：域名不可信，必须回退
        mode = MODE_PROXY

    pool = _from_facts(facts, addresses_list)
    candidates = addresses.mobile_candidates(
        pool, port=port, token=token, serve_host=serve_host, serve_scheme=scheme)
    if mode == MODE_PROXY and not candidates:
        mode = MODE_NONE
        next_step = next_step or NEXT_LOGIN
    elif mode == MODE_PROXY:
        blocking = failures[0].code if failures else ""
        next_step = next_step or _FALLBACK_NEXT.get(blocking, NEXT_SERVE_FAIL)
    elif mode == MODE_NONE and not next_step:
        next_step = NEXT_LOGIN

    trusted = tuple(addresses.host_port(cand.host, cand.port) for cand in candidates)
    plan_obj = PhonePlan(
        port=port, mode=mode, candidates=tuple(candidates),
        failures=tuple(failures), next_step=next_step, serve_host=serve_host,
        scheme=scheme, trusted_hosts=trusted,
    )
    if log:
        log(f"手机访问计划：mode={plan_obj.mode} scheme={plan_obj.scheme} "
            f"serve={serve_host or '-'} 候选={len(plan_obj.candidates)} "
            f"失败={[r.code for r in plan_obj.failures]}")
    return plan_obj


def detect_plan(port: int = addresses.DEFAULT_PORT, log=None, *, token: str | None = None,
                addresses_list=None, spawn=None, which=shutil.which,
                probe=None) -> PhonePlan:
    """detect_plan = 先按当前事实探测一遍，再照计划把 serve 打开（幂等）。

    只碰 serve 层：绝不重启、不改动正在跑的 DSH 进程与它的配置。
    """
    detection = tailscale.detect(spawn=spawn, which=which, probe=probe)
    current = plan(port, log, token=token, detection=detection,
                   addresses_list=addresses_list, spawn=spawn)
    if current.mode != MODE_SERVE:
        return current
    scheme = current.scheme
    live = detection.serve.route_for(addresses.SCHEME_PORTS[scheme])
    if live and live.host and live.proxy:
        return current
    failure = tailscale.enable_serve(port, scheme=scheme, spawn=spawn, cli=detection.cli)
    if failure is not None:
        refreshed = tailscale.detect(spawn=spawn, which=which, probe=probe)
        return plan(port, log, token=token, detection=refreshed,
                    addresses_list=addresses_list, spawn=spawn, serve_blocked=failure)
    return current


def phone_checklist(plan_obj: PhonePlan) -> list[str]:
    """手机要能打开，必须同时成立的条件（给用户看的判定清单）。"""
    rows = [
        "电脑不休眠、DSH 网页进程在跑（端口 %d 有监听）。" % plan_obj.port,
    ]
    if plan_obj.mode == MODE_SERVE and plan_obj.serve_host:
        rows.append("手机装了 Tailscale 并登录了同一个 tailnet（serve 只在 tailnet 内可见）。")
        rows.append("手机上能解析 %s（MagicDNS 打开时自动生效）。" % plan_obj.serve_host)
        rows.append("serve 规则还在：tailscale serve status 里能看到指向 127.0.0.1:%d 的代理。"
                    % plan_obj.port)
    elif plan_obj.mode == MODE_PROXY:
        rows.append("手机装了 Tailscale 并登录同一账号，或与电脑在同一个局域网。")
        rows.append("防火墙放行了入站 TCP %d（WLAN/以太网常被判定为「公用」，规则要覆盖 Public）。"
                    % plan_obj.port)
        rows.append("端口转发存在：netsh interface portproxy show v4tov4 里能看到对应 IP。")
    else:
        rows.append("没有任何手机可达地址：先按「下一步」修好 Tailscale 或局域网。")
    rows.append("用二维码里的地址打开后，token 会自动换 Cookie，之后可以直接刷新。")
    return rows
