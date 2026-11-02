# 小肥鱼控制台 · DSH Console

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![check](https://github.com/berserkross/dsh-little-fat-fish-console/actions/workflows/check.yml/badge.svg)](https://github.com/berserkross/dsh-little-fat-fish-console/actions/workflows/check.yml)

DeepSeek Harness 的桌面图形界面（customtkinter · 蓝鲸主题）。双击 exe 或运行脚本即可打开窗口，
用来在本机启动 / 停止 DSH Web 服务、把服务临时开给手机访问、以及随时看状态。

> **当前版本 2.1.0**（2026-11-03）：v2 四个批次全部落地——可移植配置层、结构化探测与五态状态机、
> 托盘常驻 / 日志跟随 / 脱敏诊断包 / 串行命令队列、可发布构建（PE 版本信息 + PyInstaller onefile），
> 以及界面重排（状态大环 + 单主按钮 + ⋯ 抽屉 + 浮层）。
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

一屏一条信息流，从上到下五段：头部条（ico 头像 64px 圆形遮罩徽章 + 标题 + 发光状态灯 + 状态词 + 等宽 PID/端口
+ 手机访问结论）→ 主操作行（一颗通栏主按钮，左右撑满、高 46px，异常时右侧固定槽位出现「改为控制运行中的实例」
条件按钮，不跳位）→ 功能网格（三组 15 项操作全部平铺，没有抽屉、没有折叠）→ 常驻运行日志（高度固定 = clamp(实际行数, 6, 26) 行、不吸收剩余高度，空态 12 行，
不超出剩余空间，「展开全屏」开独立日志窗口；日志为空时显示鲸鱼娘插画 + 一句提示）→ 页脚（本机地址 + 关闭行为提示）。

整窗是「画出来的玻璃」，不是真的半透明：窗口不透明度 **1.0**（没有残留的整窗 alpha），玻璃三件套全部由 Pillow 烘成
一张整窗底图铺在 Canvas 上 —— ①整窗竖向深色渐变（顶 `(26,40,74)` → 中 `(14,22,44)` → 底 `(5,8,18)`）+ 极淡
网格/星点；②卡面按 `CARD` 合成到 0.94 等效不透明度（`CARD_FILL_ALPHA=240/255`），文字面板背后不会有任何桌面
像素；③`GLASS_EDGE` 1px 亮边 + 上沿内高光 + 卡片下方 6px 偏移的柔影。真实控件叠在底图上，面板底色取渲染图里的
取样色，控件与底图之间没有色缝。透明度只出现在装饰层（描边高光、柔影），桌面字形进不到任何承载文字的面板内部：
把一张白底黑字窗口垫在主窗口正后方截图，卡面 / 日志区 / 状态行内部与垫后窗口无关（`tests/verify_shots.py` 的 A1
用「白底垫后 vs 黑底垫后」逐像素比对来守这条）。窗口尺寸变化时重绘走 after 防抖，不闪、不丢焦点。

| 状态 | 状态灯 | 主按钮 |
|---|---|---|
| 未运行 | 灰实心 | 启动 DSH |
| 启动中 | 青色弧在走 | 停止 DSH |
| 运行中 | 绿实心 | 停止 DSH |
| 异常（端口被占用） | 橙实心 | 修复/重启 |
| 未知 | 暗灰空心 | 重新探测 |

每一态除了颜色还有文字（状态词 + PID/端口），不靠颜色单独区分。功能网格按语义分三组：

| 分组 | 操作 |
|---|---|
| 服务 | 重启 DSH、刷新状态、切换 Web 端口… |
| 手机访问 | 手机访问二维码、复制手机访问地址、复制本机地址、开启手机访问（UAC）、恢复本机模式（UAC） |
| 工具 | 导出诊断包、暂停日志跟随、关闭窗口时：收进托盘、取消排队、退出程序 |

启停只留一颗：主按钮通栏承担「启动 / 停止 / 修复重启」，位置永远固定；「服务」组不再重复放启动/停止，
只负责重启、刷新与换端口 —— 两颗都叫「启动 DSH」时用户会犹豫该点哪颗。

列数随窗口宽度自适应：逻辑宽度 ≥660 三列（三张组卡），≥480 两列，更窄一列；组卡内部固定排 2 列（窄到 250 逻辑
像素以下退回 1 列）。三张组卡共用同一套列宽（holder 上 `columnconfigure(weight=1, uniform="grp")`），组内行用
`uniform="chiprow"`，所以**同一组同一列的 chip 的 x0/x1 完全一致、三组 chip 高度也一致**；某组末行只剩一项时它
通栏（`columnspan=2`，宽度 = 该组整行可用宽），手机访问组 5 项排成 2+2+1。测量表与生成脚本见
`tests/measure_chips.py`（输出 %TEMP%\ui_v4\chip-grid-3col.md 与 chip-grid-2col.md）。每颗按钮带图标、底色比面板
亮一档（看得出是按钮而不是输入框）、圆角 11、高 36、悬停变亮，文案全部整行显示，不靠悬停或提示补全。
两个开关项的文案随状态翻转（暂停/恢复日志跟随、关闭时收进托盘/退出程序）。手机访问二维码点开仍是模态浮层
（地址下拉 + 二维码 + 复制按钮，Esc 或点浮层外面关闭），浮层本批次只换了配色，下一批次由手机访问模块接手改造。
头部徽章与空态插画用的是仓库根的 `DeepSeekChan [256x256].ico`（单帧 256×256 RGBA）：`widgets.avatar()` 先裁
`(24,18)-(248,242)`、LANCZOS 放大到 4 倍超采样，再套圆形遮罩（圆心 `(136,130)`、半径 `112`）缩回目标尺寸 ——
源图是出血裁切（alpha bbox=(17,2,256,256)，右/下边缘有不透明像素），直接贴方形会露硬切口。逻辑尺寸 64px
（150% DPI 下 96 设备像素），头部条高 88px，图标上下各留 12 逻辑像素，圆完整不成缺口。窗口图标改成 **ico 优先**
（`iconbitmap`），`mascot_logo@32.png` 只作回退。
配色与尺寸常量在 `dshconsole/ui_theme.py`（含 `contrast_ratio`，正文类对比度 ≥ 4.5:1 由测试守住），
状态灯、玻璃底图、两个浮层在 `dshconsole/widgets.py`。

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
py -3.11 -m pip install "pyinstaller>=6,<7"
py -3.11 -m PyInstaller --noconfirm DSHConsole.spec
```

产物是 **onefile** 的 `dist\DSHConsole.exe`（2.1.0 实测 32,172,230 B，签名后 32,179,368 B）。
PE 版本资源由 `version_info.txt` 提供，资源管理器「属性 → 详细信息」能看到 `FileVersion 2.1.0.0`、
`ProductName DSH 控制台（小肥鱼控制台）`、`CompanyName berserkross`。
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
python dsh_gui.py --selftest        # 主窗口 + 状态灯 / 主按钮 / 功能网格 / 浮层 / 日志折叠的自检
python dsh_gui.py --stop-selftest   # 「停止」整条链路（假进程 + 注入端口探测）
python tests/shoot_ui.py            # 抓全部状态截图到 %TEMP%\ui_v4\（只开自己这份代码的窗口，绝不碰真实进程）
python tests/verify_shots.py        # 截图自检：玻璃三件套 / 白底垫后逐像素一致 / 无蓝带 / 日志行高
python tests/measure_chips.py       # 按钮网格测量表（3 列与 2 列两种，输出 chip-grid-*.md）
```

共 243 个用例。测试只用标准库，用 `tempfile` 造假目录树，不依赖本机任何真实安装路径；两个自检
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
