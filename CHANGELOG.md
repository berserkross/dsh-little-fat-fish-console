# 变更记录

格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，版本号遵循 [SemVer](https://semver.org/lang/zh-CN/)。

## [Unreleased]

## [2.4.5] - 2026-11-26

### 修复

- **点「重启 DSH」有可能把控制台窗口一起带走**：真凶这次仍未定位（journal 里重启序列
  一行都没有，事件日志三天没有 Application Error，控制台父进程是 explorer，唯一会杀进程的
  `_stop` 已显式跳过自己的 PID）。本轮先把「可诊断」做实：新增动作簿
  `dshconsole/actions.py`，每个底层动作开始前落盘 `action.json`、每换一步覆盖、正常收尾删掉；
  下次启动读到残留就打出「上次「重启 DSH」在 11-26 02:31:07 断在「等端口关闭」，没有正常收尾。」
  —— 窗口被外部硬杀时这是唯一还留着的现场。
- **结束 DSH 只杀主进程**：node 的子进程留着会继续占用端口，下一步就卡在「端口没关」。
  现在 `taskkill /T` 结束整棵树，杀前用 `_pids_provider()` 复核名单（PID 会被系统回收，
  旧号可能已经指向别人）、杀后回读一次，确认真的没了才记「已结束」。
- 手机端动作改为投递时再绑定处理函数（`lambda` 包一层），替换面不必实现每一个动作。

### 新增

- **「中断会话…」**（服务组）：先列 DSH 里 `running=true` 的会话，弹窗多选（全选 / 中断全部 /
  中断所选 / 取消），只中断正在跑的这一轮，会话本身与记录都还在。
  手机端 `/console` 也加了「中断会话」按钮（需要电脑上签的动作码，intent 为 `interrupt`）。
- 新增 `dshconsole/sessions.py`：直接调 DSH 的 `/api` RPC（`session/list`、
  `session/cancel`），token 换 cookie 后走 `client-request` 信封。
- 新增 `dshconsole/actions.py`（`begin` / `step` / `finish` / `unfinished` / `describe`）。

### 用例

- 563 个（新增 21 个：动作簿 7、会话 RPC 8、中断会话的界面钩子 6）。

## [2.4.4] - 2026-11-26

### 修复

- **端口答话只问一次就下结论**：本机实测同一端口先连超两次、随后 2 ms 返回 401，
  单次 1.5 秒超时足以把好好的 DSH 判成「不应答 HTTP」（状态标签跳到「异常」）。
  `probe.http_answer` 现在默认问两轮、失败间隔 150 ms，只有全轮失败才返回 `None`。
- **控制台自己不会恢复**：以前只有启动那一次刷新，唯一计时器是 500 ms 的激活轮询，
  所以 Tailscale 起晚了、DSH 被别处重启之后，界面会一直停在旧状态直到用户手动点按钮。
  现在每 15 秒自动刷一次（`AUTO_REFRESH_MS`）；上一次还在飞就跳过这一轮，不叠请求。

### 新增

- **开机自启动开关**（服务组「开机自启动：开/关」）：写 / 撤
  `HKCU\SOFTWARE\Microsoft\Windows\CurrentVersion\Run\DSHConsole`。
  只碰当前用户的 Run 键，不需要管理员权限；写不进去时只记日志、不翻标签，不谎报已生效。
- 新增 `dshconsole/autostart.py`（`available` / `enabled` / `set_enabled` / `target_command`）。

### 用例

- 542 个（新增 `tests/test_autostart.py`、探测重试 3 例、自动刷新 3 例、开关 4 例）。

## [2.4.3] - 2026-11-22

- 正常启动时在窗口构造前后记录进度。单条界面事件先写日志，再更新控件，便于追查窗口初始化或绘制异常。

- 修复打包版写入默认日志返回 PermissionError、备用写入失败也没有记录的问题。用户目录内的 onedir 安装改为优先写 `logs/console.log`，AppData 继续作为后续回退；回退文件同时记录每个失败位置的异常，界面也报告成功位置或失败原因。

## [2.4.2] - 2026-11-22

### 修复

- **落盘日志静默失败**：`journal.write()` 以前把 `OSError` 吞掉，界面看着一切正常，
  事后却连一行证据都没有（2026-11-22 排查「exe 秒退」时就卡在这里）。现在它返回
  `True/False` 并记下 `last_error()`；界面在第一次失败时提醒一次（含真实异常名与路径），
  不再每行刷屏。
- **主位置写不进去就换地方存**：再加一个备用落点 `%LOCALAPPDATA%\dsh-console\console.log`，
  两处都失败才放弃；证据不再随主目录的权限问题一起消失。

### 现状

- 本机 2.4.1 的一个现场现象仍未闭环：同一个 exe 用 `DSH_CONSOLE_CONFIG` 指到别处能正常写
  `console.log`（1118 B 完整启动记录），用默认配置启动却连 `children.json` 都不更新，而
  PowerShell 对同一文件追加写成功、ACL 与属性正常、也没有 `DSH_CONSOLE_CONFIG` 环境变量。
  2.4.2 的提示与备用落点正是为了把这条真实异常打印出来。

## [2.4.1] - 2026-11-22

### 修复

- **双击 exe 毫无反应（真凶在打包形态）**：2026-11-22 起，onefile 产物在本机启动时停在
  PyInstaller 引导层，弹「Could not create temporary directory!」，日志一行不写。现场证据：
  换 `TEMP` 指向、`Start-Process` 与 bash 直接启动都失败；同机现场编的 8 MB hello onefile
  却能正常解包 ⇒ 环境能建临时目录，是大产物解包到 `%TEMP%\_MEIxxxx` 那一步被拦（本机
  装有腾讯电脑管家，Defender 已让位）。
- **打包改为 onedir**：`DSHConsole.spec` 从 onefile 改成 `EXE(exclude_binaries=True)` +
  `COLLECT`，产物是 `dist\DSHConsole\`（exe 约 6 MB + `_internal\`，整目录约 73 MB）。
  启动不再写临时目录，双击即开；桌面快捷方式改指 `DSHConsole-app\DSHConsole.exe`。
  分发形态随之变成 zip。

### 变更

- CI 的打包步骤改名为 `Build onedir app and check version resource`，校验路径改为
  `dist\DSHConsole\DSHConsole.exe`；新增 `tests/test_packaging.py` 盯着 spec 别再退回 onefile。

## [2.4.0] - 2026-11-15

### 新增

- **手机端只读控制台 /console**：3081 上直接看状态（阶段、端口、PID、端口转发、直连开关），
  点一下签一个 60 秒有效的一次性 6 位动作码，再用它执行 启动 / 重启 / 关闭 DSH；码过期即作废，
  错码不消耗真码，POST 体超过 4 KB 直接拒绝，页面与 JSON 都不含 token。
- 工具组新增「免 token 自动开」开关：偏好写进 config.json，重写探测结果时不会被顺手抹掉；
  关掉之后刷新状态不会再自动开 3081。

### 修复

- **3081 拿死钥匙**：token 采集改为在两份日志里取最新写入的那份——
  harness/dsh-web.stdout.log（控制台自己拉起 DSH 时写）与 DSH_HOME/dsh-web.log
  （别的会话调 restart_harness 时改道写，见 dsh-power-xc/lib/index.js:297）。
  只认前者时，外部重启一次手机就连不上。
- **node 堆封到 1.5 GB**：启动命令加 --max-old-space-size=1536。此前默认上限按内存给到
  4 GB，实测会涨到 2 GB 私有内存再被系统换页，物理内存只剩 0.6 GB 时整机卡顿。

### 变更

- 状态说明里的「异常（端口被占用）」简化为「异常」：端口在听却不应答 HTTP（半死）与
  「端口被别的程序占了」是两种情况，说明文字按有没有本机 bin.js 进程分两支。
- 启动等待改为 HTTP 就绪判定：端口开着但不答话不再算启动成功。
## [2.3.0] - 2026-11-12

### 新增

- **控制台落盘日志**：`dshconsole/journal.py` 把主日志区每一行连同异常追加到配置目录下的
  `console.log`（超过 1 MB 轮换成 `console.log.1`，token 自动脱敏）。此前所有诊断信息只活在
  窗口里，点了重启、窗口没了、DSH 也没起来——事后一个字都查不到。窗口启动时会打印该文件路径。
- 托盘菜单的「显示/隐藏窗口」现在会写一行日志，用来区分「窗口自己消失」和「被收进托盘」。

### 修复

- 重启/启动的等待不再短促放弃：`_wait_started()` 轮询端口，每 10 秒报一次「仍在等待」，
  重启等 30 秒、启动等 60 秒；失败时直接把 `dsh-web.stderr.log` 与 stdout 的最后 8 行贴进
  日志区，而不是只说一句「请查看日志」。
- 重启流程补了分段面包屑（「重启②：3080 已关闭，开始拉起新的 DSH。」），一次点击在日志里
  留下可复盘的轨迹。
- **进程表里一条读不到的记录会让整个控制台瞎掉**：`Get-CimInstance` 在进程创建/退出的瞬间会给出
  CommandLine 为空的条目，旧逻辑据此把整份进程表判成「不知道」——状态灯从此停在「未知」，
  重启入口也拿不到 PID，而 DSH 明明在跑。现在跳过读不到的那条，只有一条都读不到才判未知。
- 落盘日志不再抄一份 `dsh-web.*.log` 的镜像行（实测一分钟就能灌进 98 KB 插件噪声，会把
  「重启②/启动失败」这类面包屑挤出 1 MB 窗口）；`--selftest` / `--stop-selftest` 也改到临时
  配置目录，不再往用户真实的 `console.log` 里写测试数据。
- `_stop()` 增加自杀守卫：PID 会被系统回收，若候选 PID 恰好等于控制台自己的 PID，跳过并记录，
  避免「点重启把自己的窗口关了」。

## [2.2.9] - 2026-11-12

### 修复

- 3081 被占时界面看不出来：芯片停在「免 token 直连：关」，手机连不上而人以为是自己
  关掉的。现在绑定失败会把芯片写成「端口被占」并标红，日志同时给出排查命令
  （`netstat -ano | findstr :3081`），成功后自动恢复成「开」。

## [2.2.8] - 2026-11-12

### 修复

- 免 token 直连（3081）把手机送回一个没人监听的地址：跳转目标原先取的是「接管
  候选」，只在 DEGRADED 状态才有值，所以恒为空、静默落到 `http://<tailnet-ip>:3080/`
  ——那个端口只监听 127.0.0.1，手机点上去是死链。现在 `relay_target_url()` 以 serve
  域名优先、其次任何手机真能打开的候选，并按 token 缓存结果；换 token 自动重算，
  取不到地址只缓 10 秒。
- `probe.token_accepted()` 把好 token 判成坏的：默认 opener 会跟随 303 跳到无 token
  的 `/` 再吃 401。改为不跟随重定向、2xx/3xx 一律算有效，并对 token 做 URL 编码。
- token 正则截断：`dsh_gui` 里用 `[A-Za-z0-9_\-]+` 抓 token，遇到 `.`、`=` 等字符
  会在中途断掉，抓到的是一段假 token；改为 `[^\s\"'<>]+`。

## [2.2.7] - 2026-11-11

### 修复

- 免 token 直连（3081）跳转的是一把死 token：旧逻辑只看 `dsh-web.stdout.log` 的
  修改时间是否「晚于控制台启动」，回答不了「这把 token 现在还认不认」。DSH 被控制台
  以外的入口重启后，日志不刷新、判断照样通过，手机被重定向到 401。现在每次取 token
  都当场问 3080 一次（`probe.token_accepted`），不认就不跳转，并在控制台日志里写明
  「现在跑着的 DSH 不是控制台这次启动的」。
- 自动直连一次失败就整场放弃：端口被上一次运行的残留监听占住时，三次退避用尽后
  `_relay_auto_done` 永久置真。改为 5 秒退避持续重试，且 tailnet 地址变化时自动重绑。

### 变更

- `tailscale.serve` 的 target 从裸端口改为 `http://127.0.0.1:<port>`，不再依赖 CLI 的
  端口简写语法；已在 Tailscale 1.104.5 上核对 `--bg/--http/--yes` 与 `serve status --json`
  形状未变。
- `version_info.txt` 的 `filevers/prodvers` 从 (2,0,0,0) 修正为实际版本。

## [2.2.6] - 2026-11-07

### 修复

- 「假活」闭环根治：手机访问的 portproxy 转发规则随 IP 变化只增不减，残留规则让 3080
  永远显示在监听，启动脚本据此误判「DSH 在跑」而不启动、浏览器登录超时。现在：
  `Remove-AllProxies` 清掉本端口全部转发规则，开关手机访问都先清旧规则再重建；
  新增 `-CleanupOnly` 入口只清规则、不碰进程与防火墙。
- 停止 DSH 后若检测到转发残留，自动走 `-CleanupOnly` 清理；接住切换脚本返回值，
  用户取消 UAC 时如实报「清理失败」而不是「清理完成」（脚本侧取消提权改为 exit 1）。
- 启动守卫：端口已在监听时不再拉起第二份 DSH（EADDRINUSE 的根因），普通启动与
  强制重启路径同守。
- 进程判定收紧：任一 node 进程命令行读不到就整体判未知，不猜；端口占用者只认
  127.0.0.1 监听，转发假活不再被当成 DSH。
- `psrun` 输出改落临时文件：Start-Process 拉起的 DSH 及插件 worker 会继承捕获管道
  写端，`communicate` 等 EOF 挂死（十轮验收现场抓到的真实 bug）；现在只等服务进程
  退出、不依赖管道 EOF，启动不再有挂死窗口。

### 新增

- 状态条「端口转发残留」琥珀芯片：转发规则在、本机 DSH 进程不在时可见，点一下即清理。
- 启动串行化闸 `Local\DshConsole.DshStart`：GUI、launch 脚本、切换脚本、重启四条路径
  同一时刻只有一个入口在拉起 DSH，拿不到闸如实提示、不再叠加启动。
- launch 脚本薄壳化：运行判定与 GUI `probe.classify` 同规则（只认本机这份 bin.js）；
  独立双击回退推导修复（标准布局与本机布局都认）；新增 `-NoOpen` 供自动化。
- 诊断包新增 `startup-failures.txt`：最近 20 条启动失败日志摘要（优先 EADDRINUSE 行），
  走同一脱敏管线。
- 「启动中」状态显示已用秒数与最近一行启动日志（脱敏），完成后停留 2 秒再回 PID/端口。

## [2.2.5] - 2026-11-04

### 修复

- 免 token 直连在端口被占时不再「一次失败、整场放弃」：换 exe 重启时上一条监听可能还没退干净，
  第一轮绑不上就永久关掉了开关。现在最多重试三轮（每次状态刷新一次），真的占着才放弃。

## [2.2.4] - 2026-11-04

### 修复

- 手机访问的 3081 不再把「带 token 的地址」甩给手机，而是由电脑这边用手机请求里的 Host
  去跟 DSH 换一次 cookie，把 `Set-Cookie` 直接交给手机并 302 到 `:3080`。地址里不再出现 token，
  手机之后直接开 `http://<tailnet-ip>:3080/` 也进得去 —— cookie 与 Host 绑定，换出来的正是它能用的那块。
- 换不到 cookie（DSH 没起、端口不对）时退回原来的带 token 跳转，不假装成功。

## [2.2.3] - 2026-11-04

### 修复

- 启动前清空日志改到 Python 侧执行并检查结果。以前这一步写在 PowerShell 的
  `Set-Content ... -ErrorAction SilentlyContinue` 里，日志被别的进程占着时会静默失败，
  上一次运行的 token 就留在文件里，二维码扫出来必然 401。现在清不掉会明确说「token 不可信」。
- 点「启动」时若端口已被占用，日志直接报出占用者（PID 与 harness 路径），不再尝试起第二份 ——
  起也只会撞出 `EADDRINUSE` 然后把失败写进同一个日志，看起来像「控制台启动失败」。
- 401 提示补上占用者，方便一眼判断端口上答话的是不是控制台刚启动的那份。

## [2.2.2] - 2026-11-04

### 修复

- 「重启 DSH」以前只关闭、不重启：GUI 把 `-ServeHost` / `-ForceStart` 传给随包脚本，而
  `launch-dsh.ps1` 的 `param` 里没有这两个名字，PowerShell 在参数绑定阶段就失败，脚本一行都没跑。
  现在启动与重启都直接用 `Start-Process` 拉起 `dsh web`，脚本只作回退路径。
- 直连启动补上 `--trusted-host`（脚本那一版从来不传，重启出来的 DSH 认不得 tailnet 域名，
  手机访问回来就是 401），并显式把 `DSH_HOME` 交给子进程。
- 启动前清空 `dsh-web.stdout.log` / `dsh-web.stderr.log`，否则控制台读到的是上一次运行留下的
  过期 token，二维码扫出来是失效的。

### 新增

- 「免 token 直连」：在 tailnet 地址的 3081 上开一道本地门，手机打开 `http://<tailnet-ip>:3081`
  即 302 到带 token 的 3080，由 DSH 自己种 cookie；之后直接开 3080 也能进，直到 DSH 重启换 token。
  拿到 tailnet 地址时自动开一次，手动关掉之后不再自己打开。

## [2.2.1] - 2026-11-03

### 界面

- 整窗纵向滚动：窗口小于内容最小尺寸时，内容区整体滚动，底栏与日志始终可达；放得下时滚动条自动收起。
  以前把窗口拉到 620×560 会直接裁掉底栏，用户没有别的路可以走。
- 最小高度改为按各区块实测 `winfo_reqheight()` 求和。按 `GRID_BTN_H` 常量估算只有真值的一半，
  最小窗口里组卡会被压成一条缝、芯片文字被切。
- `_log_room()` 同源改为实测扣减：日志不再高估余量、擅自长到 10 行把三张组卡挤扁。

### 测试

- 327 个用例保持通过；`--selftest` 的 `primary_full` / `fit_full` 回到 True。

## [2.2.0] - 2026-11-03

### 界面

- 玻璃不再是「真半透明窗口」，改成画出来的渲染层：整窗竖向渐变（顶 26,40,74 → 底 5,8,18）+ 6% 以内的网格与星点 +
  卡面等效 0.94 不透明 + 1px 亮边 + 卡面下方柔影；`WINDOW_ALPHA=1.0`，桌面字再也透不过面板。
- 头部徽章、空态插画、窗口图标统一取自仓库根 `DeepSeekChan [256x256].ico`（圆心 136,130 / 半径 112 圆形遮罩 + LANCZOS，
  窗口图标改为 ico 优先、PNG 回退）。
- 常驻日志区高 = `clamp(实际行数, 6, 26) × 行高`，不再吸收剩余高度；空日志走 9 行 + 圆形大图空态。
- 功能网格三组卡严格等宽（457/457/458，余数 1px 交给 Tk 分配）、末项通栏、三组同列 chip 右沿 442/442/443；
  CustomTkinter 的 `place(width=, height=)` 必抛 `ValueError`，故布局改走 `grid_columnconfigure(weight=1, uniform="grow")` + `sticky="nsew"`。
- `_on_resize` 里补算日志行数：行数按可用余高取 clamp，不重算会留「窄高撑到 15 行、再拉矮仍停 15 行」的残留，把组卡挤到 276 高。
- 手机访问浮层改走 `dshconsole.phone` 计划：二维码与「复制手机访问地址」共用一道 `phone_candidate_url()` 闸，
  回环地址一律不进码（`addresses.is_loopback` → 不画码、只写下一步）；`_phone_on` 在 serve 就绪时不再提权，
  tailscale 的 `reason.text` 原样写日志；`--selftest` marker 追加 `phone_mode/phone_url/phone_reachable/phone_candidates/phone_qr_ok/phone_copy_ok`。
- 修窄→宽拖动窗口后组卡被夹扁、13 个芯片整组消失：行权重要按 `GRID_SUBCOLS` 整体重置，不能只配当前行数。
- 产品名改为「小肥鱼控制台」（窗口标题、单实例守卫、托盘、版本资源同步）。

### 测试

- 新增 `tests/shoot_ui.py` / `tests/verify_shots.py` / `tests/measure_chips.py`：状态截图、截图自检（连抓两张一致 + 白底垫后逐像素）、
  按钮测量表；`--selftest` marker 追加 `rows/rows_lines/rows_ok/empty_state/glass/fit_full/hero_art/ico/alpha` 字段。
- 用例 208 → 327（含手机访问浮层 20 例：候选过滤、绝不回落 127.0.0.1、serve 就绪不提权、reason 原样展示）。
### 新增

- `dshconsole/addresses.py`：手机可达候选 `mobile_candidates()` / `primary_mobile()`，按
  serve 域名 > Tailscale 100.x > 局域网私有网段 > 回环 排序，回环地址默认整条剔除；
  `Candidate.phone_reachable` / `display()` 给界面直接用，`url_for()` / `host_port()` 统一拼地址
  （默认端口省略、IPv6 加方括号）。
- `dshconsole/tailscale.py`：Tailscale 事实层。`detect()` 读 `status --json` 与 `serve status --json`，
  `serve_argv()` / `enable_serve()` / `reset_serve()` 管 serve 生命周期，`https_reason()` / `http_reason()`
  给结构化失败原因（cli_missing / daemon_down / not_logged_in / no_magicdns / https_disabled / serve_failed）。
  import 时不执行命令，解析函数只吃字符串，IO 全部可注入。
- `dshconsole/phone.py`：策略层 `plan()` / `detect_plan()` 返回 `PhonePlan`（候选列表 + 生效方式 +
  失败原因 + 用户下一步 + trusted-host 列表），serve 不可用时自动回退端口转发；`phone_checklist()`
  给「手机要满足什么」的判定清单。

### 变更

- `dshconsole/data/switch-dsh-web.ps1`：新增 `-ServeHost`（把 MagicDNS 域名加入 `--trusted-host`）；
  防火墙规则改为 `-Profile Any`，且对已存在的规则补 `Set-NetFirewallRule -Profile Any`
  （实测 WLAN/以太网被判为「公用」时，只放行 Private,Domain 的规则会让局域网路径整条静默失效）。
- 测试 208 → 269 例（新增 `tests/test_tailscale.py`、`tests/test_phone.py`，`tests/test_addresses.py`
  补回环排除/排序/候选测试）。

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
