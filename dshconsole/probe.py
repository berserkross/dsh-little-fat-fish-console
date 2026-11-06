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
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from .psrun import PsResult, run_native, run_ps_cmd

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
TOKEN_PROBE_TIMEOUT = 2.0


def token_accepted(port: int, token: str, host: str = "127.0.0.1",
                   timeout: float = TOKEN_PROBE_TIMEOUT, opener=None) -> bool | None:
    """拿 token 去问一次正在运行的 DSH：True=认，False=不认（401），None=问不到。

    为什么必须问：控制台手里的 token 是从启动日志里抠出来的，只有「本控制台启动的
    那一次」会写这行。DSH 被别处（桌面版、别的终端、别的控制台）重启过之后，日志里
    的 token 就成了旧钥匙 —— 手机扫码只会得到 401，而界面上看不出任何异常。
    """
    if not token:
        return False
    url = f"http://{host}:{int(port)}/?token={token}"
    open_url = opener or urllib.request.urlopen
    try:
        with open_url(url, timeout=timeout) as response:
            return 200 <= int(getattr(response, "status", 200) or 200) < 400
    except urllib.error.HTTPError as exc:
        return False if int(getattr(exc, "code", 0) or 0) == 401 else None
    except (urllib.error.URLError, OSError, ValueError):
        return None


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
    return _process_pairs(data)[0]


def _process_pairs(data: object) -> tuple[list[tuple[int, str]] | None, str | None]:
    """已经是 Python 对象（批量探测的 JSON 段）时走这条路，省一次 dumps/loads。"""
    if data is None:
        return None, "node 进程查询没有返回内容"
    if isinstance(data, dict):
        data = [data]
    if not isinstance(data, list):
        return None, "node 进程查询没有返回进程列表"
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
        else:
            return None, "部分 node 进程命令行不可读取，无法安全判定 DSH 是否运行"
    return processes, None


def node_processes(runner: Runner | None = None) -> tuple[list[tuple[int, str]] | None, str | None]:
    run = runner or run_ps_cmd
    result = run(PROCESS_QUERY, timeout=30)
    if not result.ok:
        return None, _failure("node 进程查询失败", result)
    processes = parse_process_list(result.stdout)
    if processes is None:
        return None, "node 进程查询没有返回可解析的进程列表"
    return processes, None


def classify(processes: list[tuple[int, str]],
             bin_js: Path | str | None) -> tuple[list[int], list[tuple[int, str]]]:
    """一份进程列表同时算出「本机 DSH 的 PID」与「别的安装里的 DSH」。

    两条判断合成一次遍历：批量查询已经拿到进程列表，再各自 spawn 一次纯属浪费。
    """
    wanted = normalize_path(str(bin_js)) if bin_js else ""
    pids: set[int] = set()
    others: list[tuple[int, str]] = []
    for pid, command_line in processes:
        paths = command_line_paths(command_line)
        if wanted and any(normalize_path(path) == wanted for path in paths):
            pids.add(pid)
            continue
        for path in paths:
            if is_dsh_bin_js(path) and normalize_path(path) != wanted:
                others.append((pid, path))
                break
    return sorted(pids), others


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
    pids, _others = classify(processes, bin_js)
    return pids, None


def other_dsh_processes(bin_js: Path | str | None,
                        runner: Runner | None = None) -> tuple[list[tuple[int, str]] | None, str | None]:
    """别的安装（npx 缓存等）里的 bin.js 进程：只用来解释「端口被谁占着」，不参与停止。"""
    processes, err = node_processes(runner)
    if processes is None:
        return None, err
    _pids, others = classify(processes, bin_js)
    return others, None

# ---------------- 一次刷新问完全部问题 ----------------
# 逐项 spawn 的实测开销（本机，冷缓存）：powershell 冷启动 ≈1.0~1.15s，
#   dsh_processes 2.23s / other_dsh_processes 2.07s / portproxy 1.36s /
#   firewall_rule 4.41s / lan_ips 2.46s → 合计 12~15s。
# 两条优化一起用：
#   1) 进程 / 网卡 / tailscale 合并进**一个** PowerShell 脚本，一次冷启动；
#   2) 两条 netsh 直接当原生 EXE 跑（各 ~0.10s），与 PS 那一路并行（ThreadPoolExecutor）。
# 于是关键路径 = PS 启动 + CIM 查询，而不是「五项探测相加」。
BATCH_TIMEOUT = 25
NETSH_TIMEOUT = 15
# netsh 的「没有这条规则」退出码：Windows 上会以 1 / -1 / 4294967295 的面貌出现。
MISSING_RULE_CODES = (0, 1, -1, 4294967295)


