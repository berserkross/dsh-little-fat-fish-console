"""Tailscale 事实层：把 tailscale CLI 的输出解析成结构化事实，不做任何决策。

设计约束（都是可测性要求，不是洁癖）：
- import 时不执行任何命令 —— 网络/daemon 状态只在你主动调 detect() 时才问；
- 解析函数只吃字符串，测试直接喂真机抄下来的 JSON，不需要装 Tailscale；
- IO 函数接受 spawn 注入（默认 dshconsole.psrun.run_native），测试不碰真 CLI。

命名理由：本模块只管「Tailscale 是什么状态」（CLI 在不在、daemon 起没起、DNSName、
证书、serve 配置），「serve 优先还是回退端口转发」这类策略在 phone.py。事实与策略
分开，任何一层的测试都不用为另一层造桩。
"""
from __future__ import annotations

import json
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from . import psrun

TS_EXE = "tailscale.exe"
# 常规安装位置：PATH 里没有时兜底，省掉一次失败的 subprocess 启动。
KNOWN_PATHS = (
    r"C:\Program Files\Tailscale\tailscale.exe",
    r"C:\Program Files (x86)\Tailscale\tailscale.exe",
)
TIMEOUT_STATUS = 10
TIMEOUT_SERVE = 20

RUNNING = "Running"
DAEMON_DOWN_STATES = frozenset({"NoState", "Stopped", "Starting"})
LOGIN_REQUIRED_STATES = frozenset({"NeedsLogin", "NeedsMachineAuth"})

# 失败原因码：调用方按码判断，按 text 展示。码是人话与逻辑的唯一交点。
CLI_MISSING = "cli_missing"
DAEMON_DOWN = "daemon_down"
NOT_LOGGED_IN = "not_logged_in"
NO_MAGICDNS = "no_magicdns"
HTTPS_DISABLED = "https_disabled"
SERVE_FAILED = "serve_failed"


@dataclass(frozen=True)
class Reason:
    """一个可展示的失败原因：code 给逻辑，text 给用户。"""

    code: str
    text: str


@dataclass(frozen=True)
class Facts:
    """tailscale status --json 里我们真正会用到的那几个字段。"""

    backend_state: str = ""
    dns_name: str = ""                      # 已剥掉结尾的点：valkiriya.tail679d87.ts.net
    tailscale_ips: tuple[str, ...] = ()
    magic_dns_enabled: bool = False
    magic_dns_suffix: str = ""
    cert_domains: tuple[str, ...] = ()
    version: str = ""

    @property
    def running(self) -> bool:
        return self.backend_state == RUNNING

    def ipv4(self) -> str | None:
        for ip in self.tailscale_ips:
            if ":" not in ip:
                return ip
        return self.tailscale_ips[0] if self.tailscale_ips else None


@dataclass(frozen=True)
class ServeRoute:
    """一条 serve 规则：host:port 上的路径代理到哪个本地目标。"""

    host: str
    port: int
    https: bool
    proxy: str = ""

    def url(self) -> str:
        scheme = "https" if self.https else "http"
        default = 443 if self.https else 80
        return f"{scheme}://{self.host}" if self.port == default else f"{scheme}://{self.host}:{self.port}"


@dataclass(frozen=True)
class ServeConfig:
    routes: tuple[ServeRoute, ...] = ()

    @property
    def active(self) -> bool:
        return bool(self.routes)

    def route_for(self, port: int) -> ServeRoute | None:
        for route in self.routes:
            if route.port == port:
                return route
        return None


def _load_json(raw) -> object | None:
    """从可能夹着日志噪音的文本里抠出 JSON；抠不出来就是 None，绝不抛。"""
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        return json.loads(text[start:end + 1])
    except ValueError:
        return None


