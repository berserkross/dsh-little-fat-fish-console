"""状态探测：每个函数返回「值 / 未知（None + 原因）」，绝不拿 False 冒充未知。

约定：返回 tuple 的函数，第二项是「查不到」的人话原因（可直接进日志框）；第一项
是 None 才代表未知。空的 list / False 都是「查到了，结果本来就是这样」。
所有探测都走 psrun 的结构化结果，看到 stderr 里的数字就当成 PID 这种事不会再发生。
"""
from __future__ import annotations

import ipaddress
import json
import re
import socket
from pathlib import Path
from typing import Callable

from .psrun import PsResult, run_ps_cmd

Runner = Callable[..., PsResult]
LOCAL_HOSTS = ("127.0.0.1", "localhost")
# 只认 @deepseek-ai/dsh 自己的 bin.js：别的项目里同样叫 bin.js 的进程不算 DSH。
DSH_BIN_JS_TAIL = "\\@deepseek-ai\\dsh\\lib\\bin.js"


def _failure(what: str, result: PsResult) -> str:
    return f"{what}：{result.why() or 'PowerShell 执行失败'}"


def _ipv4(value: str) -> str | None:
    try:
        return str(ipaddress.IPv4Address((value or "").strip()))
    except ValueError:
        return None


# ---------------- 端口是否在监听 ----------------
def port_open(port: int, host: str = "127.0.0.1", timeout: float = 0.4) -> bool:
    """本机端口是否接受连接。连不上就是没开，这里不存在「未知」。"""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


# ---------------- 端口转发（netsh portproxy） ----------------
def parse_portproxy_table(text: str) -> list[tuple[str, int, str, int]]:
    """解析 `netsh interface portproxy show v4tov4` 的表格。

    返回 (listen_address, listen_port, connect_address, connect_port)。
    表头两行、分隔线、说明行都没有 4 个 IPv4 列，天然被跳过；IPv6 行也因为
    地址不是 IPv4 被丢掉 —— 这个功能只用 v4tov4。
    """
    rows: list[tuple[str, int, str, int]] = []
    for line in (text or "").splitlines():
        fields = line.split()
        if len(fields) != 4:
            continue
        listen_ip, connect_ip = _ipv4(fields[0]), _ipv4(fields[2])
        if not listen_ip or not connect_ip:
            continue
        if not (fields[1].isdigit() and fields[3].isdigit()):
            continue
        rows.append((listen_ip, int(fields[1]), connect_ip, int(fields[3])))
    return rows


def portproxy_targets(port: int, runner: Runner | None = None) -> tuple[list[tuple[str, int]] | None, str | None]:
    """监听在 port 上的转发规则转发到的 (地址, 端口)。

    空 list = 查到了，这个端口没有转发；None = 查不到。
    """
    run = runner or run_ps_cmd
    result = run("netsh interface portproxy show v4tov4", timeout=15)
    if not result.ok:
        return None, _failure("端口转发查询失败", result)
    rows = parse_portproxy_table(result.text)
    return [(connect_ip, connect_port) for _listen_ip, listen_port, connect_ip, connect_port
            in rows if listen_port == port], None


# ---------------- 防火墙规则 ----------------
FIREWALL_RULE = "DSH Web {port} access"


def firewall_command(port: int) -> str:
    quoted = "'" + FIREWALL_RULE.format(port=port).replace("'", "''") + "'"
    return (
        "try {\n"
        f"  $r = @(Get-NetFirewallRule -DisplayName {quoted} -ErrorAction Stop | "
        f"Where-Object {{ $_.DisplayName -eq {quoted} }})\n"
        "  if ($r.Count -gt 0) { 'FOUND' } else { 'MISSING' }\n"
        "} catch { 'ERROR ' + $_.Exception.Message }\n"
    )


def parse_firewall_result(text: str) -> bool | None:
    """FOUND -> True，MISSING -> False，报错或没有结论 -> None。"""
    for line in (text or "").splitlines():
        token = line.strip()
        if token == "FOUND":
            return True
        if token == "MISSING":
            return False
        if token.upper().startswith("ERROR"):
            return None
    return None


def firewall_rule(port: int, runner: Runner | None = None) -> tuple[bool | None, str | None]:
    run = runner or run_ps_cmd
    result = run(firewall_command(port), timeout=30)
    if not result.ok:
        return None, _failure("防火墙规则查询失败", result)
    found = parse_firewall_result(result.text)
    if found is not None:
        return found, None
    detail = next((ln.strip() for ln in result.text.splitlines()
                   if ln.strip().upper().startswith("ERROR")), "")
    return None, detail or "防火墙规则查询没有返回 FOUND / MISSING"


# ---------------- Tailscale / 局域网地址 ----------------
def tailscale_ip(exe: Path | str | None, runner: Runner | None = None) -> tuple[str | None, str | None]:
    """tailscale 的 IPv4；没装 / 没登录 / 命令失败都返回 None + 原因。"""
    if not exe:
        return None, "未检测到 tailscale.exe（可在 config.json 里指定路径）"
    run = runner or run_ps_cmd
    command = "& '" + str(exe).replace("'", "''") + "' ip -4"
    result = run(command, timeout=15)
    if not result.ok:
        return None, _failure("tailscale ip 查询失败", result)
    for token in (result.stdout or "").split():
        found = _ipv4(token)
        if found and not found.startswith("127."):
            return found, None
    return None, "tailscale 没有返回可用的 IPv4 地址"