def _ps_quote(value: object) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def core_command() -> str:
    """一个 PowerShell 脚本，输出 JSON：node 进程 / 网卡地址（带来源名）/ tailscale 地址。

    进程查询用 Get-CimInstance（CommandLine 只有它能给）；网卡地址用 .NET
    NetworkInterface —— Get-NetIPAddress 要 451ms，它只要 ~60ms，而且能顺带
    拿到网卡名（Tailscale / 以太网 / WLAN）做下拉的来源标注。
    """
    parts = [
        "$ErrorActionPreference = 'Stop'",
        "$out = [ordered]@{}",
        "function Step([string]$name, [scriptblock]$body) {",
        "  $t = [System.Diagnostics.Stopwatch]::StartNew()",
        "  try { $out[$name] = & $body } catch { $out[($name + '_error')] = $_.Exception.Message }",
        "  $t.Stop()",
        "  $out[($name + '_ms')] = [int]$t.ElapsedMilliseconds",
        "}",
        "$all = [System.Diagnostics.Stopwatch]::StartNew()",
        "Step 'node' {",
        "  @(Get-CimInstance Win32_Process -Filter \"Name='node.exe'\" -ErrorAction Stop |",
        "    Select-Object ProcessId, CommandLine)",
        "}",
        "Step 'addresses' {",
        "  $list = @()",
        "  foreach ($nic in [System.Net.NetworkInformation.NetworkInterface]::GetAllNetworkInterfaces()) {",
        "    if ($nic.OperationalStatus -ne [System.Net.NetworkInformation.OperationalStatus]::Up) { continue }",
        "    foreach ($uni in $nic.GetIPProperties().UnicastAddresses) {",
        "      if ($uni.Address.AddressFamily -ne [System.Net.Sockets.AddressFamily]::InterNetwork) { continue }",
        "      $list += [ordered]@{ ip = $uni.Address.IPAddressToString; name = $nic.Name;",
        "        kind = $nic.NetworkInterfaceType.ToString() }",
        "    }",
        "  }",
        "  $list",
        "}",
    ]
    parts += [
        "$all.Stop()",
        "$out['total_ms'] = [int]$all.ElapsedMilliseconds",
        "ConvertTo-Json -InputObject $out -Depth 6 -Compress",
    ]
    return "\n".join(parts) + "\n"


def _is_lan_ip(ip: str) -> bool:
    return bool(re.match(r"^(10|192\.168|172\.(1[6-9]|2\d|3[01]))\.", ip))


def portproxy_text(runner: Runner | None = None) -> tuple[str | None, str | None]:
    """端口转发表格的原文（直接调 netsh.exe，~0.10s）。"""
    run = runner or run_native
    result = run(["netsh", "interface", "portproxy", "show", "v4tov4"], timeout=NETSH_TIMEOUT)
    if not result.ok:
        return None, _failure("端口转发查询失败", result)
    return result.text, None


def netsh_firewall_state(port: int,
                         runner: Runner | None = None) -> tuple[bool | None, str | None, str]:
    """(有规则 / 未定, 未知原因, netsh 原始输出)。

    判定顺序：输出里有规则名 → 有这条规则（netsh 找到时会回显规则名）；
    没有规则名且退出码属于「没有匹配规则」→ 没有这条规则；
    其余（netsh 本身报错）→ 未知 + 原因。实测 0.10s，而 Get-NetFirewallRule 要 2.6s。
    """
    run = runner or run_native
    rule = FIREWALL_RULE.format(port=port)
    result = run(["netsh", "advfirewall", "firewall", "show", "rule", "name=" + rule],
                 timeout=NETSH_TIMEOUT)
    text = result.text
    if rule.lower() in text.lower():
        return True, None, text
    code = result.code
    if code is not None and code in MISSING_RULE_CODES:
        return False, None, text
    return None, result.why() or "防火墙规则查询没有给出结论", text


def tailscale_ip_native(exe: Path | str | None,
                        runner: Runner | None = None) -> tuple[str | None, str | None]:
    """直接跑 tailscale.exe（~0.05s）而不是让 PowerShell 代跑：省掉一段串行等待。"""
    if not exe:
        return None, "未检测到 tailscale.exe（可在 config.json 里指定路径）"
    run = runner or run_native
    result = run([str(exe), "ip", "-4"], timeout=NETSH_TIMEOUT)
    if not result.ok:
        return None, _failure("tailscale ip 查询失败", result)
    for token in result.text.split():
        found = _ipv4(token)
        if found and not found.startswith("127."):
            return found, None
    return None, "tailscale 没有返回可用的 IPv4 地址"


@dataclass(frozen=True)
class RawProbe:
    """批量探测的原始结果：字段全是「值 / None + 原因」，判定留给 status。"""

    processes: list[tuple[int, str]] | None = None
    process_error: str | None = None
    portproxy_text: str | None = None
    portproxy_error: str | None = None
    firewall: bool | None = None
    firewall_error: str | None = None
    firewall_text: str = ""
    addresses: list[tuple[str, str]] | None = None     # (地址, 来源名)
    address_error: str | None = None
    ts_ip: str | None = None
    ts_error: str | None = None
    timings: dict[str, int] = field(default_factory=dict)
    total_ms: int = 0

    @property
    def lan_ips(self) -> list[str] | None:
        """标「局域网」的地址（10/192.168/172.16-31，排除 tailscale 的 100.x）。"""
        if self.addresses is None:
            return None
        found: list[str] = []
        for ip, _source in self.addresses:
            if _is_lan_ip(ip) and ip not in found:
                found.append(ip)
        return found


