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
