"""访问地址候选（C4）：本机 / Tailscale / 每个局域网 IP，带来源标注。

以前是弹个输入框让人手抄 IP。现在给下拉：每项写清来源（本机 / Tailscale /
以太网 / WLAN），端口可编辑（默认 3080，1-65535 校验）。IPv6 用方括号包起来。

探测拿不到 IP 时给「未知（原因）」而不是空列表 —— 空列表让人以为是软件坏了。
"""

from __future__ import annotations

from dataclasses import dataclass

LOCAL_HOST = "127.0.0.1"
LOCAL_LABEL = "本机"
FALLBACK_LABEL = "局域网"
TAILSCALE_LABEL = "Tailscale"
DEFAULT_PORT = 3080
KIND_LABELS = {"Tailscale": TAILSCALE_LABEL}


@dataclass(frozen=True)
class Address:
    host: str
    label: str
    kind: str                      # local / tailscale / lan

    @property
    def bracketed(self) -> str:
        if ":" in self.host and not self.host.startswith("["):
            return f"[{self.host}]"      # IPv6 要方括号，否则端口分不清
        return self.host

    def url(self, port: int = DEFAULT_PORT) -> str:
        return f"http://{self.bracketed}:{port}/"

    def display(self, port: int = DEFAULT_PORT) -> str:
        return f"{self.url(port)}    （{self.label}）"


def _lan_pairs(lan_ips, lan_sources):
    if lan_sources:
        for ip, source in lan_sources:
            if ip:
                yield ip, source or FALLBACK_LABEL
        return
    for ip in lan_ips or []:
        if ip:
            yield ip, FALLBACK_LABEL


def build(ts_ip: str | None = None, lan_ips=None, lan_sources=None,
          *, port: int = DEFAULT_PORT) -> list[Address]:
    """本机永远在第一位；Tailscale、局域网各一条，去重。"""
    found = [Address(LOCAL_HOST, LOCAL_LABEL, "local")]
    seen = {LOCAL_HOST}
    if ts_ip and ts_ip not in seen:
        found.append(Address(ts_ip, TAILSCALE_LABEL, "tailscale"))
        seen.add(ts_ip)
    for ip, source in _lan_pairs(lan_ips, lan_sources):
        if ip in seen:
            continue
        found.append(Address(ip, KIND_LABELS.get(source, source), "lan"))
        seen.add(ip)
    return found


def unknown(reason: str | None) -> str:
    return f"未知（{reason or '原因不明'}）"


def menu(ts_ip: str | None, lan_ips, lan_sources=None, *, port: int = DEFAULT_PORT,
         ts_error: str | None = None, lan_error: str | None = None) -> list[tuple[str, Address | None]]:
    """下拉框条目：(显示文本, 地址)。地址为 None 的那行是「未知（原因）」。"""
    rows: list[tuple[str, Address | None]] = [
        (addr.display(port), addr) for addr in build(ts_ip, lan_ips, lan_sources, port=port)
    ]
    if not ts_ip:
        rows.append((f"Tailscale：{unknown(ts_error)}", None))
    if not lan_ips:
        rows.append((f"局域网：{unknown(lan_error)}", None))
    return rows


def validate_port(text) -> int:
    """端口校验：只收 1-65535 的整数，报错写人话。"""
    raw = str(text).strip()
    if not raw:
        raise ValueError("端口不能为空")
    if not raw.isdigit():
        raise ValueError(f"端口要填数字：{raw}")
    port = int(raw)
    if not 1 <= port <= 65535:
        raise ValueError(f"端口要在 1-65535 之间：{port}")
    return port


# ---------------- 手机可达候选（phone-v2） ----------------
# 根因：二维码曾直接编码 build()[0]，而 build() 永远把 127.0.0.1 放第一位 ——
# 手机扫到的是它自己的回环地址，必然打不开。这里把「手机能不能用」做成显式分层，
# 并把回环整条剔出手机候选：serve 域名 > Tailscale 直连 > 局域网 > 回环。

SCHEME_HTTP = "http"
SCHEME_HTTPS = "https"
SCHEME_PORTS = {SCHEME_HTTP: 80, SCHEME_HTTPS: 443}

TIER_SERVE = "serve"
TIER_TAILSCALE = "tailscale"
TIER_LAN = "lan"
TIER_LOOPBACK = "loopback"
TIER_ORDER = {TIER_SERVE: 0, TIER_TAILSCALE: 1, TIER_LAN: 2, TIER_LOOPBACK: 3}
TIER_LABELS = {
    TIER_SERVE: "MagicDNS 域名（tailscale serve）",
    TIER_TAILSCALE: "Tailscale 直连",
    TIER_LAN: "局域网",
    TIER_LOOPBACK: "本机",
}
# 0.0.0.0 / :: 是通配地址不是回环，但同样不该出现在手机上，一并归到这一层。
UNREACHABLE_HOSTS = frozenset({"localhost", "::1", "0.0.0.0", "::"})


