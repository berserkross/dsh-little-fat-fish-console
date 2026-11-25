"""结束 DSH 时，别把控制台自己算进「DSH 的进程树」。

`taskkill /T` 顺着「父进程 PID」一路往下杀。控制台要是从 DSH 里被拉起来的
（手机端动作、DSH 里的工具调用、在 DSH 会话里跑 `Start-Process` 都算），它就挂在
DSH 的进程树里 —— 于是「重启 DSH」顺手把控制台也杀了：窗口消失、日志断在半句、
下一次点快捷方式又是一个新进程，看起来就像「控制台也跟着重启」。

所以不再用 `taskkill /T`：自己查一遍进程树，算出「DSH 的子孙」减去「控制台和它的
子孙」，再逐个 `Stop-Process`。DSH 自己（树根、控制台的祖先）照杀不误。
"""
from __future__ import annotations

from dshconsole import psrun

PARENT_QUERY = (
    "Get-CimInstance Win32_Process | ForEach-Object { "
    "'{0}={1}' -f $_.ProcessId, $_.ParentProcessId }"
)

KILL_TIMEOUT = 60
QUERY_TIMEOUT = 30


def parse_parents(text: str) -> dict[int, int]:
    """一行一个 `子=父`；解析不了的行直接丢掉，不猜。"""
    pairs: dict[int, int] = {}
    for line in (text or "").splitlines():
        line = line.strip()
        if "=" not in line:
            continue
        left, right = line.split("=", 1)
        try:
            pairs[int(left)] = int(right)
        except ValueError:
            continue
    return pairs


def children_of(parent_of: dict[int, int]) -> dict[int, list[int]]:
    kids: dict[int, list[int]] = {}
    for child, parent in parent_of.items():
        kids.setdefault(parent, []).append(child)
    return kids


def subtree(seeds, kids: dict[int, list[int]]) -> set[int]:
    """这些进程 + 它们所有的子孙（PID 会被回收，所以只沿当前这份表走）。"""
    found: set[int] = set()
    stack = [int(seed) for seed in seeds]
    while stack:
        pid = stack.pop()
        if pid in found:
            continue
        found.add(pid)
        stack.extend(kids.get(pid, ()))
    return found


def ancestors(pid: int, parent_of: dict[int, int], limit: int = 64) -> list[int]:
    """pid 自己和它往上的所有祖先；撞到环或缺号就停。"""
    chain = [int(pid)]
    seen = {int(pid)}
    current = int(pid)
    for _ in range(limit):
        parent = parent_of.get(current)
        if not parent or parent in seen:
            break
        chain.append(parent)
        seen.add(parent)
        current = parent
    return chain


def kill_set(roots, parent_of: dict[int, int], protect) -> list[int]:
    """要结束的进程：roots 的子孙减去 protect 的子树（含 protect 自己）。"""
    kids = children_of(parent_of)
    doomed = subtree(roots, kids)
    keep = subtree(protect, kids) if protect else set()
    return sorted(doomed - keep)


def _script(pids) -> str:
    return "; ".join(f"Stop-Process -Id {int(pid)} -Force -ErrorAction SilentlyContinue"
                     for pid in pids) + "; 'done'"


def stop_tree(roots, protect, runner=None) -> tuple[list[int], list[int], str | None]:
    """结束 roots 的进程树，跳过 protect 及其子孙。

    返回 (真的下手的 PID, 因为 protect 而跳过的 PID, 错误说明)。PID 现查现算：
    传进来的号可能已经被系统回收，绝不能让它们指向控制台自己。
    """
    roots = [int(pid) for pid in roots if pid]
    protect = [int(pid) for pid in (protect or []) if pid]
    if not roots:
        return [], [], None
    run = runner or psrun.run_ps_cmd
    result = run(PARENT_QUERY, timeout=QUERY_TIMEOUT)
    if not result.ok:
        return [], [], "查不到进程树：" + (result.why() or result.text.strip()[:200])
    parent_of = parse_parents(result.stdout)
    if not parent_of:
        return [], [], "进程树查询没有返回任何进程"
    targets = kill_set(roots, parent_of, protect)
    spared = sorted(set(kill_set(roots, parent_of, [])) - set(targets))
    if not targets:
        return [], spared, None
    killed = run(_script(targets), timeout=KILL_TIMEOUT)
    if not killed.ok:
        return targets, spared, killed.why() or killed.text.strip()[:200]
    return targets, spared, None