def parse_batch(text: str) -> dict | None:
    raw = (text or "").strip()
    if not raw.startswith("{"):
        return None
    try:
        data = json.loads(raw)
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def _batch_addresses(items: object) -> tuple[list[tuple[str, str]] | None, str | None]:
    if isinstance(items, dict):
        items = [items]
    if not isinstance(items, list):
        return None, "网卡地址查询没有返回列表"
    found: list[tuple[str, str]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        ip = _ipv4(str(item.get("ip") or ""))
        if not ip or ip.startswith(("127.", "169.254.")):
            continue
        name = str(item.get("name") or "").strip()
        kind = str(item.get("kind") or "").strip()
        if not name:
            name = {"Wireless80211": "WLAN", "Ethernet": "以太网"}.get(kind, kind or "网卡")
        if all(ip != seen for seen, _ in found):
            found.append((ip, name))
    return found, None


def _batch_ts(data: dict) -> tuple[str | None, str | None]:
    for token in str(data.get("tailscale") or "").split():
        found = _ipv4(token)
        if found and not found.startswith("127."):
            return found, None
    reason = str(data.get("tailscale_error") or "").strip()
    if reason:
        return None, f"tailscale ip 查询失败：{reason}"
    return None, "tailscale 没有返回可用的 IPv4 地址"


def _timings(data: dict) -> dict[str, int]:
    found: dict[str, int] = {}
    for key, value in data.items():
        if isinstance(key, str) and key.endswith("_ms"):
            try:
                found[key[:-3]] = int(value)
            except (TypeError, ValueError):
                continue
    return found


def _core_section(run: Runner, timeout: int) -> dict:
    """跑那一个 PowerShell 脚本，返回解析好的 JSON（失败时返回带 error 的字典）。"""
    result = run(core_command(), timeout=timeout)
    if not result.ok:
        return {"_error": _failure("进程与网卡查询失败", result)}
    data = parse_batch(result.stdout)
    if data is None:
        return {"_error": "进程与网卡查询没有返回可解析的 JSON"}
    return data


def probe_all(port: int, tailscale: Path | str | None = None,
              runner: Runner | None = None, timeout: int = BATCH_TIMEOUT,
              proxy_runner: Runner | None = None,
              firewall_runner: Runner | None = None,
              tailscale_runner: Runner | None = None) -> RawProbe:
    """一次完整探测：四条并行的原生/PS 查询，总耗时≈最慢那一路。

    PowerShell 那一路只做「进程列表 + 网卡地址」（WMI 与 .NET 都要它），
    两条 netsh 与 tailscale.exe 直接原生跑 —— 于是 2 个约 1.2s 的 PowerShell
    冷启动被压成 1 个，其余的 0.1s 级查询互相重叠。
    每段耗时都记在 timings 里（诊断包会打印出来），所以「为什么慢」不用猜。
    """
    started = time.monotonic()
    run = runner or run_ps_cmd
    with ThreadPoolExecutor(max_workers=4) as pool:
        ps_future = pool.submit(_core_section, run, timeout)
        proxy_future = pool.submit(portproxy_text, proxy_runner)
        firewall_future = pool.submit(netsh_firewall_state, port, firewall_runner)
        ts_future = pool.submit(tailscale_ip_native, tailscale, tailscale_runner)
        data = ps_future.result()
        proxy, proxy_err = proxy_future.result()
        firewall, firewall_err, firewall_raw = firewall_future.result()
        ts_ip, ts_error = ts_future.result()
    timings = _timings({k: v for k, v in data.items() if not k.startswith("_")})
    core_error = data.get("_error")

    processes, process_error = _process_pairs(data.get("node"))
    if processes is None:
        process_error = str(data.get("node_error") or "").strip() or process_error or core_error
    addresses, address_error = _batch_addresses(data.get("addresses"))
    if addresses is None:
        address_error = str(data.get("addresses_error") or "").strip() or address_error or core_error
    if ts_ip is None and addresses:
        # 网卡里已经能看到 tailscale 的 100.x：tailscale.exe 没跑起来也不至于未知。
        ts_ip = next((ip for ip, _source in addresses if ip.startswith("100.")), None)
        if ts_ip:
            ts_error = None

    return RawProbe(
        processes=processes,
        process_error=None if processes is not None else (process_error or core_error),
        portproxy_text=proxy,
        portproxy_error=proxy_err,
        firewall=firewall,
        firewall_error=firewall_err,
        firewall_text=firewall_raw,
        addresses=addresses,
        address_error=address_error,
        ts_ip=ts_ip,
        ts_error=None if ts_ip else ts_error,
        timings=timings,
        total_ms=int(round((time.monotonic() - started) * 1000)),
    )
