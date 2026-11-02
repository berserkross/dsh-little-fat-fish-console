# 小肥鱼控制台 · DSH Console

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![check](https://github.com/berserkross/dsh-little-fat-fish-console/actions/workflows/check.yml/badge.svg)](https://github.com/berserkross/dsh-little-fat-fish-console/actions/workflows/check.yml)

DeepSeek Harness 的桌面图形界面（customtkinter · 蓝鲸主题）。双击 exe 或运行脚本即可打开窗口，
用来在本机启动 / 停止 DSH Web 服务、把服务临时开给手机访问、以及随时看状态。

> v1 存档版：这是**第一版源码的忠实快照**，上传目的是建立可迭代的基线。
> 已知的硬编码与待办都列在「v1 已知问题」里，进入 v2 时逐项处理。

## 功能

- ▶ 启动 DeepSeek Harness
- ⏹ 停止 DeepSeek Harness
- 开启手机访问（回环 + 端口转发 + 信任来源）
- 恢复本机（仅回环）
- 复制手机地址
- 生成二维码（窗口内显示，刷新 / 关闭即清除，**不落盘**）
- 实时查看服务状态与日志（异常带 traceback，令牌自动打码）
- 接管「已经跑着、但不是记录里那份安装」的 DSH 实例
- 单实例：重复启动只把已有窗口拉到前台，不会开出第二个窗口

## 环境要求

| 项 | 版本 |
|---|---|
| Windows | 10 / 11 |
| Python | 3.11 及以上（开发与打包环境实测 3.11.9） |
| 运行依赖 | `customtkinter`、`pillow`、`qrcode`（见 `requirements.txt`） |
| 打包 | `pyinstaller >= 6, < 7` |
| 本机已装 | DeepSeek Harness（`node_modules\@deepseek-ai\dsh`）+ Node.js |

本仓库自带启动脚本与开关脚本（`dshconsole/data/*.ps1`），**不需要**把它们复制到
DeepSeek Harness 目录里，也不需要把本程序放进 Harness 目录才能跑 —— 位置随意。

## 运行

```powershell
python -m pip install -r requirements.txt
python .\dsh_gui.py
```

### 首次运行会问你 DSH 装在哪

程序启动时自己找 DeepSeek Harness（依次尝试：`--harness` 参数 → `config.json` 里的记录 →
`DSH_HOME` 的父目录 → `where dsh` 反推 → 常见安装位 → 从当前目录向上找）。找不到时**不会崩**，
而是弹一个目录选择框：手动选中 Harness 安装目录（里面应有 `node_modules\@deepseek-ai\dsh`），
选择结果会记到 `%APPDATA%\dsh-console\config.json`，下次不再询问；点取消则提示原因并退出。

也可以手工指定：

```powershell
python .\dsh_gui.py --harness "D:\apps\deepseek-harness" --port 3080
python .\dsh_gui.py --harness="D:\apps\deepseek-harness" --port=3080   # 等号写法同样支持
```

`--harness` / `--port` **只影响本次运行**，不写入 `config.json`；参数写错（缺值、端口不是
1-65535 的整数、用了不认识的参数）会打印用法并以退出码 2 结束，不会静默忽略。想让程序长期
记住，用上面的目录选择框，或直接编辑 `config.json`。

`config.json` 里记录 `harness / node / bin_js / dsh_home / port / chrome / tailscale`；
任何一条路径失效（目录被删、换了机器）都会被丢弃并重新探测。想换配置位置可设
`DSH_CONSOLE_CONFIG` 环境变量指向另一个 json 文件。

### 多实例与「采纳运行中的实例」

同一个窗口只允许开一个：程序启动时先抢 Windows 命名互斥体 `Local\DshConsole.SingleInstance`，
抢不到就把已有的「DSH 控制台」窗口切到前台，然后以退出码 0 结束（不会再弹出第二个主窗口）。
非 Windows 或系统调用不可用时这层检查自动跳过，只在日志里留一行，不影响启动。

另一件事是「跑着的 DSH 不是记录里那份」。当端口被监听、却找不到本机 `bin.js` 对应的 `node` 进程时，
状态显示为「异常（端口被占用）」，并在日志里列出占用端口的可能是另一处安装的 DSH（PID + 路径）。
这时状态行下方会出现一个按钮：

```text
改为控制运行中的实例（PID 9856）
```

点它会从那个进程的 `bin.js` 反推 harness 目录（`...\node_modules\@deepseek-ai\dsh\lib\bin.js` 往上剥
`node_modules\@deepseek-ai\dsh\lib\bin.js` 这四层），写进 `config.json` 并标注 `"source": "adopted"`，
随后立刻重新探测：状态应变成「运行中」，「停止 / 重启」也随之作用于这个实例。
有多个候选进程时会弹输入框让你选序号（不默认第一个）；路径推不出 harness 时不会瞎猜，
而是提示用 `--harness` 指定或手工编辑 `config.json`。

命令行不直接提供「采纳」开关，因为它需要看当前真实进程：想固定目标就照旧 `--harness`，
注意 `--harness` 只影响本次运行，不会写入 `config.json`。

## 打包

```powershell
python -m pip install "pyinstaller>=6,<7"
pyinstaller --clean --noconfirm DSHConsole.spec
```

产物在 `dist\` 下。架构细节见 `docs\build-and-signing.md`。

## 目录结构

```
dsh_gui.py                       主程序（GUI + 状态机 + 二维码 + 采纳运行中实例）
dshconsole/config.py             探测与 config.json 读写（只依赖标准库，可无 GUI 导入）
dshconsole/status.py             五态判定：未运行 / 启动中 / 运行中 / 异常（端口被占用）/ 未知
dshconsole/probe.py              进程、端口、portproxy、防火墙、Tailscale、局域网地址探测
dshconsole/psrun.py              结构化 PowerShell 调用（超时 / 权限 / 未安装分开表达）
dshconsole/adopt.py              从「别的安装」的 bin.js 反推 harness 并写回 config.json
dshconsole/single.py             单实例互斥体 + 把已有窗口切到前台（ctypes，无 pywin32）
dshconsole/errors.py             traceback 脱敏摘要 + excepthook 安装
dshconsole/textutil.py           日志里的令牌打码
dshconsole/resources.py          资源定位：源码运行取包目录，PyInstaller 冻结取 sys._MEIPASS
dshconsole/data/launch-dsh.ps1   启动器（参数化，随包发布）
dshconsole/data/switch-dsh-web.ps1  手机访问切换器（参数化，随包发布）
tests/                           config / probe / psrun / status / redact / errors / single / adopt / GUI hooks
requirements.txt                 运行依赖
DSHConsole.spec                  PyInstaller 打包描述
DeepSeekChan [256x256].ico       窗口与 exe 图标
docs/build-and-signing.md        构建、加版本信息、签名交接单
.github/workflows/check.yml      CI：依赖安装 + 语法检查 + 单元测试
LICENSE                          MIT 许可证
SECURITY.md                      漏洞上报方式与预期行为
CHANGELOG.md                     版本变更记录
```

## 测试

```powershell
python -m unittest discover -s tests -v
python dsh_gui.py --selftest        # 主窗口 + 采纳按钮的自检
python dsh_gui.py --stop-selftest   # 「停止」整条链路（假进程 + 注入端口探测）
```

测试只用标准库，用 `tempfile` 造假目录树，不依赖本机任何真实安装路径；两个自检同样
把进程与端口探测全部注入（不碰真实 DSH 进程、也不要求 3080 空闲），所以在 CI 上可跑。
GUI 用例需要 `customtkinter` / `pillow` / `qrcode`，没装时会跳过。

## 版本进度

v1 的硬编码已在 v2「批次 A（可移植性）」修掉：

| v1 问题 | 现状 |
|---|---|
| `HARNESS` 硬编码为作者机器路径 | 改为启动时探测 + `config.json` + 首次运行询问（`dshconsole/config.py`） |
| 依赖 Harness 目录下两份外部 ps1 | 脚本移入本仓库 `dshconsole/data/`，随包发布；`resources.py` 负责定位 |
| 端口 3080 / 令牌日志路径写死 | 端口来自 `--port` / `config.json`（默认 3080），令牌日志由 harness 目录推导 |
| `qrcode` 未列入依赖 | 已进 `requirements.txt` |
| spec 里 `name='DSHConsole'` 与实物不一致 | 已改为 `DSH 控制台`，并显式 `upx=False` |

仍未做（后续批次）：产物没有 `version=` 版本信息（FileVersion / ProductName）、产物未签名
（SmartScreen 显示「未知发布者」）。

## 安全提示

本程序会读取 DSH 启动日志以提取带 token 的访问地址。**该日志与地址绝不可提交进仓库**（见 `.gitignore`）。

## 商标

图标与配色取自 DeepSeek 品牌视觉，仅作本机自用；对外分发请自行替换并遵守相应商标政策。

## 安全

本程序会改 portproxy 规则、启停 DSH 进程、并从日志里读带 token 的访问地址（只在内存里用，不落盘）。
发现异常行为请按 [SECURITY.md](SECURITY.md) 私密上报，不要开公开 issue。

## 许可证

[MIT](LICENSE) © 2026 YANG TIANRUI (berserkross)
