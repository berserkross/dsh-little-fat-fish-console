"""配置层：路径/端口探测 + config.json 持久化。

约定：每个探测项都按「显式参数 > config.json 记录 > 环境变量 > 常见安装位 > 放弃」
的顺序回退，找不到就返回 None，绝不抛异常 —— GUI 靠 None 决定要不要弹目录选择。

只依赖标准库，导入本模块不会拉起 tkinter。
"""
from __future__ import annotations

import json
import os
import re
import shutil
from dataclasses import dataclass
from pathlib import Path

from . import resources

APP_NAME = "dsh-console"
CONFIG_ENV = "DSH_CONSOLE_CONFIG"   # 测试/便携场景可整体改写配置文件位置
DEFAULT_PORT = 3080
BIN_JS_REL = Path("node_modules") / "@deepseek-ai" / "dsh" / "lib" / "bin.js"
TOKEN_LOG_NAME = "dsh-web.stdout.log"


def _is_dir(value: object) -> bool:
    try:
        return bool(value) and Path(str(value)).is_dir()
    except OSError:
        return False


def _is_file(value: object) -> bool:
    try:
        return bool(value) and Path(str(value)).is_file()
    except OSError:
        return False


def _first_file(candidates: list[Path]) -> Path | None:
    for cand in candidates:
        if _is_file(cand):
            return cand
    return None


def _env(name: str) -> str:
    return os.environ.get(name) or ""


# ---------------- 单项探测 ----------------
def looks_like_harness(path: object) -> bool:
    """harness 目录的唯一判据：里面装着 node_modules/@deepseek-ai/dsh/lib/bin.js。"""
    if not path:
        return False
    try:
        return (Path(str(path)) / BIN_JS_REL).is_file()
    except OSError:
        return False


def harness_from_dsh() -> Path | None:
    """由 PATH 上的 dsh 命令反推 harness 目录（npm 全局安装读 shim 正文找 bin.js）。"""
    shim = shutil.which("dsh")
    if not shim:
        return None
    shim_path = Path(shim)
    if looks_like_harness(shim_path.parent):
        return shim_path.parent
    try:
        text = shim_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        text = ""
    match = re.search(
        r"([A-Za-z]:\\[^\"'\r\n]*?)\\node_modules\\@deepseek-ai\\dsh\\lib\\bin\\.js", text
    )
    if match and looks_like_harness(match.group(1)):
        return Path(match.group(1))
    for parent in list(shim_path.parents)[:6]:
        if looks_like_harness(parent):
            return parent
    return None


def common_harness_candidates() -> list[Path]:
    roots = [Path(_env(k)) for k in ("LOCALAPPDATA", "APPDATA", "USERPROFILE") if _env(k)]
    candidates: list[Path] = []
    for root in roots:
        candidates += [
            root / "Programs" / "deepseek-harness",
            root / "Programs" / "dsh",
            root / "deepseek-harness",
            root / "npm",
        ]
    candidates.append(Path.home() / "Documents" / "Codex" / "apps" / "deepseek-harness")
    candidates.append(Path("C:/deepseek-harness"))
    return candidates


def harness_from_cwd(cwd: str | Path | None = None) -> Path | None:
    """从当前目录向上找：仓库里直接跑 dsh_gui.py 时最省事的一条路。"""
    try:
        start = Path(cwd if cwd is not None else Path.cwd()).resolve()
    except OSError:
        return None
    for depth, parent in enumerate([start, *start.parents]):
        if depth > 12:
            break
        if looks_like_harness(parent):
            return parent
    return None


def harness_from_dsh_home() -> Path | None:
    """DSH_HOME 指向 .dsh，harness 是它的父目录；父目录不成立时看它下面的 apps/*。"""
    env_home = _env("DSH_HOME")
    if not env_home:
        return None
    parent = Path(env_home).parent
    if looks_like_harness(parent):
        return parent
    hits: list[Path] = []
    for base in (parent, parent / "apps"):   # 也认 <root>\apps\<harness> 这种分居布局
        try:
            subdirs = [p for p in sorted(base.glob("*")) if p.is_dir()]
        except OSError:
            continue
        hits += [p for p in subdirs if looks_like_harness(p)]
    if not hits:
        return None
    hits.sort(key=lambda p: ("harness" not in p.name.lower(), p.name.lower()))
    return hits[0]


def detect_harness(explicit: object = None, stored: object = None,
                   cwd: str | Path | None = None) -> Path | None:
    """显式 > 记录 > DSH_HOME 父目录 > dsh 命令 > 常见安装位 > cwd 向上 > None。"""
    for cand in (explicit, stored):
        if _is_dir(cand):
            return Path(str(cand))
    found = harness_from_dsh_home()
    if found:
        return found
    found = harness_from_dsh()
    if found:
        return found
    for cand in common_harness_candidates():
        if looks_like_harness(cand):
            return cand
    return harness_from_cwd(cwd)


