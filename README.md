# 小肥鱼控制台 · DSH Console

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![check](https://github.com/berserkross/dsh-little-fat-fish-console/actions/workflows/check.yml/badge.svg)](https://github.com/berserkross/dsh-little-fat-fish-console/actions/workflows/check.yml)

DeepSeek Harness 的桌面图形界面（customtkinter · 蓝鲸主题）。双击 exe 或运行脚本即可打开窗口，
用来在本机启动 / 停止 DSH Web 服务、把服务临时开给手机访问、以及随时看状态。

> **当前版本 2.2.6**（2026-11-07）：根治「假活」闭环——端口转发残留不再让启动按钮误判，停止 DSH 后
> 自动清理转发残留，启动/重启守卫不再撞 EADDRINUSE，进程判定收紧为「读不到就报未知」。
> 2.2.5（2026-11-04）：v2 四个批次全部落地——可移植配置层、结构化探测与五态状态机、
> 托盘常驻 / 日志跟随 / 脱敏诊断包 / 串行命令队列、可发布构建（PE 版本信息 + PyInstaller onefile），
> 界面重排（画出来的玻璃 + ico 头像 + 按行日志 + 三组对齐的功能网格 + ⋯ 抽屉与浮层），
> 以及手机访问的候选/策略层（Tailscale serve 优先、回环地址整条剔除）。
> 2.2.1 起窗口可以缩到最小尺寸：内容整体纵向滚动，底栏不再被裁掉。
> 2.2.2 修好了「重启 DSH 只关闭、不重启」，并加上「免 token 直连」：手机打开 `http://<tailnet-ip>:3081` 就能拿到会话。
> 发布产物**不附带 exe**（原样源码与构建命令见 `docs\build-and-signing.md`）。自己构建出的 exe 未签名时，
> 首次运行 Windows 会弹 SmartScreen「未知发布者」，点「更多信息 → 仍要运行」即可；只想本机消除这条提示，
> 可用 `scripts\sign-self-signed.ps1` 自签名 —— 那对本机有效、对别人的机器无效，见 `docs\self-signed-local.md`。

## 功能

- ▶ 启动 DeepSeek Harness
- ⏹ 停止 DeepSeek Harness
- 开启手机访问（回环 + 端口转发 + 信任来源）
- 恢复本机（仅回环）
- 复制手机地址
- 生成二维码（点「手机访问」弹浮层显示，关闭即清除，**不落盘**）
- 实时查看服务状态与日志（异常带 traceback，令牌自动打码）
- 接管「已经跑着、但不是记录里那份安装」的 DSH 实例
- 单实例：重复启动只把已有窗口拉到前台，不会开出第二个窗口（收在托盘里也会先显示再聚焦）
- 托盘常驻：关闭按钮收进托盘，菜单可显示/隐藏、复制地址、停止 DSH、退出；「关闭窗口时收进托盘 / 直接退出」在应用内「⋯」抽屉里切换
- 日志跟随真机输出：直接 tail `dsh-web.stdout.log` / `dsh-web.stderr.log`，只追加新内容，上限 2000 行
- 脱敏诊断包：一键导出 zip（元信息 / 探测明细 / 日志尾部 / 系统与网络原始输出），整包打码
- 访问地址下拉：本机 / Tailscale / 每个局域网 IP 都标出来源，端口可改，支持 IPv6

## 界面

一屏三块：顶部 120px 状态环，中间一颗主按钮，下面默认只显示末尾 15 行的运行日志（「展开全屏」开独立日志窗口，
跟随、打码、截断自愈和主界面共用同一份 `logtail` 输出）。环内写状态词与 PID，环外右侧一行放手机访问结论与
Tailscale / 局域网地址。

| 状态 | 环 | 主按钮 |
|---|---|---|
| 未运行 | 灰 | 启动 DSH |
| 启动中 | 青色，弧长在走 | 停止 DSH |
| 运行中 | 绿 | 停止 DSH |
| 异常（端口被占用） | 橙 | 修复/重启 |
| 未知 | 暗灰 | 重新探测 |

每一态除了颜色还有文字（环内短词 + 右侧完整说明），不靠颜色单独区分。其余操作——重启、切换 Web 端口、
手机访问二维码、复制地址、两个 UAC 开关、导出诊断包、日志跟随、关闭行为、退出——都收进右上角「⋯」抽屉；
二维码不再常驻，点「手机访问」弹模态浮层（地址下拉 + 二维码 + 复制按钮，Esc 或点浮层外面关闭）。

配色与尺寸常量在 `dshconsole/ui_theme.py`，状态环、抽屉、两个浮层在 `dshconsole/widgets.py`。

## 手机访问（serve 优先，端到端重做中）

二维码只允许编码**手机真的打得开**的地址。回环地址（`127.0.0.1` / `localhost` / `::1`）永远不进二维码 ——
那是手机自己的回环，扫出来必然打不开，这正是旧版本二维码扫不开的根因。

候选地址按这个顺序给出（`dshconsole/addresses.py` 的 `mobile_candidates()`）：

| 顺位 | 层级 | 形态 | 说明 |
|---|---|---|---|
| 1 | `serve` | `http(s)://<machine>.<tailnet>.ts.net/` | `tailscale serve` 代理到 `127.0.0.1:<port>`；不需要管理员权限、不需要端口转发、不需要动防火墙 |
| 2 | `tailscale` | `http://100.x.y.z:<port>/?token=…` | 回退路径：netsh 端口转发 + 本机 DSH 监听回环 |
| 3 | `lan` | `http://10.x / 192.168.x:<port>/?token=…` | 同一 Wi-Fi 下的局域网地址；校园网常开设备隔离，未必通 |
| 4 | `loopback` | `http://127.0.0.1:<port>/` | **只在界面下拉里出现，不进二维码** |

策略层在 `dshconsole/phone.py`（`plan()` / `detect_plan()`）：先试 serve，认证状态、MagicDNS 关闭或
`tailscale serve` 装不上都会带着结构化原因自动回退到端口转发，并把「用户该做的下一步」写进结果。
事实层在 `dshconsole/tailscale.py`：只解析 `tailscale status --json` / `tailscale serve status --json`，
import 时**不执行任何命令**，所有 IO 都能注入假的 spawn 单测。

### 手机要满足什么才能打开

1. 手机装了 Tailscale，并登录**同一个 tailnet**（serve 出来的地址只在 tailnet 内可见，不是公网）。
2. 手机能解析 `<machine>.<tailnet>.ts.net`（MagicDNS 打开时自动生效）。
3. serve 路径：`tailscale serve status` 能看到指向 `127.0.0.1:<port>` 的代理。
4. 回退路径：Windows 防火墙放行 node.exe 的 TCP 端口，且 `netsh interface portproxy` 里有对应网卡。
   **注意**：Win10/11 会把校园网 Wi-Fi 判成「公用」，老版本只放行 Private,Domain 的规则因此整条静默失效；
   现在切换器新建规则用 `-Profile Any`，已存在的规则也会 `Set-NetFirewallRule -Profile Any` 补上。
5. 二维码里的 `token` 首次打开就会被写进 Cookie，之后刷新不再需要。

serve 是常驻配置，拆除用：

```powershell
tailscale serve reset
```

> 目前 MagicDNS 域名的 HTTPS 证书需要 Tailscale 管理台开通（`DNS` 页 → `HTTPS Certificates`）。
> 没开通时 `tailscale cert` 返回 500，serve 会降级成 `http://<domain>/` —— 仍然可用（tailnet 内本来
> 就是加密的 WireGuard），只是没有浏览器级的 TLS。

## 环境要求

| 项 | 版本 |
|---|---|
| Windows | 10 / 11 |
| Python | 3.11 及以上（开发与打包环境实测 3.11.9） |
| 运行依赖 | `customtkinter`、`pillow`、`qrcode`、`pystray`（见 `requirements.txt`；托盘不可用会自动降级） |
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
抢不到就把已有的「小肥鱼控制台」窗口切到前台，然后以退出码 0 结束（不会再弹出第二个主窗口）。
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
py -3.11 -m pip install "pyinstaller>=6,<7"
py -3.11 -m PyInstaller --noconfirm DSHConsole.spec
```

产物是 **onefile** 的 `dist\DSHConsole.exe`（2.2.6 实测 32,251,168 B，签名后 32,258,304 B）。
PE 版本资源由 `version_info.txt` 提供，资源管理器「属性 → 详细信息」能看到 `FileVersion 2.2.6.0`、
`ProductName 小肥鱼控制台`、`CompanyName berserkross`。
本机实测：Python 3.11.9 + PyInstaller 6.22.3，干净构建约 21 秒。

验证产物（exe 是 GUI 子系统，控制台看不到它的 `print`，所以用 `Start-Process` 拿退出码）：

```powershell
(Get-Item dist\DSHConsole.exe).VersionInfo | Format-List FileVersion, ProductVersion, CompanyName
$p = Start-Process dist\DSHConsole.exe -ArgumentList '--selftest' -Wait -PassThru; $p.ExitCode
```

`build\`、`dist\` 与 `*.exe` 已在 `.gitignore` 里，产物不入库。签名方案（有证书 / 自签名 / 不签）
见 `docs\build-and-signing.md`。

## 目录结构

```
dsh_gui.py                       主程序（GUI + 状态机 + 大环 / 单主按钮 / 抽屉 / 浮层 + 采纳运行中实例）
dshconsole/ui_theme.py           配色、尺寸与五态视觉常量（UI 唯一调色板）
dshconsole/widgets.py            自绘控件：状态环、⋯ 抽屉、二维码浮层、全屏日志浮层
dshconsole/config.py             探测与 config.json 读写（只依赖标准库，可无 GUI 导入）
dshconsole/status.py             五态判定：未运行 / 启动中 / 运行中 / 异常（端口被占用）/ 未知
dshconsole/probe.py              进程、端口、portproxy、防火墙、Tailscale、局域网地址探测
dshconsole/psrun.py              结构化 PowerShell 调用（超时 / 权限 / 未安装分开表达）
dshconsole/adopt.py              从「别的安装」的 bin.js 反推 harness 并写回 config.json
dshconsole/single.py             单实例互斥体 + 唤起已有窗口（ctypes 命名事件，无 pywin32）
dshconsole/errors.py             traceback 脱敏摘要 + excepthook 安装
dshconsole/textutil.py           日志打码：redact() 打 token，redact_text() 管全部密钥
dshconsole/logtail.py            按字节偏移跟随 stdout / stderr 日志（截断重同步、行数上限、逐行打码）
dshconsole/tasks.py              串行命令队列（排队中 / 执行中 / 成功 / 失败 / 已取消）
dshconsole/snapshot.py           状态短 TTL 缓存，「手动刷新」强制穿透
dshconsole/addresses.py          访问地址候选（本机 / Tailscale / 局域网，带来源标注与端口校验）
dshconsole/diagnostics.py        脱敏诊断包（meta.json / probe.txt / log-tail.txt / windows.txt）
dshconsole/tray.py               系统托盘（pystray 可选，失败自动降级成普通窗口）
dshconsole/resources.py          资源定位：源码运行取包目录，PyInstaller 冻结取 sys._MEIPASS
dshconsole/data/launch-dsh.ps1   启动器（参数化，随包发布）
dshconsole/data/switch-dsh-web.ps1  手机访问切换器（参数化，随包发布）
tests/                           config / probe / psrun / status / redact / errors / single / adopt /
                                 logtail / tasks / snapshot / addresses / diagnostics / tray / GUI hooks
requirements.txt                 运行依赖
DSHConsole.spec                  PyInstaller 打包描述（onefile、console=False、version=）
version_info.txt                 PE 版本资源的唯一源头（版本号只在这里定义）
DeepSeekChan [256x256].ico       窗口与 exe 图标
docs/build-and-signing.md        实测构建记录、版本信息与签名方案
.github/workflows/check.yml      CI：依赖安装 + 语法检查 + 单元测试
LICENSE                          MIT 许可证
SECURITY.md                      漏洞上报方式与预期行为
CHANGELOG.md                     版本变更记录
```

## 测试

```powershell
python -m unittest discover -s tests -v
python dsh_gui.py --selftest        # 主窗口 + 大环 / 主按钮 / 抽屉 / 浮层 / 日志折叠的自检
python dsh_gui.py --stop-selftest   # 「停止」整条链路（假进程 + 注入端口探测）
```

共 392 个用例。测试只用标准库，用 `tempfile` 造假目录树，不依赖本机任何真实安装路径；两个自检
同样把进程与端口探测全部注入（不碰真实 DSH 进程、也不要求 3080 空闲），所以在 CI 上可跑。
GUI 用例需要 `customtkinter` / `pillow` / `qrcode`，没装时会跳过；托盘用例用假 pystray，
不需要真的托盘环境。

## 版本进度

v1 的硬编码已在 v2「批次 A（可移植性）」修掉：

| v1 问题 | 现状 |
|---|---|
| `HARNESS` 硬编码为作者机器路径 | 改为启动时探测 + `config.json` + 首次运行询问（`dshconsole/config.py`） |
| 依赖 Harness 目录下两份外部 ps1 | 脚本移入本仓库 `dshconsole/data/`，随包发布；`resources.py` 负责定位 |
| 端口 3080 / 令牌日志路径写死 | 端口来自 `--port` / `config.json`（默认 3080），令牌日志由 harness 目录推导 |
| `qrcode` 未列入依赖 | 已进 `requirements.txt` |
| spec 里 `name='DSHConsole'` 与实物不一致 | 已统一为 `DSHConsole`（ASCII 文件名，免去命令行与 CI 的引号/代码页问题），显式 `upx=False` |

批次 C（体验层）也已完成：托盘常驻、日志跟随、脱敏诊断包、地址下拉、命令队列，以及把一次状态
刷新从 14.4 秒压到 2.1 秒（一次 PowerShell 调用替代七次独立 spawn）。

批次 E（可发布构建）已完成：`version_info.txt` 给产物加上 PE 版本资源（`FileVersion 2.0.0.0`、
`ProductName DSH 控制台（小肥鱼控制台）`、`CompanyName berserkross`、MIT 版权与仓库地址），
spec 补 `version='version_info.txt'` 并把产物名统一为 `DSHConsole.exe`；冻结态两条自检
（`--selftest` / `--stop-selftest`）退出码均为 0，`.rsrc` 由 71,912 B 增至 72,896 B。

仍未做：**产物未签名** —— 本机没有代码签名证书（`Cert:\CurrentUser\My -CodeSigningCert` 为空），
所以别人第一次运行会看到 SmartScreen「未知发布者」；签名路径见 `docs\build-and-signing.md`。
批次 D（视觉重排，方案 1「大环 + 抽屉」）已完成：状态从四行文字变成一颗 120px 状态环，八个按钮收成一颗主按钮
加一个「⋯」抽屉，常驻二维码改成「手机访问」模态浮层，日志默认只留末尾 15 行、需要时展开成独立窗口。
功能面没有削减：托盘、单实例、诊断包、地址选择器、队列、日志跟随、采纳运行中实例全部照旧可用。

## 安全提示

本程序会读取 DSH 启动日志以提取带 token 的访问地址。**该日志与地址绝不可提交进仓库**（见 `.gitignore`）。

## 商标

图标与配色取自 DeepSeek 品牌视觉，仅作本机自用；对外分发请自行替换并遵守相应商标政策。

## 安全

本程序会改 portproxy 规则、启停 DSH 进程、并从日志里读带 token 的访问地址（只在内存里用，不落盘）。
发现异常行为请按 [SECURITY.md](SECURITY.md) 私密上报，不要开公开 issue。

## 许可证

[MIT](LICENSE) © 2026 YANG TIANRUI (berserkross)
