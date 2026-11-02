# NIGHT-LOG · v2 通宵作业记录

> 你睡觉期间我按批次推进 v2。这份文件是唯一入口：看「当前状态」→ 翻「验收证据」→ 只看「等你拍板」。
> 最后更新：2026-11-03 02:40 (GMT+8)

## 当前状态

| 批次 | 内容 | 状态 | commit |
|---|---|---|---|
| A | 可移植性（config 层、--harness/--port、ps1 随包） | ✅ 已验收 | `a8bd549` `8bb6978` `ba48752` |
| B1 | 正确性（结构化探测、五态、脱敏、PID 确认） | ✅ 已验收 | `6c72bac` `9bdd07a` `9d8cb99` |
| B2 | 采纳运行中实例、单实例、异常显式化、去猴补丁 | ✅ 已验收并推送 | `c072600` `e468171` `4c03684` `65255e6` |
| C | 体验层五项 + 性能修复 + CI 缺陷 | 🔄 进行中 | — |
| E | 发布（version_info、`py -3.11` 构建、签名方案） | ⏳ 未开始 | — |
| D | 视觉重排（信息架构、状态环） | ⏳ 未开始（你说最后做） | — |

远端 main = `65255e6`。**CI 当前是红的**，原因见下，修法已派给 C。

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

### CI 失败（`65255e6`）
```
FAIL: test_harness_from_cwd_walks_up
AssertionError: 'C:/Users/runneradmin/...' != 'C:/Users/RUNNER~1/...'
Ran 124 tests / FAILED (failures=1)
```
不是测试瑕疵而是真缺陷：`harness_from_cwd()` 若返回 8.3 短名，后面和进程命令行（长名）做严格比较会永远不匹配 —— 即"短名路径下运行的控制台认不出自己启动的 DSH"。修法：返回 resolve 后的规范路径。已派给 C。

## 等你拍板

（目前为空。遇到只能你决定的事我写在这里，并停下不硬猜。）