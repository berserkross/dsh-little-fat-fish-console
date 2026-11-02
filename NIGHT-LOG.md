# NIGHT-LOG · v2 通宵作业记录

> 你睡觉期间我按批次推进 v2。这份文件是唯一入口：看「当前状态」→ 翻「验收证据」→ 只看「等你拍板」。
> 最后更新：2026-11-03 03:30 (GMT+8)

## 当前状态

| 批次 | 内容 | 状态 | commit |
|---|---|---|---|
| A | 可移植性（config 层、--harness/--port、ps1 随包） | ✅ 已验收 | `a8bd549` `8bb6978` `ba48752` |
| B1 | 正确性（结构化探测、五态、脱敏、PID 确认） | ✅ 已验收 | `6c72bac` `9bdd07a` `9d8cb99` |
| B2 | 采纳运行中实例、单实例、异常显式化、去猴补丁 | ✅ 已验收并推送 | `c072600` `e468171` `4c03684` `65255e6` |
| C | 体验层五项 + 性能修复 + CI 缺陷 | ✅ 已验收并推送 | `b9d1a74` `4324165` `842b339` `3e71249` `92ee3ce` `5e998ea` |
| E | 发布（version_info、`py -3.11` 构建、签名方案） | ✅ 已验收并推送 | `718c34a` |
| D | 视觉重排（信息架构、状态环） | ⏳ 未开始（你说最后做） | — |

远端 main = `718c34a`。**CI 已绿**（run 41506609308，2m9s，九步全过，含新增的「构建 onefile exe 并断言版本资源」）。

## 决策记录（你定的 + 我定的）

- **E 用 `py -3.11` 构建**（你 m00555 定）：3.11 已补齐 customtkinter 6.0.0 / Pillow 13.0.0 / qrcode / PyInstaller 6.22.3
- **C 做五项、不做 i18n**（你 m00555 定）：托盘 / 日志跟随 / 脱敏诊断包 / 多地址选择器 / 命令队列
- **禁止停止/重启正在跑的 DSH（PID 9856）**：它是承载本会话的进程，停它等于掐断工作环境。所有启停验证用注入或临时 harness
- **每批验收通过就推 main**，不攒批
- **不打 force、不删 tag/分支、不碰仓库外目录**（CC Safety Net 也会拦）
- **打回上限 3 次**（你 m00623 定，原建议是 2）：同一任务书第 3 次仍不过，我按 R8 兜底自己修，并把"为什么三次都没修对"写进这份日志
- **测试期间可增删 3080 的防火墙规则，测完必须删**；不改 portproxy、不动 Tailscale、不碰 dsh-qq 的 open 组策略
- **Release 不挂 unsigned exe**（与 v1 一致）：打 tag + 写正文，等你有证书再补
- **无人值守时遇到只能你拍板的事：停下、写进「等你拍板」、不猜**


## 验收证据（我亲自跑的，不是子代理自述）

### B2
```
python -m unittest discover -s tests        → Ran 124 tests / OK
py -3.11 -m unittest discover -s tests      → Ran 124 tests / OK（skip=0，3.11 依赖已补齐后）
py_compile (20 files)                        → PY_COMPILE_OK
git grep 'globals()["' -- dsh_gui.py         → 零命中
git grep 'C:\Users\Ibash' -- *.py *.ps1 *.spec → 零命中
switch-dsh-web.ps1                           → BOM=True，diff 仅 1 行文案
%APPDATA%\dsh-console\config.json           → 不存在（实测后已清理）
```
真机采纳动作（我独立复跑）：
```
before: harness=...\deepseek-harness, phase=degraded, pids=[]
candidates: [(9856, '...\npm-cache\_npx\1e7f6d9597241db0')]
adopt msg: 已改为控制 ...\_npx\1e7f6d9597241db0（PID 9856）
after : phase=running, pids=[9856]
cleanup: removed config.json → restored harness=...\deepseek-harness
```