LAN_QUERY = (
    "Get-NetIPAddress -AddressFamily IPv4 | "
    "Where-Object { $_.IPAddress -match '^(10|192\\.168|172\\.(1[6-9]|2\\d|3[01]))\\.' "
    "-and $_.IPAddress -notmatch '^100\\.' } | "
    "Select-Object -ExpandProperty IPAddress -Unique"
)


def parse_lan_ips(text: str) -> list[str]:
    found: list[str] = []
    for token in (text or "").split():
        ip = _ipv4(token)
        if ip and ip not in found and not ip.startswith(("127.", "169.254.")):
            found.append(ip)
    return found


def lan_ips(runner: Runner | None = None) -> tuple[list[str] | None, str | None]:
    run = runner or run_ps_cmd
    result = run(LAN_QUERY, timeout=20)
    if not result.ok:
        return None, _failure("局域网地址查询失败", result)
    return parse_lan_ips(result.stdout), None


# ---------------- node 进程 ----------------
PROCESS_QUERY = (
    "$ErrorActionPreference = 'Stop'\n"
    "try {\n"
    "  $p = @(Get-CimInstance Win32_Process -Filter \"Name='node.exe'\" -ErrorAction Stop | "
    "Select-Object ProcessId, CommandLine)\n"
    "  ConvertTo-Json -InputObject $p -Compress -Depth 3\n"
    "} catch {\n"
    "  [Console]::Error.WriteLine($_.Exception.Message)\n"
    "  exit 3\n"
    "}\n"
)


def normalize_path(value: str) -> str:
    """大小写不敏感、斜杠统一成反斜杠、吃掉 . 与 .. 的路径规范化。

    同一个 bin.js 在命令行里可能是 C:/a/../b/bin.js、\\\\srv\\b\\bin.js 或带引号的形式，
    直接字符串比较会漏；比较前双方都过一遍这里。
    """
    return _collapse(value).lower()


def display_path(value: str) -> str:
    """给人看的路径：同 normalize_path 的折叠，但保留原有大小写。"""
    return _collapse(value)


def _collapse(value: str) -> str:
    text = (value or "").strip().strip('"').strip("'").replace("/", "\\")
    parts: list[str] = []
    for part in text.split("\\"):
        if part in ("", "."):
            continue
        if part == "..":
            if parts:
                parts.pop()
            continue
        parts.append(part)
    return "\\".join(parts)


def _is_absolute(value: str) -> bool:
    return bool(re.match(r"^[A-Za-z]:[\\\\/]", value) or value.startswith("\\\\"))


def command_line_paths(command_line: str) -> list[str]:
    """从命令行里挑出「绝对路径形式的 bin.js」参数（引号内外的写法都认）。"""
    tokens: list[str] = []
    for index, chunk in enumerate((command_line or "").split('"')):
        if index % 2:
            tokens.append(chunk)
        else:
            tokens.extend(chunk.split())
    paths: list[str] = []
    for token in tokens:
        cleaned = token.strip().strip('"').strip("'")
        if cleaned.lower().endswith("bin.js") and _is_absolute(cleaned):
            paths.append(cleaned)
    return paths


def is_dsh_bin_js(path: str) -> bool:
    return normalize_path(path).endswith(DSH_BIN_JS_TAIL)


def parse_process_list(text: str) -> list[tuple[int, str]] | None:
    """把 ConvertTo-Json 的进程列表解析成 [(pid, commandline)]；解析不了返回 None。"""
    raw = (text or "").strip()
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except ValueError:
        return None
    if isinstance(data, dict):
        data = [data]
    if not isinstance(data, list):
        return None
    processes: list[tuple[int, str]] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        command_line = item.get("CommandLine")
        try:
            pid = int(item.get("ProcessId"))
        except (TypeError, ValueError):
            continue
        if isinstance(command_line, str) and command_line:
            processes.append((pid, command_line))
    return processes


def node_processes(runner: Runner | None = None) -> tuple[list[tuple[int, str]] | None, str | None]:
    run = runner or run_ps_cmd
    result = run(PROCESS_QUERY, timeout=30)
    if not result.ok:
        return None, _failure("node 进程查询失败", result)
    processes = parse_process_list(result.stdout)
    if processes is None:
        return None, "node 进程查询没有返回可解析的进程列表"
    return processes, None


def dsh_processes(bin_js: Path | str | None, runner: Runner | None = None) -> tuple[list[int] | None, str | None]:
    """命令行里带「本机这一个 bin.js 绝对路径」的 node 进程 PID。

    只认配置里的 bin.js：别的项目、别的安装目录里同形状的进程一律不算，
    所以「停止」不会误杀。None = 查不到（不是「没在跑」）。
    """
    if not bin_js:
        return None, "没有探测到 bin.js 路径，无法确认哪个 node 进程才是 DSH"
    processes, err = node_processes(runner)
    if processes is None:
        return None, err
    wanted = normalize_path(str(bin_js))
    pids = sorted({pid for pid, command_line in processes
                   if any(normalize_path(path) == wanted
                          for path in command_line_paths(command_line))})
    return pids, None


def other_dsh_processes(bin_js: Path | str | None,
                        runner: Runner | None = None) -> tuple[list[tuple[int, str]] | None, str | None]:
    """别的安装（npx 缓存等）里的 bin.js 进程：只用来解释「端口被谁占着」，不参与停止。"""
    processes, err = node_processes(runner)
    if processes is None:
        return None, err
    wanted = normalize_path(str(bin_js)) if bin_js else ""
    others: list[tuple[int, str]] = []
    for pid, command_line in processes:
        for path in command_line_paths(command_line):
            if is_dsh_bin_js(path) and normalize_path(path) != wanted:
                others.append((pid, path))
                break
    return others, None
