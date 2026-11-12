#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""文档事实检查：README / CHANGELOG 里写下的事实必须能从仓库现状验证。

检查项：
  1. 版本号四处一致：__version__ / README 当前版本 / version_info.txt 字符串与
     filevers 元组 / CHANGELOG 最新版本。
  2. README 声明的用例数等于 tests/ 里 `def test_` 的实际数量。
  3. README 与 CHANGELOG 里反引号引用的仓库内路径真实存在。
  4. 同一行里「文件 + N 行」的声明与文件实际行数一致。
  5. README 代码块里作为命令参数出现的仓库文件真实存在。

只检查静态可判定的事实；运行时输出、Release 资产、真实 DSH 环境不在此脚本范围内。

用法：python scripts/check_docs.py
失败返回 1，并把每条不一致打印到 stderr；CI 在单元测试之前执行。
"""
from __future__ import annotations

import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

# Windows 控制台默认 GBK，中文输出会乱码；统一走 UTF-8（Linux 下是无操作）。
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]
DOCS = ("README.md", "CHANGELOG.md")
PATH_PREFIXES = ("dshconsole/", "tests/", "docs/", "scripts/", "certs/")
TOP_FILES = {
    "dsh_gui.py",
    "requirements.txt",
    "version_info.txt",
    "DSHConsole.spec",
    "CHANGELOG.md",
    "README.md",
    "LICENSE",
    "SECURITY.md",
    "NIGHT-LOG.md",
}
SKIP_PREFIXES = ("dist/", "build/", ".venv/", "~", "%")

problems: list[str] = []


def read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def fail(msg: str) -> None:
    problems.append(msg)


def version_of() -> str | None:
    m = re.search(r'__version__\s*=\s*"([^"]+)"', read("dshconsole/__init__.py"))
    if not m:
        fail("dshconsole/__init__.py 里找不到 __version__")
        return None
    return m.group(1)


def check_version() -> None:
    version = version_of()
    if version is None:
        return

    m = re.search(r"\*\*当前版本\s*v?([0-9]+(?:\.[0-9]+)+)\*\*", read("README.md"))
    if not m:
        fail("README 缺少「**当前版本 x.y.z**」声明")
    elif m.group(1) != version:
        fail(f"README 当前版本 {m.group(1)} != dshconsole/__init__.py {version}")

    vi = read("version_info.txt")
    for key in ("FileVersion", "ProductVersion"):
        m = re.search(rf"StringStruct\('{key}', '([^']+)'\)", vi)
        if not m:
            fail(f"version_info.txt 缺少 {key}")
        elif m.group(1) != version + ".0":
            fail(f"version_info.txt {key}={m.group(1)} != {version}.0")

    m = re.search(r"filevers=\(([^)]*)\)", vi)
    if not m:
        fail("version_info.txt 缺少 filevers 元组")
    else:
        got = tuple(int(x) for x in re.findall(r"\d+", m.group(1)))
        want = tuple(int(x) for x in (version.split(".") + ["0"] * 4)[:4])
        if got != want:
            fail(f"version_info.txt filevers={got} != {want}")

    m = re.search(r"##\s*\[?([0-9]+\.[0-9]+\.[0-9]+)\]?", read("CHANGELOG.md"))
    if m and m.group(1) != version:
        fail(f"CHANGELOG 最新版本 {m.group(1)} != {version}")


def check_test_count() -> None:
    count = 0
    for path in sorted((ROOT / "tests").glob("test_*.py")):
        count += len(re.findall(r"^\s*def\s+test_", path.read_text(encoding="utf-8"), re.M))
    m = re.search(r"共\s*(\d+)\s*个用例", read("README.md"))
    if not m:
        fail("README 缺少「共 N 个用例」声明")
    elif int(m.group(1)) != count:
        fail(f"README 声明 {m.group(1)} 个用例，tests/ 实际有 {count} 个 def test_")


def check_paths() -> None:
    for doc in DOCS:
        for token in re.findall(r"`([^`\n]+)`", read(doc)):
            path = token.replace("\\", "/").strip()
            if path.startswith(SKIP_PREFIXES) or any(c in path for c in "*<>{}|"):
                continue
            if not (path.startswith(PATH_PREFIXES) or path in TOP_FILES):
                continue
            if not (ROOT / path).exists():
                fail(f"{doc} 引用了不存在的路径：{token}")


def check_line_counts() -> None:
    for doc in DOCS:
        for line in read(doc).splitlines():
            if "上限" in line:
                continue
            numbers = re.findall(r"(\d+)\s*行", line)
            paths = re.findall(r"`([\w./\\-]+\.(?:py|js|md|ps1))`", line)
            if len(numbers) != 1 or len(paths) != 1:
                continue
            path = paths[0].replace("\\", "/")
            target = ROOT / path
            if path.startswith(SKIP_PREFIXES) or not target.is_file():
                continue
            actual = sum(1 for _ in target.open(encoding="utf-8", errors="replace"))
            if actual != int(numbers[0]):
                fail(f"{doc} 声明 {path} 有 {numbers[0]} 行，实际 {actual} 行")


def check_commands() -> None:
    for block in re.findall(r"```[a-zA-Z0-9]*\n(.*?)```", read("README.md"), re.S):
        for token in re.findall(r"[\w./\\-]+\.(?:py|ps1|spec|txt|md|json)", block):
            path = token.replace("\\", "/")
            if path.startswith(SKIP_PREFIXES) or any(c in path for c in "*<>$%{}"):
                continue
            if "/" in path:
                if not path.startswith(PATH_PREFIXES):
                    continue
            elif path not in {
                "dsh_gui.py",
                "requirements.txt",
                "DSHConsole.spec",
                "version_info.txt",
            }:
                continue
            if not (ROOT / path).exists():
                fail(f"README 命令里引用了不存在的文件：{token}")


def check_release_claims() -> None:
    """当前版本的 Release 若附带 exe，README/构建文档不得再声称「不附带 exe / 未签名」。

    需要 GITHUB_TOKEN 与 GITHUB_REPOSITORY（Actions 默认提供前者由 workflow 注入）。
    本地无凭据时跳过并明确说明，不假装检查过。
    """
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    repo = os.environ.get("GITHUB_REPOSITORY")
    version = version_of()
    if not (token and repo and version):
        print("跳过 Release 资产检查（缺少 GITHUB_TOKEN / GITHUB_REPOSITORY）。")
        return

    url = f"https://api.github.com/repos/{repo}/releases/tags/v{version}"
    request = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "User-Agent": "dsh-console-docs-check",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            payload = json.load(response)
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            fail(f"Release v{version} 不存在：README 的「当前版本」应指向一个真实 Release")
        else:
            print(f"跳过 Release 资产检查（GitHub API 返回 {exc.code}）。")
        return
    except (urllib.error.URLError, TimeoutError) as exc:
        print(f"跳过 Release 资产检查（网络不可用：{exc}）。")
        return

    assets = payload.get("assets") or []
    has_exe = any(str(a.get("name", "")).lower().endswith(".exe") for a in assets)
    if not has_exe:
        return

    stale_phrases = ("不附带 exe", "不随 Release 分发 exe", "产物未签名", "未签名的现实")
    for doc in ("README.md", "docs/build-and-signing.md"):
        text = read(doc)
        for phrase in stale_phrases:
            if phrase in text:
                fail(
                    f"Release v{version} 已附带 exe，但 {doc} 仍写着「{phrase}」"
                    f"——发布方式变了，文档没有跟着改"
                )


def main() -> int:
    check_version()
    check_test_count()
    check_paths()
    check_line_counts()
    check_commands()
    check_release_claims()

    if problems:
        print(f"文档一致性检查失败（{len(problems)} 项）：", file=sys.stderr)
        for item in problems:
            print(f"  - {item}", file=sys.stderr)
        return 1

    print("文档一致性检查通过。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