def parse_status(raw) -> Facts | None:
    """解析 tailscale status --json；不是 JSON 就返回 None（而不是假装已登录）。"""
    data = _load_json(raw)
    if not isinstance(data, dict):
        return None
    if "BackendState" not in data and "Self" not in data:
        return None      # {} 之类不是 state 输出，别假装「已连上」
    selfinfo = data.get("Self") if isinstance(data.get("Self"), dict) else {}
    tailnet = data.get("CurrentTailnet") if isinstance(data.get("CurrentTailnet"), dict) else {}
    ips = tuple(str(ip) for ip in (selfinfo.get("TailscaleIPs") or []) if ip)
    certs = tuple(str(d).rstrip(".") for d in (data.get("CertDomains") or []) if d)
    return Facts(
        backend_state=str(data.get("BackendState") or ""),
        dns_name=str(selfinfo.get("DNSName") or "").rstrip("."),
        tailscale_ips=ips,
        magic_dns_enabled=bool(tailnet.get("MagicDNSEnabled")),
        magic_dns_suffix=str(data.get("MagicDNSSuffix") or "").rstrip("."),
        cert_domains=certs,
        version=str(data.get("Version") or ""),
    )


def parse_serve_config(raw) -> ServeConfig:
    """解析 tailscale serve status --json。

    真机形状（1.104.2 实测）：
      {"TCP": {"80": {"HTTP": true}},
       "Web": {"<host>:80": {"Handlers": {"/": {"Proxy": "http://127.0.0.1:3080"}}}}}
    「No serve config」/「{}」都解析成空配置。
    """
    data = _load_json(raw)
    if not isinstance(data, dict):
        return ServeConfig()
    tcp = data.get("TCP") if isinstance(data.get("TCP"), dict) else {}
    web = data.get("Web") if isinstance(data.get("Web"), dict) else {}
    routes: list[ServeRoute] = []
    for key, entry in web.items():
        host, _, port_text = str(key).rpartition(":")
        port = int(port_text) if port_text.isdigit() else 0
        flags = tcp.get(str(port)) if isinstance(tcp.get(str(port)), dict) else {}
        proxy = ""
        handlers = entry.get("Handlers") if isinstance(entry, dict) else None
        if isinstance(handlers, dict) and isinstance(handlers.get("/"), dict):
            proxy = str(handlers["/"].get("Proxy") or "")
        routes.append(ServeRoute(host=host, port=port, https=bool(flags.get("HTTPS")), proxy=proxy))
    routes.sort(key=lambda route: (route.port, route.host))
    return ServeConfig(tuple(routes))


def https_reason(facts: Facts | None) -> Reason | None:
    """https 模式可用吗；不可用时给出用户能照着做的原因。"""
    if facts is None:
        return Reason(CLI_MISSING, "没找到 tailscale CLI，无法确认 HTTPS 证书状态")
    if not facts.cert_domains:
        return Reason(
            HTTPS_DISABLED,
            "Tailscale 账户没有开 HTTPS 证书（status 里 CertDomains 为空，"
            "tailscale cert 直接返回 500），所以 serve 只能走 http://<域名>/",
        )
    if facts.dns_name and facts.dns_name not in facts.cert_domains:
        return Reason(
            HTTPS_DISABLED,
            f"当前域名 {facts.dns_name} 不在已签发列表里，需要在 Tailscale 管理台启用 HTTPS 证书后重试",
        )
    return None


def http_reason(facts: Facts | None) -> Reason | None:
    """http 模式（--http=80）可用吗：只要 daemon 在跑且域名可解析就够，不需要证书。"""
    if facts is None:
        return Reason(CLI_MISSING, "没找到 tailscale CLI，手机访问只能靠局域网/端口转发")
    if facts.backend_state in LOGIN_REQUIRED_STATES:
        return Reason(NOT_LOGGED_IN, "Tailscale 已装但没登录（或还在等设备授权），先登录同一账号")
    if not facts.running:
        if facts.backend_state in DAEMON_DOWN_STATES or not facts.backend_state:
            return Reason(DAEMON_DOWN, "Tailscale daemon 没在运行")
        return Reason(DAEMON_DOWN, f"Tailscale 状态是 {facts.backend_state}，serve 需要 Running")
    if not facts.dns_name:
        return Reason(NO_MAGICDNS, "拿不到节点自己的 MagicDNS 域名，serve 无法给出手机可达地址")
    if not facts.magic_dns_enabled:
        return Reason(NO_MAGICDNS, "tailnet 没开 MagicDNS，手机解析不到 <节点>.<tailnet>.ts.net 这个名字")
    return None


