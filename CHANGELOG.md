# 变更记录

格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，版本号遵循 [SemVer](https://semver.org/lang/zh-CN/)。

## [Unreleased]

v2 批次 A：可移植性 —— 从「只有作者机器能跑」改成「clone → 装依赖 → 全部按钮可用」。

### 新增

- `dshconsole/` 包：`config.py` 负责探测 harness / node / bin.js / DSH_HOME / 端口 / 浏览器 / Tailscale，
  并读写 `%APPDATA%\dsh-console\config.json`；`resources.py` 统一资源定位（源码运行 vs PyInstaller 冻结）。
- `--harness` / `--port` 参数，`DSH_CONSOLE_CONFIG` 环境变量可整体改配置位置。
- `requirements.txt`（customtkinter / pillow / qrcode），CI 增加单元测试步骤。
- `tests/test_config.py`：探索顺序、config.json 往返、失效路径重探测、探测失败返回 None。

### 变更

- 启动器与手机访问切换器从 `reference/` 移入 `dshconsole/data/` 并随包发布；两个脚本改成 `param()`
  参数化（`-Harness/-NodeExe/-BinJs/-DshHome/-Port/-Chrome/-RuleName`），自提权分支把值参数一并透传。
- `dsh_gui.py` 不再硬编码路径与端口，改为从 `dshconsole.config` 取值；探测失败时弹目录选择而不是直接崩。
- `DSHConsole.spec`：`name` 统一为 `DSH 控制台`，`upx=False`，`datas` 带上 `dshconsole/data/*.ps1` 与图标，
  `hiddenimports` 补 `qrcode` / `PIL`。

### 修复

- 别人 clone 下来后 6/8 个按钮因找不到 ps1 与 harness 而失效。
- `qrcode` 未列入依赖导致二维码按钮报 ModuleNotFoundError。
- `--harness` / `--port` 此前只写在文档里、没有代码解析，用户传了也被静默忽略；现已在
  `dshconsole.config.parse_cli()` 实现，非法参数明确报错并以退出码 2 退出。
- `launch-dsh.ps1` 在 node 为空时 `Test-Path -LiteralPath ''` 触发参数绑定异常，使「PATH 里的 node」
  与 codex runtime 两级回退变成死代码；改为 `if (-not $node -or -not (Test-Path ...))`。
- 两个 ps1 的 `Split-Path -Parent $PSScriptRoot` 回退在移动后指向 `dshconsole/` 而非 harness；
  改为 DSH_HOME 父目录优先，仍取不到则明确报错并 `exit 1`。

v2 批次 B1：正确性核心 —— 「查不到」不再冒充「未运行」，进程识别不再误杀，日志不再泄露令牌。

### 新增

- `dshconsole/psrun.py`：结构化 PowerShell 调用，`PsResult(ok, code, stdout, stderr, error)` 把超时 /
  找不到 powershell / 启动失败与「命令正常但退出码非零」分开表达，并提供 `.why()` 人话说明。
- `dshconsole/probe.py`：进程、端口转发、防火墙、Tailscale、局域网地址的探测层，每个函数返回
  「结果 + 错误原因」，查不到时给 `None` 而不是 `False`；`netsh portproxy` 走表格解析，
  防火墙规则区分「没有规则」与「查不出来」。
- `dshconsole/status.py`：`Phase`（未运行 / 启动中 / 运行中 / 异常（端口被占用）/ 未知）与
  `probe_status()`，一次探测产出界面要的全部状态与 `notes` 说明。
- `dshconsole/textutil.py`：`redact()` 把 `token=<值>` 与 `?token=<值>` 的令牌部分打码。
- `tests/`：新增 `test_psrun.py` / `test_probe.py` / `test_status.py` / `test_redact.py`，
  覆盖超时分支、转发表格解析、五态判定与日志打码（84 个用例，Python 3.11 / 3.14 双解释器通过）。

### 变更

- 状态栏改为按五态渲染，未知项显示「未知（原因见日志）」并在日志框留一行「未知：…」，不再伪装成未运行。
- 「停止」不再看到就杀：先列出将要结束的 PID 与对应的 `bin.js` 路径，确认后才动手；PID 查不到时不动手。
- 进程识别改为「`node.exe` 且命令行里的绝对路径与本机 `bin.js` 一致」，不再按 `bin.js web` 的形态匹配。
- 「手机访问」改为「端口转发确实指向本机端口 + 防火墙规则存在」才算开启，转发到别处会明确提示。

### 修复

- PowerShell 超时、被策略拦截或权限不足时，界面把「查不到」显示成「未运行 / 未开启」；现在显示「未知」并给出原因。
- 同形态的其他 `node bin.js web` 进程会被误认成 DSH，点「停止」即被结束。
- 「复制手机地址」把带令牌的完整地址打进日志框，屏幕共享或截图即泄露；日志现在打码，剪贴板仍是完整地址。
- `requirements.txt` 的中文注释在中文 Windows + Python 3.11 上让 `pip install -r` 直接抛 `UnicodeDecodeError`（pip 无 BOM 时按 locale 解码）；注释改为 ASCII，文件保持无 BOM。
v2 批次 B2：接管与可观测性 —— 正在跑的实例能被接管，异常不再静默，单实例与自检可被 CI 自动验证。

### 新增

- `dshconsole/adopt.py`：把「占用端口但不是我这份 bin.js」的候选反推成 harness（从
  `node_modules\@deepseek-ai\dsh\lib\bin.js` 往上剥 `config.BIN_JS_REL` 的层数，再用 `looks_like_harness` 校验），
  写回 `config.json` 并标记 `"source": "adopted"`；推不出目录时拒绝写入，提示改用 `--harness`。
- `dshconsole/errors.py`：`summarize()` 把 traceback 截到 12 帧 / 2000 字符并过一遍 `textutil.redact()`，
  `install()` 同时接管 `sys.excepthook` 与 `threading.excepthook`（后者头部带线程名）。
- `dshconsole/single.py`：Windows 命名互斥体 `Local\DshConsole.SingleInstance`（`CreateMutexW` +
  `ERROR_ALREADY_EXISTS`），第二个进程把已有窗口 `SetForegroundWindow` 后以退出码 0 结束；非 Windows
  或 ctypes 不可用只记一行日志、不阻止启动。
- 界面：状态为 DEGRADED 且存在占用候选时出现「改为控制运行中的实例（PID …）」按钮；多个候选弹输入框
  让用户选序号，不默认第一个；采纳成功后按钮立刻收起并立刻重新探测。
- 测试：`tests/test_errors.py` / `test_single.py` / `test_adopt.py` / `test_gui_hooks.py`（全量 124 个用例）。

### 变更

- 探测口全部改为实例级可注入：`_pids_provider` / `_status_provider` / `_port_open`；两个 `--*-selftest`
  不再猴补丁 `globals()`，也不再依赖本机真实 DSH 进程与 3080 端口。
- `Tk.report_callback_exception` 改为 `_on_callback_error`：脱敏 traceback 写进日志框并立即释放 `_busy`。
- 后台线程往界面投递（`after`）在窗口已销毁时退回 stderr，不再让工作线程抛
  `RuntimeError: main thread is not in main loop`。
- `config.json` 增加 `source` 字段，只交代配置来龙去脉，不参与探测优先级。
- CI：`py_compile` 覆盖 `dshconsole` 全部模块，新增 `--selftest` 与 `--stop-selftest` 两个 GUI 自检步骤。
- `switch-dsh-web.ps1:162` 的启动提示不再出现 `bin.js web` 字面量，免得和「按命令行识别进程」的口径混淆。

### 修复

- 本机实际在跑的是 npx 缓存里那份安装时，状态显示「异常（端口被占用）」且「停止 / 重启」对真正在跑的
  实例完全无效（B1 收紧进程识别带来的日常使用回归）；现在可以一键采纳并立刻转为「运行中」。
- 后台线程异常与界面回调异常此前只打到 stderr（打包成 exe 后完全看不见），界面还会停在「进行中」；
  现在进日志框、令牌打码、`_busy` 必定释放。
- `--stop-selftest` 之前用 `update()` 手泵事件循环，工作线程 `after()` 抛 `RuntimeError` 导致自检假失败；
  改为真实 `mainloop()` + 轮询等待。

## [1.0.0] - 2026-11-03

首个公开快照：把本机自用的控制台原样开源，作为后续迭代的基线。

### 新增

- 启动 / 停止 DeepSeek Harness
- 开启手机访问（回环 + portforward + 信任来源）与「恢复本机」
- 复制手机地址、窗口内生成二维码（不落盘）
- 实时查看服务状态与日志

### 已知问题

- `dsh_gui.py:22` 的 `HARNESS` 路径硬编码，换机器即失效
- 产物缺 FileVersion / ProductName（spec 缺 `version=`），且未签名
- 端口 3080 与 token 日志路径同样硬编码
