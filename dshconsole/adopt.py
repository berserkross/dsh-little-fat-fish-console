"""采纳运行中的实例：把「端口被另一处安装的 DSH 占着」变成一次显式、有记录的接管。

B1 之后进程识别只认「命令行里的 bin.js == 本机配置的 bin.js」，于是 npx 缓存里那份 DSH
（%LOCALAPPDATA%\\npm-cache\\_npx\\<hash>\\node_modules\\@deepseek-ai\\dsh\\lib\\bin.js）在界面上
显示成「异常（端口被占用）」，「停止 / 重启」对它无效。这里不放松识别规则，而是在用户点击时
把候选进程的 bin.js 反推成 harness 写回 config.json —— 显式 --harness 仍然优先，探测优先级不变。
"""
from __future__ import annotations

import json
from dataclasses import dataclass, replace
from pathlib import Path

from . import config, probe, psrun

# bin.js 相对 harness 的层数：harness\node_modules\@deepseek-ai\dsh\lib\bin.js。
# npx 缓存里的安装形状完全相同（那里的 harness 就是 _npx\<hash>），所以按层数反推即可；
# 直接由 BIN_JS_REL 算出，不写死数字，免得哪天相对路径变了反推悄悄错位。
BIN_JS_DEPTH = len(config.BIN_JS_REL.parts)
ADOPTED = "adopted"
# 候选是从哪来的：命令行里扫到的「别的 bin.js」，还是「就问这个端口是谁在听」。
VIA_PROCESS = "process"
VIA_PORT = "port"


@dataclass(frozen=True)
class Candidate:
    """一个「可能是端口占用者」的别的 DSH 进程。"""

    pid: int
    bin_js: str                 # 命令行里的路径，已折叠 . 与 ..
    harness: Path | None        # 反推并校验过的 harness；推不出就是 None（不猜）
    via: str = VIA_PROCESS      # 怎么找到的（见 VIA_*）

    @property
    def label(self) -> str:
        where = self.harness or self.bin_js
        if self.via == VIA_PORT:
            return f"PID {self.pid}（正在监听端口） → {where}"
        return f"PID {self.pid} → {where}"


def harness_from_bin_js(bin_js: object) -> Path | None:
    """由 ...\\node_modules\\@deepseek-ai\\dsh\\lib\\bin.js 反推 harness（剥掉 BIN_JS_REL 那几层）。

    剥出来的目录必须真的装着同一份 bin.js 才认（config.looks_like_harness），否则返回 None：
    宁可让用户手动指定，也不写入一个猜出来的路径。
    """
    if not bin_js:
        return None
    full = Path(probe.display_path(str(bin_js)))
    parts = full.parts
    if len(parts) <= BIN_JS_DEPTH:
        return None
    harness = Path(*parts[:-BIN_JS_DEPTH])
    return harness if config.looks_like_harness(harness) else None


def from_processes(processes: object) -> list[Candidate]:
    """把 probe.other_dsh_processes 的 [(pid, path)] 变成候选列表（同 PID 只留一次）。"""
    found: list[Candidate] = []
    seen: set[int] = set()
    for item in processes or []:
        try:
            pid, path = item
            pid = int(pid)
        except (TypeError, ValueError):
            continue
        if pid in seen or not path:
            continue
        seen.add(pid)
        shown = probe.display_path(str(path))
        found.append(Candidate(pid=pid, bin_js=shown, harness=harness_from_bin_js(shown)))
    return found


def candidates(bin_js: object = None, runner=None) -> tuple[list[Candidate] | None, str | None]:
    """现查一遍候选（None = 查不到，不是「没有候选」）。"""
    others, err = probe.other_dsh_processes(bin_js, runner)
    if others is None:
        return None, err
    return from_processes(others), None



# ---------------- 端口占用者（最直接的那条线索） ----------------
# 只按命令行里的 bin.js 找候选有个真实的漏网场景：npx 缓存、换过 node 路径、
# 或者从别的目录起的实例，命令行形状与本机配置对不上，于是「改为控制运行中的实例」
# 根本不出现 —— 明明端口被占着，用户却只能手动改 config.json。
# 这条路反过来问系统：这个端口现在是谁在听。
PORT_OWNER_TIMEOUT = 20


