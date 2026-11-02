"""脱敏诊断包（C3）。

用户点一下「导出诊断包」，得到一个 zip：里面有版本/路径元信息、探测明细、日志
尾部、系统与网络原始输出。整包统一过 textutil.redact_text() —— token、cookie、
API key、sk- 前缀、gho_/ghp_ 前缀全部打码。谁把包发出去都不算泄密。

不做成「先写原文再打码」：内容在进 zip 的那一刻就只有一个打过码的版本，不存在
忘打码的中间文件。
"""

from __future__ import annotations

import json
import platform
import sys
import zipfile
from datetime import datetime
from enum import Enum
from pathlib import Path

from . import config, logtail, probe, psrun, resources, textutil

LOG_LINES = 500
FILES = ("meta.json", "probe.txt", "log-tail.txt", "windows.txt")


def _plain(value):
    """转成能塞进 json 的东西：Path/Enum 变字符串，其余递归处理。"""
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_plain(item) for item in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def _version() -> str:
    try:
        from . import __version__ as version   # noqa: PLC0415 - 可选，缺了不算错
        return str(version)
    except Exception:
        return "unknown"


def meta_dict(cfg, *, status=None, phase: str | None = None,
              pids=None, notes=None, timings=None) -> dict:
    """元信息：版本、时间、解释器、冻结与否、状态，以及 config 里的**路径类**字段。

    不带 config.json 的完整内容：那里可能有用户填的路径之外的东西，诊断用不上。
    """
    return {
        "app": config.APP_NAME,
        "version": _version(),
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "python": sys.version.split()[0],
        "executable": sys.executable,
        "frozen": resources.frozen(),
        "phase": phase or (status.phase.value if status is not None else None),
        "pids": list(pids) if pids is not None else (list(status.pids or []) if status else None),
        "notes": list(notes) if notes is not None else (list(status.notes) if status else []),
        "port": int(cfg.port),
        "config_path": config.config_path(),
        "harness": cfg.harness,
        "node": cfg.node,
        "bin_js": cfg.bin_js,
        "dsh_home": cfg.dsh_home,
        "tailscale": cfg.tailscale,
        "chrome": cfg.chrome,
        "log_files": [Path(path) for path in cfg.log_files],
        "timings_ms": timings if timings is not None else (
            dict(status.timings) if status is not None else {}
        ),
    }


def probe_report(raw: probe.RawProbe | None, status=None) -> str:
    """探测明细：每项的结论 + 耗时，查不到的写清为什么。"""
    lines = ["== 探测明细 =="]
    if raw is None:
        if status is None:
            lines.append("（没有本次探测的数据）")
            return "\n".join(lines)
        lines.append(f"阶段：{status.phase.label}")
        lines.append(f"PID：{status.pids}")
        lines.append(f"端口 {status.port_open}／手机 {status.phone_open}")
        lines.append(f"Tailscale：{status.ts_ip}／局域网：{status.lan_ips}")
        for note in status.notes:
            lines.append(f"说明：{note}")
        return "\n".join(lines)

    lines.append(f"总耗时：{raw.total_ms} ms")
    steps = raw.timings or {}
    for name, value in steps.items():
        lines.append(f"  分项 {name}：{value} ms")
    lines.append(f"node 进程：{len(raw.processes) if raw.processes is not None else '未知'}"
                 f"（{raw.process_error or 'ok'}）")
    lines.append(f"端口转发：{'ok' if raw.portproxy_text is not None else raw.portproxy_error}")
    lines.append(f"防火墙规则：{raw.firewall}")
    lines.append(f"网卡地址：{raw.addresses}")
    lines.append(f"Tailscale 地址：{raw.ts_ip}（{raw.ts_error or 'ok'}）")
    for line in (raw.portproxy_text or "").splitlines():
        lines.append(f"  portproxy| {line}")
    for line in (raw.firewall_text or "").splitlines():
        lines.append(f"  firewall| {line}")
    return "\n".join(lines)


def log_tail(cfg, *, count: int = LOG_LINES) -> str:
    """日志尾部：stdout 与 stderr 各取最后 count 行。"""
    chunks = []
    for path in cfg.log_files:
        chunks.append(f"===== {path} =====")
        chunks.append(logtail.read_tail(path, count))
    return "\n".join(chunks)


def windows_report(port: int, *, ps_runner=None, proxy_runner=None,
                   firewall_runner=None) -> str:
    """OS / PowerShell / 端口与防火墙的原始输出。"""
    run = ps_runner or psrun.run_ps_cmd
    lines = ["== 系统 =="]
    lines.append(f"platform：{platform.platform()}")
    lines.append(f"machine：{platform.machine()}／processor：{platform.processor()}")
    if hasattr(sys, "getwindowsversion"):
        version = sys.getwindowsversion()
        lines.append(f"windows：{version.major}.{version.minor} build {version.build}")
    version_result = run("$PSVersionTable.PSVersion.ToString()", timeout=20)
    lines.append(f"PowerShell：{version_result.stdout.strip() or version_result.why()}")

    lines.append("")
    lines.append("== 端口转发（netsh interface portproxy show all）==")
    proxy_text, proxy_err = probe.portproxy_text(proxy_runner)
    lines.append(proxy_text.strip() if proxy_text is not None else f"（查不到：{proxy_err}）")

    lines.append("")
    lines.append(f"== 防火墙（{probe.FIREWALL_RULE.format(port=port)}）==")
    allowed, firewall_err, raw_text = probe.netsh_firewall_state(port, firewall_runner)
    lines.append(f"判定：{allowed}（{firewall_err or 'ok'}）")
    lines.append(raw_text.strip())
    return "\n".join(lines)


def build(dest: Path | str, *, meta: dict, probe_text: str,
          log_text: str, windows_text: str) -> Path:
    """写 zip。每个条目在写入前就过 redact_text，写完不落任何中间文件。"""
    dest = Path(dest)
    if dest.parent and not dest.parent.exists():
        dest.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "meta.json": json.dumps(_plain(meta), ensure_ascii=False, indent=2),
        "probe.txt": probe_text,
        "log-tail.txt": log_text,
        "windows.txt": windows_text,
    }
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as archive:
        for name in FILES:
            archive.writestr(name, textutil.redact_text(payload.get(name, "")))
    return dest


def export(dest: Path | str, *, cfg, status=None, raw: probe.RawProbe | None = None) -> Path:
    """收集 + 打包。界面在后台线程里调它（里面要 spawn PowerShell）。"""
    return build(
        dest,
        meta=meta_dict(cfg, status=status),
        probe_text=probe_report(raw, status),
        log_text=log_tail(cfg),
        windows_text=windows_report(int(cfg.port)),
    )
