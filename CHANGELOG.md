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
