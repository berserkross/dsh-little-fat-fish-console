"""采纳运行中的实例：把「端口被另一处安装的 DSH 占着」变成一次显式、有记录的接管。

B1 之后进程识别只认「命令行里的 bin.js == 本机配置的 bin.js」，于是 npx 缓存里那份 DSH
（%LOCALAPPDATA%\\npm-cache\\_npx\\<hash>\\node_modules\\@deepseek-ai\\dsh\\lib\\bin.js）在界面上
显示成「异常（端口被占用）」，「停止 / 重启」对它无效。这里不放松识别规则，而是在用户点击时
把候选进程的 bin.js 反推成 harness 写回 config.json —— 显式 --harness 仍然优先，探测优先级不变。
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path

from . import config, probe

# bin.js 相对 harness 的层数：harness\node_modules\@deepseek-ai\dsh\lib\bin.js。
# npx 缓存里的安装形状完全相同（那里的 harness 就是 _npx\<hash>），所以按层数反推即可；
# 直接由 BIN_JS_REL 算出，不写死数字，免得哪天相对路径变了反推悄悄错位。
BIN_JS_DEPTH = len(config.BIN_JS_REL.parts)
ADOPTED = "adopted"


@dataclass(frozen=True)
class Candidate:
    """一个「可能是端口占用者」的别的 DSH 进程。"""

    pid: int
    bin_js: str                 # 命令行里的路径，已折叠 . 与 ..
    harness: Path | None        # 反推并校验过的 harness；推不出就是 None（不猜）

    @property
    def label(self) -> str:
        return f"PID {self.pid} → {self.harness or self.bin_js}"


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


def adopt(cfg, candidate: Candidate, path=None):
    """把候选写回 config.json，返回 (新配置, 说明)；harness 推不出时拒绝并说明怎么手动指定。"""
    if candidate.harness is None:
        return None, (f"推不出 PID {candidate.pid} 那处安装的 harness 目录"
                      f"（{candidate.bin_js}）。请用 --harness 指定，或手动编辑 config.json。")
    new = replace(cfg, harness=candidate.harness, bin_js=Path(candidate.bin_js),
                  source=ADOPTED)
    config.save(new, path)
    return new, f"已改为控制 {new.harness}（PID {candidate.pid}）"