### 发现的真问题：状态刷新要 12–15 秒（已并入批次 C）
```
port_open            0.00s
dsh_processes        2.23s
other_dsh_processes  2.07s
portproxy            1.36s
firewall_rule        4.41s
lan_ips              2.46s
powershell 冷启动     1.14s   ← 每项都独立 spawn 一次
probe_status 合计    12.3–15.2s
```
修法：合并成一次 PowerShell 调用 + 非阻塞刷新 + 2–5s TTL，目标 ≤2s。

### C（我独立复跑，覆盖 189 例）
```
python -m unittest discover -s tests    → Ran 189 tests / OK        (3.14.7)
py -3.11 -m unittest discover -s tests  → Ran 189 tests / OK        (3.11.9, skip=0)
py_compile (17 文件)                     → COMPILE_OK
python dsh_gui.py --selftest            → SELFTEST OK, exit 0
python dsh_gui.py --stop-selftest       → STOP SELFTEST OK, exit 0
tray_started=True close_to_tray=True    → 菜单: 显示主窗口/复制手机访问地址/停止 DSH/退出
probe_status_batch 计时                  → 3.17 / 2.17 / 2.28 s（原 12–15s）
timings                                 → {'node':864,'addresses':37,'total':929} ms
3080 监听者                              → 仍是 PID 9856（未动）
%APPDATA%\dsh-console\config.json       → 不存在（未创建）
```
脱敏取证（我自己喂数据、自己解包检查）：
```
输入: token=abc123def456 / sk-livesecret0001 / gho_tokensecret9999 / cookie: session=deadbeefcafe
      / api_key=hunter2 / password=hunter3 / https://user:pw@example.com/x
四件套: meta.json probe.txt log-tail.txt windows.txt  每文件 hits=0 frag=0
TOTAL_LEAKS = 0        MASK_COUNT = 28
```

### E（我自己复验产物）
```
dist\DSHConsole.exe  32,151,698 B   onefile / x64 / GUI 子系统 / manifest asInvoker（不弹 UAC）
SHA256               04700552D6835F521634D4B4531B409DC69AF925CC14152C03318FD05E5E85FD
VersionInfo  FileVersion=2.0.0.0  ProductVersion=2.0.0.0  CompanyName=berserkross
             ProductName=FileDescription=DSH 控制台（小肥鱼控制台）
             LegalCopyright=MIT License · Copyright (c) 2026 YANG TIANRUI  OriginalFilename=DSHConsole.exe
冻结态自检   DSHConsole.exe --selftest → SELFTEST OK exit 0
             DSHConsole.exe --stop-selftest → STOP SELFTEST OK exit 0
打包内容     dshconsole\data\launch-dsh.ps1 / switch-dsh-web.ps1 / DeepSeekChan [256x256].ico 均在归档里
git 卫生     git ls-files 里 dist/ build/ *.exe 命中 0；.gitignore 已含 build/ dist/
证书         Cert:\CurrentUser\My 无 CodeSigningCert；signtool 未安装 ⇒ 维持"不挂 unsigned exe"
```
spec 现在有 `version='version_info.txt'` / `name='DSHConsole'` / `upx=False` / `console=False`；CI 新增一步会构建 exe 并断言四项版本字段非空——防的正是「spec 漏一行、exe 照样能跑但属性页空白」这种静默失效。

### 性能目标只做到一半（我的决定，写清理由）
```
低负载   1.96 / 2.04 / 2.10 s
主负载   2.25 / 2.43 / 2.60 s      （目标 ≤2s 未稳压住）
地板 = 一次 PowerShell 冷启动 1.2s + CimCmdlets 载入 0.85s
```
再压只有两条路，**我都没做**：(a) 常驻 PowerShell 宿主——增生命周期复杂度；(b) ctypes 读 PEB 取命令行——会动到「按 bin.js 认进程」这条给"停止 DSH"把关的判定，风险不值得。2.0–2.4s 已可接受，登记为已知限制。