def port_owner_command(port: int) -> str:
    """一条 PowerShell：监听 port 的 PID + 它的命令行（一次冷启动，不做两次查询）。"""
    return (
        "$ErrorActionPreference = 'Stop'; "
        f"$conn = @(Get-NetTCPConnection -LocalPort {int(port)} -State Listen "
        "-ErrorAction Stop | Select-Object -First 1); "
        "if ($conn.Count -eq 0) { 'null'; exit 0 }; "
        "$own = [int]$conn[0].OwningProcess; "
        "$proc = Get-CimInstance Win32_Process -Filter \"ProcessId=$own\" -ErrorAction Stop; "
        "ConvertTo-Json -InputObject ([ordered]@{ pid = $own;"
        " command_line = [string]$proc.CommandLine }) -Compress"
    )


def parse_port_owner(text: str) -> tuple[int, str] | None:
    """解析端口占用者。'null' / 空 / 坏 JSON 一律 None（= 没问到，不是猜一个）。"""
    raw = (text or "").strip()
    if not raw or raw.lower() == "null":
        return None
    line = raw.splitlines()[-1]
    try:
        data = json.loads(line)
    except ValueError:
        return None
    if not isinstance(data, dict):
        return None
    try:
        pid = int(data.get("pid"))
    except (TypeError, ValueError):
        return None
    return pid, str(data.get("command_line") or "")


def bin_js_from_command_line(command_line: str) -> str | None:
    """从命令行里挑出那个 DSH 的 bin.js（按路径规则认，不按位置猜）。"""
    for path in probe.command_line_paths(command_line or ""):
        if probe.is_dsh_bin_js(path):
            return probe.display_path(path)
    return None


def from_port_owner(port: int, runner=None) -> tuple[Candidate | None, str | None]:
    """问「谁在监听 port」：拿得到就是最可靠的候选，拿不到就交出原因。

    返回 (candidate, why)：candidate 为 None 时 why 说明为什么没接上候选；
    端口其实没被占用时 why 也是 None —— 那不是失败，是没得接管。
    """
    run = runner or psrun.run_ps_cmd
    result = run(port_owner_command(port), timeout=PORT_OWNER_TIMEOUT)
    if not result.ok:
        return None, f"查端口 {port} 的占用者失败：{result.why() or result.text.strip()[:200]}"
    parsed = parse_port_owner(result.stdout)
    if parsed is None:
        return None, None
    pid, command_line = parsed
    bin_js = bin_js_from_command_line(command_line)
    if bin_js is None:
        return None, (f"端口 {port} 被 PID {pid} 占用，但它的命令行里没有 DSH 的 bin.js，"
                      "无法确认该接管哪处安装。")
    return Candidate(pid=pid, bin_js=bin_js,
                     harness=harness_from_bin_js(bin_js), via=VIA_PORT), None


def merge(*groups: list[Candidate], limit: int = 3) -> list[Candidate]:
    """按 PID 去重合并候选，先来的先留（端口占用者最该排在第一个）。"""
    found: list[Candidate] = []
    seen: set[int] = set()
    for group in groups:
        for candidate in group or []:
            if candidate.pid in seen:
                continue
            seen.add(candidate.pid)
            found.append(candidate)
            if len(found) >= limit:
                return found
    return found

def adopt(cfg, candidate: Candidate, path=None):
    """把候选写回 config.json，返回 (新配置, 说明)；harness 推不出时拒绝并说明怎么手动指定。"""
    if candidate.harness is None:
        return None, (f"推不出 PID {candidate.pid} 那处安装的 harness 目录"
                      f"（{candidate.bin_js}）。请用 --harness 指定，或手动编辑 config.json。")
    new = replace(cfg, harness=candidate.harness, bin_js=Path(candidate.bin_js),
                  source=ADOPTED)
    config.save(new, path)
    return new, f"已改为控制 {new.harness}（PID {candidate.pid}）"
