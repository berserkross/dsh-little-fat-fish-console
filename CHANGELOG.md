# 变更记录

格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，版本号遵循 [SemVer](https://semver.org/lang/zh-CN/)。

## [Unreleased]

v2 批次 F：界面皮肤（轻科幻 + 可爱 + 蓝主色 + 半透明）—— 结构验收后的一层皮，外加复审挑出的五处硬伤。

### 新增

- `widgets.GlassBackdrop`：启动时用 Pillow 合成整窗底图（深蓝径向渐变 + 网格/星点 ≤6% + 各面板的烘焙玻璃：1px 亮边、上沿内高光、外侧柔影），铺在 Canvas 上、真实控件叠在它上面；面板底色取渲染图取样色，控件与底图之间没有色缝。窗口 `<Configure>` 重绘带 after 防抖，不闪、不丢焦点。
- `widgets.art_image`（lru_cache）+ `mascot` / `hero_picture` / `apply_window_icon`：鲸鱼娘素材统一从 `dshconsole/data/art/` 走 `resources.data_file` 加载，缺图、坏图、打包后路径失效一律返回 `None` 并回退到内联矢量鲸鱼，绝不留白块。
- 头部条：鲸鱼娘 52px 圆形玻璃底盘 + 淡蓝发光描边，标题小一号放右侧；状态灯改成发光圆点（运行中绿 / 停止灰 / 异常橙 / 启动中青色走弧），PID 与端口改等宽字体，与状态词分字重分颜色。
- 日志区空态：日志为空时在卡片中央画 `mascot_hero` 插画（缺失用矢量）配一句提示；日志区高度改成按内容自适应、夹在 6~26 行与窗口剩余空间之间。
- 新增测试覆盖：图标唯一、启停只在主按钮、组内 2 列、日志行数随内容、头部与空态尺寸、玻璃 token 全是 RGBA、装饰不透明度 < 6%、alpha 落在实测带内、WCAG 对比度、缺图加载器不抛、矢量回退确实画出像素。`tests/test_ui_theme.py` 16→25、`tests/test_layout.py` 9→12，总数 221→233。

### 变更

- 主按钮改成通栏（`fill="x"`、高 46、悬停泛光），「启动 DSH / 停止 DSH / 修复重启」全部由它承担。
- 15 颗网格按钮改成组内 2 列（组卡窄于 250 逻辑像素退回 1 列），每颗带图标、底色比面板亮一档、圆角 11、高 36、悬停泛光，省下的高度还给日志。
- 三张组卡统一 `columnconfigure(weight=1)` + `sticky="nsew"`，900×900 窄窗不再在「工具」右侧留空洞。
- 整窗 `-alpha` 取 0.96（0.94 / 0.95 / 0.96 / 0.97 逐档实测背景下渗峰值 14 / 12 / 9 / 8 级，0.96 起已辨认不出背后的字形）。

### 修复

- 「服务」组里重复的「启动 DSH / 停止 DSH」删除：两颗都叫启停时用户会犹豫该点哪颗，启停收归主按钮，组内只留重启、刷新、换端口。
- 组内 3 列时按钮文案被截：「关闭窗口时：收进托盘」最后一个字被吃掉，两个 UAC 项少 12px。字号 12→11 并按实测收窄内边距，13 条文案全部整行显示。
- 日志区标题右侧「区域 N 行 · 上限 2000 行」的行数提示在行数未变化时不再被跳过（原先提前 return 把它一起跳掉了）。
- 全屏日志浮层的固定 980×620 会挂到窄窗口外面，改为按主窗口尺寸夹取（最小 320 高）。

v2 批次 E：界面重做（方案 A「无环单列信息流」）—— 用户判定「大环观感极差、主要功能全折叠找不到」，
推翻批次 D 的「大环 + 抽屉」，改成一条从上到下的信息流，15 项操作全部平铺可见。

### 变更

- 顶部：120px 状态环换成 44px 状态条一行放下——状态灯（10px 实心点 / 启动中半弧 / 未知空心）+ 状态词 + `PID x · 端口 3080（在线）` + 手机访问结论。
- 主操作行：主按钮保持一颗，文案与配色随五态变化；异常态在右侧固定槽位出现「改为控制运行中的实例（PID x）」条件按钮，位置不随状态跳动。
- 新增功能网格：按「服务 / 手机访问 / 工具」三组平铺 15 项操作，逻辑宽度 ≥660 三列、≥480 两列、更窄一列自适应；所有按钮文案整行可见，150% DPI 下不撑破。
- 「⋯」抽屉整块删除：`DrawerMenu`、`_drawer_items`、`_open_drawer`、`_place_drawer`、`_on_drawer_closed`、`_drawer` 全部移除，抽屉里的 12 项操作全部前移到网格。
- 「启动 DSH」变成常驻按钮后补上线前守卫：端口已在线时只写一行日志并返回，不会重复拉起第二个实例。
- 日志区从固定行高改成随窗口伸缩的一行：15 行是下限、2000 行截断、打码与跟随链路不变，「展开全屏」仍在。
- `ui_theme`：围绕新骨架重写色板与尺寸（近黑画布、hairline 描边、单一强调蓝），删除 `RING_SIZE` / `RING_THICKNESS` / `DRAWER_WIDTH` / `DRAWER_ROW_HEIGHT`，新增 `STATUS_LAMP` / `STATUS_BAR_H` / `GRID_BTN_H` / `SLOT_W` 与纯函数 `grid_columns(width)`；`WINDOW_SIZE` 收到 700×640 逻辑像素，150% DPI 下 1050×960 物理像素，能在 1600 高的屏幕上完整落地。
- `--selftest` 标记：保留原有字段与顺序，新增 `groups / columns / fit / phone_on / toggle_label`；`fit` 改用 `winfo_rooty` 在同一坐标系里换算（原来拿子控件相对坐标比父窗口坐标，恒判 False）。
- 测试 208 → 221 例：`tests/test_ui_theme.py` 重写（状态灯尺寸、`grid_columns` 断点、环/抽屉常量确实消失、QrOverlay 依赖的 token 仍在），新增 `tests/test_layout.py`（三组 15 项互不重复且全部可调用、手机访问四项在网格里、抽屉已删、启停都在、布局高度预算 ≤900）。

### 移除

- `StatusRing`（107px 大环）与整段抽屉实现；状态灯 `StatusLamp` 接管同一位置。

## [2.1.0] - 2026-11-03

v2 批次 D：视觉重排（方案 1「大环 + 抽屉」）—— 界面从「八颗按钮 + 常驻二维码」改成「一颗环、一颗主按钮、一个抽屉」。

### 新增

- `dshconsole/ui_theme.py`：配色、尺寸与五态视觉常量，UI 的唯一调色板。
- `dshconsole/widgets.py`：`StatusRing`（CTkCanvas 画弧的状态环）、`DrawerMenu`（⋯ 抽屉）、`QrOverlay`（二维码浮层）、`LogOverlay`（全屏日志浮层），以及浮层共用行为（居中、Esc 关闭、点浮层外面关闭）。
- 顶部 120px 状态环：弧长随五态变化，环内写状态词与 PID；环外右侧一行放手机访问结论与 Tailscale / 局域网地址。
- 单一主操作按钮，文案与配色随五态变化（启动 DSH / 停止 DSH / 修复/重启 / 重新探测），点击走的就是原有回调。

### 变更

- 其余操作收进右上角「⋯」应用内抽屉：刷新状态、重启、切换 Web 端口、手机访问二维码、复制手机/本机地址、两个 UAC 开关、导出诊断包、日志跟随、关闭行为、退出；队列非空时附「取消排队」。
- 常驻二维码区整块移除：点「手机访问」弹模态浮层（地址下拉 + 二维码 + 复制按钮）。
- 运行日志默认只显示末尾 15 行，右下角「展开全屏」开独立日志窗口；跟随、打码、2000 行截断自愈仍走同一份 `logtail` 链路。
- 「关闭窗口时收进托盘 / 直接退出」从页脚布尔开关改成抽屉里的切换项，托盘行为不变。
- `--selftest` 标记更新：保留 `qr / clear / adopt_shown / adopt_hidden / log_lines / trim / addresses`，新增 `ring / menu_items / overlay_open / overlay_closed / log_collapsed / log_expanded`。
- 测试 189 → 208 例（新增 `tests/test_ui_theme.py`：五态视觉、尺寸常量、主按钮映射；`tests/test_widgets.py`：`snap_to_line` 五条替身用例；`tests/test_gui_hooks.py` 补托盘退回普通窗口两条）。
- 日志卡从固定高度改成随窗口拉伸（15 行是下限，2000 行截断不变），底部不再留空带。

### 修复

- Tk 9.0 下 `create_arc` 的 `extent` 取 360 或 359.9 会被归零、整圈画不出来；状态环封顶 359 度。
- 150% DPI 下「⋯」抽屉按逻辑宽度定位会探出窗口右侧；改为画完后按实际像素宽度右对齐。
- 全屏日志浮层顶部第一行常被切掉半行：自动换行的续行让 `index("@0,0")` 看不出错位，改用 `dlineinfo` 逐像素对齐（`dshconsole/widgets.py` 的 `snap_to_line`）。

## [2.0.0] - 2026-11-03

首个「可发布」版本，四批合成：A 可移植性 → B1/B2 正确性与可观测性 → C 体验层 → E 可发布构建。
下面按批次记录细节；E 的产物事实（版本、大小、SHA256、签名方案）见 `docs/build-and-signing.md`。

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

v2 批次 C：体验层 —— 托盘常驻、跟随真实日志、脱敏诊断包、多地址选择器、串行命令队列，
外加一次探测提速（改前 14.4 秒 → 改后 2.1 秒）。

### 新增

- `dshconsole/tray.py`（pystray）：托盘图标复用现有 `DeepSeekChan [256x256].ico`，菜单为
  「显示/隐藏主窗口、复制手机访问地址、停止 DSH、退出」；关闭按钮收进托盘，页脚的开关可一键改回
  「关闭即退出」，选择存进 `config.json` 的 `close_to_tray`。托盘不可用（无库、远程桌面）时自动
  降级成普通窗口，并把原因写进日志框 —— 不会因为托盘把程序弄崩。
- `dshconsole/logtail.py`：按字节偏移跟随 `dsh-web.stdout.log` / `dsh-web.stderr.log`，
  只追加新内容；文件被截断或轮转时自动重同步；日志框上限 2000 行、超出滚动丢弃旧行；轮询间隔 0.4 秒
  （下限 0.3 秒，不做 busy loop）。每一行进入界面前都过 `textutil.redact_text()`。
- `dshconsole/textutil.py`：新增 `redact_text()`（`redact()` 的超集，原语义不变）：`token=`、
  cookie / set-cookie / session、`Authorization: Bearer`、`api_key` / `password` 等键值、
  `sk-` 与 `gho_`/`ghp_` 等前缀、以及 URL 里的 `user:pass@` 全部打码。
- `dshconsole/diagnostics.py` 与界面「导出诊断包」：一个 zip，内含 `meta.json`（版本、时间、
  解释器、是否冻结、phase/PID/notes、config 的路径类字段）、`probe.txt`（每项结论与耗时）、
  `log-tail.txt`（日志尾部 500 行）、`windows.txt`（OS / PowerShell / portproxy / 防火墙原始输出）。
  四个条目在写进 zip 的那一刻就只有一个打过码的版本，不存在忘打码的中间文件。
- `dshconsole/addresses.py`：访问地址候选 —— 本机 / Tailscale / 每个局域网 IP，每项标注来源
  （本机 / Tailscale / 以太网 / WLAN），端口可编辑并按 1-65535 校验，IPv6 自动加方括号；
  探测失败显示「未知（原因）」，不给空下拉。
- `dshconsole/tasks.py`：串行命令队列，状态为「排队中 / 执行中 / 成功 / 失败 / 已取消」，
  排队中的任务可取消（正在执行的不强杀 —— 它可能正拿着跨进程句柄），界面显示「前面还有 N 个」。
- `dshconsole/snapshot.py`：状态短 TTL（3 秒）缓存，「手动刷新」强制穿透。
- `dshconsole/probe.py`：`probe_all()` 一次刷新只 spawn 一次 PowerShell（node 进程与网卡地址
  走同一段脚本），netsh portproxy / netsh 防火墙 / `tailscale.exe` 并行执行；返回结构化
  `RawProbe`（含每项耗时与失败原因），查不到仍是 `None`。
- `dshconsole/single.py`：`Activator` 命名事件 —— 第二个实例被互斥体挡下时唤起已有窗口，
  窗口收在托盘里也会先显示再聚焦。
- 测试：`test_snapshot` / `test_logtail` / `test_tasks` / `test_addresses` /
  `test_diagnostics` / `test_tray` 六个新文件，以及 8.3 短名归一化用例（124 → 186 个用例）。

### 变更

- 状态刷新改为非阻塞：先显示上次结果 + 「刷新中…」，后台线程探测，完成后 `after(0, ...)` 回填；
  打开窗口或点刷新都不再冻结界面。
- 「复制手机地址 / 生成二维码」从手输 IP 改成下拉选地址 + 可编辑端口。
- 所有会阻塞的按钮改走串行队列，队列状态显示在状态卡片；全局 `_busy` 移除，异常 / 超时 / 取消后
  按钮都回到可用态。
- 防火墙探测从 `Get-NetFirewallRule`（约 2.6 秒）换成 `netsh advfirewall firewall show rule`
  （约 0.1 秒）；网卡地址改用 .NET `NetworkInterface`（顺带拿到「以太网 / WLAN / Tailscale」名称）；
  进程查询与地址查询合并成一次 PowerShell 调用。
- CI：`py_compile` 覆盖 `dshconsole` 全部 16 个模块，依赖检查加 `pystray`；`--selftest`
  增加「日志行数上限」和「地址候选非空」两项，`--stop-selftest` 改为断言队列空闲。

### 修复

- 一次完整状态刷新从 14.43 秒（改前三次中位数）降到 2.08 秒（改后三次中位数），同一台机器实测。
- 8.3 短名路径（CI runner 的 `RUNNER~1`）下，控制台认不出自己启动的 DSH：`bin.js` 路径比对
  永远不相等。config 返回的路径统一 `resolve()` 归一化，并补了短名 / 长名归一化的回归用例。
- 托盘菜单文案是可调用对象时，pystray 以 `text(item)` 调用它，实测抛
  `TypeError: ... takes 1 positional argument but 2 were given`；已包一层适配并加用例。
- 状态回填回调本身曾经吃掉 105 毫秒：其中 `Text.see("end")` 一次 56 毫秒（要算末尾
  bbox），`token_url()` 又在主线程读日志跑正则、和探测线程抢 GIL。改成 `yview_moveto(1.0)`、
  token 在后台线程算、多行说明合成一次 insert 之后，刷新期间注入的 Tk 回调中位数 31 毫秒、
  最坏 48 毫秒（改前主线程被整个冻结 14 秒）。

v2 批次 E：可发布构建 —— 产物终于带版本信息，打包口径从「计划」变成「实测」。

### 新增

- `version_info.txt`：PyInstaller 的 `VSVersionInfo` 文本表示，是版本号的**唯一**源头 ——
  `filevers` / `prodvers` 均为 `(2, 0, 0, 0)`、`CompanyName` 为 `berserkross`、
  `FileDescription` 与 `ProductName` 为「DSH 控制台（小肥鱼控制台）」、`LegalCopyright` 为 MIT 版权、
  `Comments` 写仓库地址；字符串表用 `080404B0`（zh-CN + 码页 1200），中文不会乱码。
- `dshconsole.__version__ = "2.0.0"`：诊断包 `meta.json` 的 `version` 字段此前永远读到 `"unknown"`。

### 变更

- `DSHConsole.spec`：新增 `version='version_info.txt'`；`name` 由 `DSH 控制台` 改为 `DSHConsole`
  —— ASCII 文件名在命令行 / CI / 签名脚本里不用带引号、不受代码页影响，中文产品名改由 PE 版本资源与
  窗口标题体现；`upx=False`、`console=False` 保持显式。
- `.github/workflows/check.yml`：新增「打包 + 版本资源校验」步骤 —— 真跑一遍 PyInstaller 打包，断言产物
  存在且 `FileVersion` / `ProductVersion` / `CompanyName` / `ProductName` 非空。理由是这四项正是此前
  **静默**失效的环节：spec 少一个 `version=` 参数，构建照样成功、产物照样能跑，只是没有版本信息。

### 修复

- 产物没有 `FileVersion` / `ProductVersion` / `ProductName`：`.rsrc` 里只有图标与 manifest（71,912 B）；
  加上版本资源后 72,896 B（+984 B），`GetVersionInfo` 五项均非空。
- 诊断包的 `version` 字段恒为 `"unknown"`（包上没有 `__version__`，`diagnostics._version()` 走 fallback）。

### 验收（实测）

- `python -m unittest discover -s tests`（3.14.7）与 `py -3.11 -m unittest discover -s tests`（3.11.9）：
  189 个用例全绿。
- `py -3.11 -m PyInstaller --noconfirm DSHConsole.spec`：退出码 0，干净重建 20.7 秒，产物
  `dist\DSHConsole.exe` 32,151,698 B，SHA256 `04700552D6835F521634D4B4531B409DC69AF925CC14152C03318FD05E5E85FD`。
- 冻结态 `--selftest` / `--stop-selftest`：退出码都是 0（标记文件里 `qr=True clear=True adopt_shown=True
  adopt_hidden=True log_lines=2000 trim=True addresses=True`；`fake_alive_after_click=False
  log_has_stopped=True queue_idle=True`），说明 `_MEIPASS` 下的 ps1 与 ico、pystray、qrcode、PIL 都能起来。
- 产物未签名：本机 `Get-ChildItem Cert:\CurrentUser\My -CodeSigningCert` 无输出，也没有 `signtool.exe`；
  SmartScreen 显示「未知发布者」属预期。

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