### CI 失败（`65255e6`）
```
FAIL: test_harness_from_cwd_walks_up
AssertionError: 'C:/Users/runneradmin/...' != 'C:/Users/RUNNER~1/...'
Ran 124 tests / FAILED (failures=1)
```
不是测试瑕疵而是真缺陷：`harness_from_cwd()` 若返回 8.3 短名，后面和进程命令行（长名）做严格比较会永远不匹配 —— 即"短名路径下运行的控制台认不出自己启动的 DSH"。修法：返回 resolve 后的规范路径。已派给 C。

第二轮（`5f2b043`）仍红，另外 3 例同类：`test_cli_harness_equals_form_reaches_resolve` / `test_explicit_harness_beats_detection` / `test_resolve_reports_bin_js_and_token_log` —— 这次是**测试的期望值**用了 8.3 短名（`tempfile.mkdtemp()` 在 runner 上落在 `C:\Users\RUNNER~1\…`），而代码返回的是规范长名，方向反了。修法：`tests/test_config.py` 的 fixture（`make_harness` / `make_file` / `self.tmp`）统一返回 `resolve()` 后的路径。修完我另做了一次代理验证：把 `tempfile.tempdir` 指向 `…\Temp\..\Temp`（非规范但等价）跑全套 → `Ran 189 tests / OK`，证明用例不再依赖字面路径。已推送 `f5f5c41`，CI 转绿。

## 已发布

- tag `v2.0.0` → commit `718c34a`
- Release（**不挂 exe**，按你 Q4 的口径）：https://github.com/berserkross/dsh-little-fat-fish-console/releases/tag/v2.0.0
- 正文写了：四批变更、从源码运行/构建命令、五条已知限制、本机构建产物的 SHA256、189 测试与 CI 说明
- 远端 main = `cb49469`（tag 之后只有一份文档提交）

## 等你拍板

### 1. 批次 D（视觉）我没动手，只出了三张方案卡——这属于你的品味，不是我的
现状（功能已全通）：窗口 720x880，从上到下 = 状态标签 → 五个按钮（启动/停止/重启/切换/复制）→ 二维码区 → 日志框。改法三选一：

- **方案 1「大环 + 抽屉」**（我推荐）：顶部一个 120px 状态环（颜色 = 五态，环内是状态词 + PID），主操作只留一颗按当前状态变化的按钮（未运行→启动，运行中→停止，异常→修复），其余四项收进右上角「⋯」菜单。二维码改成点"手机访问"弹出的浮层。日志默认只显示末尾 15 行，可展开全屏。改动集中在 `_build`，不动任何业务逻辑。
- **方案 2「仪表盘」**：左右两栏——左栏状态卡 + 网络卡（本机/Tailscale/以太网地址各一行，带复制键），右栏日志。适合你经常一边看日志一边点操作。
- **方案 3「极简单行」**：顶栏一行状态点 + 状态词 + 三个图标按钮，整块区域留给日志。适合挂在副屏常驻。

三个方案都保留：托盘、单实例、诊断包、地址选择器、队列。你回一个编号（或"方案 1 但保留二维码常驻"这类改动），我按你的话做，一轮到底。

### 2. 需要你在真机上验证的
- `dist\DSHConsole.exe` 双击体验：托盘图标、关窗收托盘、第二次启动唤醒前窗——我在无人值守时只跑了 `--selftest`，没敢真开 GUI 长驻。
- 手机侧：Tailscale 打开时二维码指向的地址在手机上是否真能打开（我这边只验证到 `GET http://10.23.115.16:3080/ → 401`，即链路通、token 门禁在）。

### 3. 我没有做、也不想擅自做的
- 签名（无证书，方案已写进 `docs/build-and-signing.md`）
- Release 挂 exe（等你决定是否接受"未签名 + SmartScreen 提示"）
- 干净机器 / VC++ 运行库 / 杀软误报：需要另一台机器
- 把"状态刷新压到 2 秒内"（要动认进程的判定路径，风险不值得）