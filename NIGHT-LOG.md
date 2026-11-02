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
| E | 发布（version_info、`py -3.11` 构建、签名方案） | 🔄 进行中 | — |
| D | 视觉重排（信息架构、状态环） | ⏳ 未开始（你说最后做） | — |

远端 main = `f5f5c41`。**CI 已绿**（run 41506014906，39s，八步全过）。

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

## 等你拍板

（目前为空。遇到只能你决定的事我写在这里，并停下不硬猜。）