def serve_argv(port: int, *, scheme: str = "http", exe: str = TS_EXE) -> list[str]:
    """构造 serve 命令。--yes 必须有：缺了它 CLI 会停在交互提示上把界面挂死（实测）。"""
    listen = 80 if scheme == "http" else 443
    argv = [exe, "serve", "--bg", "--yes"]
    if scheme == "http":
        argv.append(f"--http={listen}")
    argv.append(str(port))
    return argv


def find_cli(which=shutil.which, probe=None) -> str | None:
    """找 tailscale.exe：先 PATH，再常见安装位置。纯查找，不执行。

    probe 只给测试用：在真装了 Tailscale 的机器上模拟「没装」。
    """
    found = which("tailscale")
    if found:
        return found
    probe = probe or (lambda path: Path(path).is_file())
    for candidate in KNOWN_PATHS:
        if probe(candidate):
            return candidate
    return None


@dataclass(frozen=True)
class Detection:
    """一次探测的全貌：CLI、daemon 事实、当前 serve 配置，外加失败原因。"""

    cli: str | None = None
    facts: Facts | None = None
    serve: ServeConfig = field(default_factory=ServeConfig)
    error: Reason | None = None

    @property
    def usable(self) -> bool:
        return self.facts is not None and self.error is None


def _run(argv: list[str], timeout: int, spawn):
    """spawn 是 subprocess.run 的替身，不是 run_native 的替身：始终经 run_native 归一化。"""
    return psrun.run_native(argv, timeout=timeout, spawn=spawn)


def detect(*, spawn=None, which=shutil.which, probe=None) -> Detection:
    """问一次 Tailscale：CLI 在不在、daemon 什么状态、serve 现有配置是什么。"""
    exe = find_cli(which, probe)
    if not exe:
        return Detection(error=Reason(CLI_MISSING, "没找到 tailscale.exe：这台机器没装 Tailscale 客户端"))
    status_result = _run([exe, "status", "--json"], TIMEOUT_STATUS, spawn)
    facts = parse_status(status_result.stdout)
    if facts is None and not status_result.ok:
        facts = parse_status(status_result.text)
    if facts is None:
        return Detection(cli=exe, error=Reason(
            DAEMON_DOWN, f"tailscale status 没返回可解析的 JSON：{status_result.why() or '输出为空'}"))
    serve_result = _run([exe, "serve", "status", "--json"], TIMEOUT_STATUS, spawn)
    return Detection(cli=exe, facts=facts, serve=parse_serve_config(
        serve_result.stdout if serve_result.ok else ""))


def enable_serve(port: int, *, scheme: str = "http", spawn=None, cli: str | None = None) -> Reason | None:
    """把 serve 打开到 port；成功返回 None，失败返回可展示原因。"""
    exe = find_cli() if cli is None else cli
    if not exe:
        return Reason(CLI_MISSING, "没找到 tailscale.exe")
    result = _run(serve_argv(port, scheme=scheme, exe=exe), TIMEOUT_SERVE, spawn)
    if result.ok:
        return None
    return Reason(SERVE_FAILED, f"tailscale serve 失败：{result.why() or '未知原因'}")


def reset_serve(*, spawn=None, cli: str | None = None) -> Reason | None:
    """拆掉全部 serve 规则；成功返回 None。"""
    exe = find_cli() if cli is None else cli
    if not exe:
        return Reason(CLI_MISSING, "没找到 tailscale.exe")
    result = _run([exe, "serve", "reset"], TIMEOUT_SERVE, spawn)
    if result.ok:
        return None
    return Reason(SERVE_FAILED, f"tailscale serve reset 失败：{result.why() or '未知原因'}")