def is_loopback(host) -> bool:
    """主机名是否只在电脑自己身上有意义（回环 / 通配 / 空）。"""
    text = str(host or "").strip().strip("[]").lower()
    if not text:
        return True
    if text in UNREACHABLE_HOSTS:
        return True
    return text.startswith("127.")


def url_for(host, *, scheme: str = SCHEME_HTTP, port: int | None = None,
            token: str | None = None, path: str = "/") -> str:
    """拼一个可点击地址：默认端口不写端口，IPv6 加方括号，token 用 ?token= 附上。"""
    scheme = scheme if scheme in SCHEME_PORTS else SCHEME_HTTP
    port = SCHEME_PORTS[scheme] if port is None else int(port)
    name = str(host or "").strip()
    if ":" in name and not name.startswith("["):
        name = f"[{name}]"
    netloc = name if port == SCHEME_PORTS[scheme] else f"{name}:{port}"
    url = f"{scheme}://{netloc}{path}"
    if token:
        url = f"{url}{'&' if '?' in url else '?'}token={token}"
    return url


def host_port(host, port: int) -> str:
    """拼 trusted-host 用的 host:port；IPv6 必须带方括号，否则 Host 头对不上。"""
    name = str(host or "").strip()
    if ":" in name and not name.startswith("["):
        name = f"[{name}]"
    return f"{name}:{int(port)}"


@dataclass(frozen=True)
class Candidate:
    """一个「手机可以扫」的候选地址，附带层级与可用性说明。"""

    host: str
    tier: str
    label: str
    url: str
    port: int = DEFAULT_PORT
    usable: bool = True
    reason: str = ""               # usable=False 时的人话原因

    @property
    def phone_reachable(self) -> bool:
        """这个地址手机打得开吗。回环地址恒为否——哪怕 usable=True。"""
        return self.usable and self.tier != TIER_LOOPBACK

    def display(self) -> str:
        if not self.usable:
            return f"{self.label}：暂不可用（{self.reason}）"
        return f"{self.url}    （{self.label}）"


def _host_of(item) -> str:
    if isinstance(item, Address):
        return item.host
    return str(item or "")


def _label_of(item, tier: str) -> str:
    if isinstance(item, Address) and item.label:
        return item.label
    return TIER_LABELS.get(tier, tier)


def tier_for(item) -> str:
    """把一条已有地址归到层级：回环优先判定，其余信 kind。"""
    host = _host_of(item)
    if is_loopback(host):
        return TIER_LOOPBACK
    kind = getattr(item, "kind", "") if isinstance(item, Address) else ""
    return TIER_TAILSCALE if kind == "tailscale" else TIER_LAN


def mobile_candidates(items, *, port: int = DEFAULT_PORT, token: str | None = None,
                      serve_host: str | None = None,
                      serve_scheme: str = SCHEME_HTTP,
                      serve_port: int | None = None,
                      include_loopback: bool = False) -> list[Candidate]:
    """手机可达候选，已按层级排好序。回环默认整条剔除（include_loopback 才留）。

    serve_host 非空表示 tailscale serve 已经通了：它排第一，且用 serve 自己的
    协议与端口（http 未给端口就是 80，https 就是 443）。
    """
    found: list[Candidate] = []
    if serve_host:
        scheme = serve_scheme if serve_scheme in SCHEME_PORTS else SCHEME_HTTP
        real_port = SCHEME_PORTS[scheme] if serve_port is None else int(serve_port)
        found.append(Candidate(
            host=str(serve_host).strip(), tier=TIER_SERVE,
            label=TIER_LABELS[TIER_SERVE], port=real_port,
            url=url_for(serve_host, scheme=scheme, port=real_port, token=token),
        ))
    for item in items or []:
        host = _host_of(item)
        if not host:
            continue
        tier = tier_for(item)
        found.append(Candidate(host, tier, _label_of(item, tier),
                               url_for(host, port=port, token=token), port=port))
    unique: dict[str, Candidate] = {}
    for cand in found:
        unique.setdefault(cand.url, cand)      # 同 url 先来的赢
    rows = [c for c in unique.values() if include_loopback or c.tier != TIER_LOOPBACK]
    rows.sort(key=lambda c: TIER_ORDER.get(c.tier, 99))
    return rows


def primary_mobile(items, **kwargs) -> Candidate | None:
    """排序后的第一条；没有任何手机可达地址时返回 None（调用方去解释原因）。"""
    rows = mobile_candidates(items, **kwargs)
    return rows[0] if rows else None