def node_candidates() -> list[Path]:
    candidates = [
        Path(r"D:\Program Files\nodejs\node.exe"),
        Path(r"C:\Program Files\nodejs\node.exe"),
    ]
    for key in ("ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA"):
        base = _env(key)
        if base:
            candidates += [Path(base) / "nodejs" / "node.exe",
                           Path(base) / "Programs" / "nodejs" / "node.exe"]
    runtimes = Path.home() / ".cache" / "codex-runtimes"
    try:
        candidates += sorted(runtimes.glob("*/dependencies/node/bin/node.exe"))
    except OSError:
        pass
    return candidates


def detect_node(stored: object = None) -> Path | None:
    if _is_file(stored):
        return Path(str(stored))
    which = shutil.which("node")
    if which and _is_file(which):
        return Path(which)
    return _first_file(node_candidates())


def detect_dsh_home(stored: object = None) -> Path | None:
    if _is_dir(stored):
        return Path(str(stored))
    env_home = _env("DSH_HOME")
    if env_home:
        return Path(env_home)
    for cand in (Path.home() / "Documents" / "Codex" / ".dsh", Path.home() / ".dsh"):
        if _is_dir(cand):
            return cand
    return None


def detect_chrome(stored: object = None) -> Path | None:
    if _is_file(stored):
        return Path(str(stored))
    return _first_file([
        Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
        Path(r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"),
        Path(r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"),
        Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
    ])


def detect_tailscale(stored: object = None) -> Path | None:
    if _is_file(stored):
        return Path(str(stored))
    which = shutil.which("tailscale")
    if which and _is_file(which):
        return Path(which)
    return _first_file([Path(r"C:\Program Files\Tailscale\tailscale.exe")])


def resolve_port(explicit: object = None, stored: object = None) -> int:
    for value in (explicit, stored):
        try:
            port = int(value)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            continue
        if 0 < port < 65536:
            return port
    return DEFAULT_PORT


# ---------------- config.json ----------------
def config_path() -> Path:
    """%APPDATA%\\dsh-console\\config.json（用户名一律从环境变量取）。"""
    override = _env(CONFIG_ENV)
    if override:
        return Path(override).expanduser()
    base = Path(_env("APPDATA")) if _env("APPDATA") else Path.home() / "AppData" / "Roaming"
    return base / APP_NAME / "config.json"


_VALIDATORS = {
    "harness": _is_dir,
    "dsh_home": _is_dir,
    "node": _is_file,
    "bin_js": _is_file,
    "chrome": _is_file,
    "tailscale": _is_file,
}


def load(path: str | Path | None = None) -> dict:
    """读取记录；路径已失效的键直接丢弃，交给下一次探测重新决定。"""
    target = Path(path) if path else config_path()
    try:
        raw = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(raw, dict):
        return {}
    data: dict = {}
    for key, validator in _VALIDATORS.items():
        value = raw.get(key)
        if isinstance(value, str) and value and validator(value):
            data[key] = value
    port = raw.get("port")
    if isinstance(port, int) and 0 < port < 65536:
        data["port"] = port
    return data


def save(cfg: "DshConfig", path: str | Path | None = None) -> Path:
    """写入当前解析结果：用户显式选择的值 + 上次成功的探测结果。"""
    target = Path(path) if path else config_path()
    data: dict = {"port": int(cfg.port)}
    for key in ("harness", "node", "bin_js", "dsh_home", "chrome", "tailscale"):
        value = getattr(cfg, key, None)
        if value:
            data[key] = str(value)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return target


# ---------------- 汇总 ----------------
@dataclass
class DshConfig:
    """一次解析得到的完整运行配置；路径缺失用 None 表示。"""

    harness: Path | None = None
    node: Path | None = None
    bin_js: Path | None = None
    dsh_home: Path | None = None
    port: int = DEFAULT_PORT
    chrome: Path | None = None
    tailscale: Path | None = None
    icon: Path | None = None

    @property
    def ready(self) -> bool:
        """启动 ps1 的最小条件：harness 与 node 都在。"""
        return bool(self.harness and self.node)

    @property
    def token_log(self) -> Path | None:
        """两个 ps1 都把启动日志写在 harness 目录下。"""
        return (self.harness / TOKEN_LOG_NAME) if self.harness else None

    @classmethod
    def resolve(cls, explicit_harness: object = None, explicit_port: object = None,
                path: str | Path | None = None, cwd: str | Path | None = None) -> "DshConfig":
        data = load(path)
        harness = detect_harness(explicit_harness, data.get("harness"), cwd)
        bin_js = (harness / BIN_JS_REL) if harness else None
        if bin_js is not None and not bin_js.is_file():
            bin_js = None
        return cls(
            harness=harness,
            node=detect_node(data.get("node")),
            bin_js=bin_js,
            dsh_home=detect_dsh_home(data.get("dsh_home")),
            port=resolve_port(explicit_port, data.get("port")),
            chrome=detect_chrome(data.get("chrome")),
            tailscale=detect_tailscale(data.get("tailscale")),
            icon=resources.icon_path(),
        )


def resolve(explicit_harness: object = None, explicit_port: object = None,
            path: str | Path | None = None, cwd: str | Path | None = None) -> DshConfig:
    """便捷入口：一次调用完成全部探测（load()/save() 只管持久化）。"""
    return DshConfig.resolve(explicit_harness, explicit_port, path, cwd)
