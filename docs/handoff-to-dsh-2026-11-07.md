# 交接：阶段 0–4 完成情况（CC → DSH）

> 交付对象：DSH（下一个开发会话）。写这份文档的是 Claude Code 会话（CC），按
> `docs/handoff-to-claude-code-2026-11-07.md` 完成阶段 0–4 与收尾。
> 日期：2026-11-07。仓库：`C:\Users\Ibash\Documents\Codex\apps\dsh-console`。

## 结论速览

- 阶段 0–4 **全部完成**，共 6 个 commit（`fe7519d` → 见 git log，最终 HEAD 以实际为准）；
- 单元/注入测试 **361 → 393** 全绿；两个随包 ps1 与三个 harness 侧脚本 **PARSE OK**；
- v2.2.6：**用户裁决"含全部阶段"**——tag 指向最终 commit，exe 在收尾时按最终代码重建、签名、
  部署到 pc-dsh 启动点（桌面 `小肥鱼控制台.lnk` 指向该文件，无需改 lnk）；
- 阶段 3 十轮交替启动验收：**通过**（10/10 轮全绿、每轮运行态 web 实例数恒为 1、
  EADDRINUSE 增量 0、结束后 DSH 恢复运行、token 地址 303 有效）。验收期间抓到一个真实
  生产 bug 并已修复：`psrun` 捕获管道被孙进程继承导致 `communicate` 挂死（commit `692e306`）；
- 推送/Release/CI 按用户裁决（"按文档最后统一推"）在收尾执行。

## 各阶段完成情况

### 阶段 0 — 补测试 + P1（commit `fe7519d`）

- 新增 `tests/test_lifecycle.py`（8 条）与 `tests/test_scripts.py` 1 条：停止清理（含探测失败
  不清理）、启动守卫（force 均拒绝）、重启中止、`probe._process_pairs` 未知判定、脚本 UAC
  取消 `exit 1` 内容断言。验收基数 361+9=370。
- P1 修复：`_stop()` 接住 `_run_switch` 返回值，成功才报「清理完成」、失败报「清理失败：why」；
  **另一半在 ps1 侧**（计划未写，裁决补充）：随包 `switch-dsh-web.ps1` 取消 UAC 时 `exit 1`，
  否则外层脚本永远退出 0、GUI 永远看不到失败。

### 阶段 1 — 发 2.2.6（commit `4bd08e4` + tag，收尾时重建）

- 版本三处同步（`__init__.py` 2.2.6 / `version_info.txt` 2.2.6.0 / CHANGELOG / README）；
- 清 TCL/TK 环境变量干净构建：`Analysis-00.toc` `_tkinter` ×4，产物 32,251,168 B，签名后
  32,258,304 B，`Valid`，SHA256 `A6693EB597FED31E8BB66F61F94743D218803619DB62DDDE8180C9BF8F330C51`
  （**该值为阶段 1 产物；收尾按用户裁决用最终代码重建，最终值见 §产物**）；
- 部署：pc-dsh 启动点替换（旧版备份 `DSHConsole.exe.bak-2.2.6`）；桌面只有 `.lnk` 指向该文件
  （文档假设的桌面 exe 不存在——裁决：两处物理落点，lnk 不动）。

### 阶段 2 — 假活可视化 + 诊断（commit `44ca6da`）

- `status.Status` 增 `residue` 三态；状态条琥珀色芯片「端口转发残留 · 点此清理」（残留态 pack、
  平时不占位），点击走 `-CleanupOnly`；`_stop` 复用新方法 `_cleanup_residue()`；
- 诊断包新增 `startup-failures.txt`：最近 20 条 `startup-*.log` 摘要（优先 EADDRINUSE 行），
  走同一脱敏管线；`FILES` 扩为 5 条目；
- 新增 10 条用例（380 全绿）；`shoot_ui.py` 增 `03b-residue.png`（琥珀像素 3141 vs 基线 1544）。

### 阶段 3 — 单一入口（commit `29250d0`）

- `dshconsole/single.py` 增 `StartLock`/`acquire_start_lock()`：`Local\DshConsole.DshStart`
  命名互斥体，`WaitOne(0)` 抢闸，弃锁（WAIT_ABANDONED）视为拿到，降级不拦启动；
- GUI `_start()` 全程持闸（端口守卫之后、`_start_direct` 到验证完成），拿不到报
  「启动被闸门拦住」并退出；
- 随包 `launch-dsh.ps1` 薄壳化：运行判定与 `probe.classify` 同规则（`[regex]::Escape($bin)`
  只认本机这份 bin.js）；独立双击回退推导修复（DSH_HOME 父目录 → `Documents\Codex\apps\deepseek-harness`，
  以 bin.js 实际存在为准）；新增 `-NoOpen`；启动前过同一把闸；
- 随包 `switch-dsh-web.ps1` 的 `Start-Dsh` 过闸；
- **harness 侧同步（用户裁决授权的扩展，超出交接文档边界）**：
  - `apps\deepseek-harness\launch-dsh.ps1`：exact-bin 判定 + 闸（备份 `.bak-20261107`）；
  - `apps\deepseek-harness\启动DeepSeekHarness.ps1`：同改，**顺带修掉该副本残留的 netstat 误判
    与 5s 探测两个旧 bug**（备份 `.bak-20261107`）；
  - `apps\deepseek-harness\switch-dsh-web.ps1`：UAC 取消 `exit 1` + `Start-Dsh` 过闸（备份 `.bak-20261107`）；
  - `.cmd`/`.vbs` 纯委托未改；`dsh-console.ps1` 仅状态显示未改；`restart-*.ps1` 未改（遗留入口，见建议）；
  - 全部 PARSE OK、UTF-8 BOM + CRLF。
- 新增 9 条用例（389 全绿）；十轮交替启动验收：**通过**。验收过程记录：
  - v1/v2/v3 三次驱动版本分别死于驱动缺陷与管道挂死（详见下文 bug 修复），v4 分块重跑
    10/10 轮全绿：每轮 GUI 启动 → 停 → 双击脚本 → 停 → 重启 → 停，全程 web 实例数恒为 1、
    EADDRINUSE 增量 0（基线 0 → 终值 0）；结束后恢复运行态并验证 token 地址应答 303
    （=有效，与 launch-dsh.ps1 的 2xx/3xx 判据一致；裸 urlopen 跟随重定向会丢 cookie 得 401，
    这是驱动判据的第一版缺陷，非 DSH 问题）。
  - **验收抓到的真实生产 bug**（commit `692e306`）：`psrun.execute` 用捕获管道承接
    PowerShell 输出，`Start-Process` 拉起的 DSH 及插件 worker 树继承管道写端 → EOF 永不
    到来 → `communicate` 挂死（faulthandler 栈转储实证）→ 真实 GUI 点「启动」也会挂死。
    修复：输出改落临时文件，只等服务进程退出。新增 1 条真实 PowerShell 冒烟用例（393 全绿）。

### 阶段 4 — 启动耗时可视化（commit `28a8668`）

- 状态条中段在 `STARTING` 阶段显示「启动中 x.x s · <最近一行启动日志>」（日志行过
  `textutil.redact_text` 脱敏、80 字截断）；`RUNNING` 后停留 2 秒再回 PID/端口；
- 新增 3 条用例（392 全绿，README 同步 392）；`shoot_ui.py` 增 `03c-starting.png`
  （与 03b 头部像素对比确认渲染差异）。

## 产物（收尾后回填最终值）

| 项 | 阶段 1 值 | 最终值 |
|---|---|---|
| 签名后 SHA256 | `A6693EB5…330C51` | `E2079F0377B04E0E5688B34A0C6DD032E5816C0720E8F6328C434C94495D6A4E` |
| 字节数 | 32,258,304 B | 32,266,240 B（未签名 32,259,099 B） |
| 部署点 | pc-dsh（`.bak-2.2.6` 备份在旁） | 最终 exe 已替换，两处 SHA256 一致 |
| tag | `v2.2.6` @ 4bd08e4 | 按用户裁决移到最终 commit |

## 未验证项与原因（如实列出）

1. 残留芯片的**真实点击路径**未点过：只有注入式单测 + 截图（芯片可辨）；UAC 提权路径未实测
   （真实清理会弹 UAC，未在验收里触发）。
2. 悬停 tooltip 未做：点击即清理满足「悬停/点击给出清理动作」的或条件。
3. `verify_shots.py` 未纳入新截图（03b/03c）：该脚本只校验既有截图清单；纳入是 2.2.7 候选。
4. 阶段 3 验收是**代码路径驱动**（真实 `ConsoleApp._start/_restart` + 真实探测）而非真实 GUI
   点击；「双击脚本」以 `-File launch-dsh.ps1` 等价模拟（双击即此命令）。
5. exe 内置 ps1 的内容只有断言测试，未在 exe 里实测触发（构建时随 spec datas 打包，spec 未改）。
6. `version_info.txt` 的 `filevers/prodvers` 仍为 `(2,0,0,0)`：交接文档只要求两个字符串
   （2.2.5 时代也如此）；建议 2.2.7 同步成 `(2,2,7,0)`。

## 打断记录（DSH 服务被停/启）

1. 阶段 3 验收驱动第一次运行：先停当前 DSH，随后驱动因 `LiveApp` 缺 `_serve_host_arg` 崩溃，
   DSH 短暂处于停止态；修复后重跑并在结束时恢复运行。
2. v2/v3 两次验收驱动因管道挂死卡住（真实 bug，见上文），期间 DSH 处于被拉起的中间态；
   修复 `psrun` 后 v4 分块跑完 10 轮，每轮结束都停在干净停止态，最后一块结束后恢复运行
   （token 303 有效、web 实例 1）。用户 2026-11-07 已授权随时停服并要求恢复，以上均满足。

## 裁决记录（本会话所有偏离计划的决定）

1. 推送节奏＝按文档 §8 最后统一推（用户 2026-11-07 选择）。
2. harness 旧入口＝用户授权一并修（超出交接文档"不许改 apps\deepseek-harness"边界，清单先行报备）。
3. 随包 ps1 独立双击回退推导错误＝修掉（用户选择）。
4. 桌面 `小肥鱼控制台.exe` 不存在：`.lnk` 直指 pc-dsh 部署文件，两处物理落点、lnk 不动。
5. exe 不入 git（`dist-*` 被 .gitignore；Release 资产承载 exe）。
6. P1 修复的另一半在 ps1 侧（UAC 取消 exit 1）。
7. `v2.2.6` 含全部阶段（用户 2026-11-07 选择）：tag 移到最终 commit，收尾重建/签名/重部署。
8. 测试数按实际增长（361→392），README 已同步；超出计划的顺带用例均在本文档记录。

## 给 DSH 的下一步建议

1. **升 2.2.7 候选**：`verify_shots.py` 纳入 03b/03c；残留芯片 tooltip；`restart-*.ps1` 等
   遗留入口同步闸（当前仅文档标注）；插件瘦身（启动 15s 的主要成本在 60+ 插件，不在控制台）。
2. CI（check.yml）在收尾 push 后确认绿；若 Linux 上 `StartLockTests` 的 Windows 用例跳过属预期。
3. 阶段 3 验收脚本是一次性临时脚本（已随验收结束删除）；如需固化为回归，可参考本文档把它
   写成 `scripts/` 下的正式驱动（启动计时逻辑同阶段 0 建议）。
4. `dsh_gui.py` 的 `_start` 现在全程持闸（含 20s 等待窗口）：若未来启动路径变长，注意闸的
   持有窗口同步变长——这符合「串行化」意图，但会导致并发点击者的等待体感。

## 本会话改动清单（文件级要点）

- `tests/test_lifecycle.py`（新）：停止清理/启动守卫/重启中止/进程未知/启动闸 10 条；
- `tests/test_scripts.py`：UAC exit 1 + launch 脚本 4 条内容断言；
- `tests/test_single.py`：StartLock 3 条（1 条 Windows-only）；
- `tests/test_status.py`：residue 4 条；`tests/test_diagnostics.py`：startup_failures 2 条；
- `tests/test_gui_hooks.py`：FakeApp 增 `lbl_residue`/代理；残留芯片 4 条；启动行 3 条；
- `tests/shoot_ui.py`：03b/03c 两图；
- `dsh_gui.py`：`_stop`→`_cleanup_residue()` 复用；`_on_residue_click`；`_build_header` 芯片；
  `_apply_status` 芯片显隐；`_start` 持闸；`_sync_detail`/`_startup_line` 启动展示；
- `dshconsole/single.py`：`START_MUTEX_NAME`/`StartLock`/`acquire_start_lock`；
- `dshconsole/status.py`：`residue` 字段与 assemble 计算；
- `dshconsole/diagnostics.py`：`startup_failures()`/FILES 5 条目/build/export 接线；
- `dshconsole/data/launch-dsh.ps1`：薄壳重写（exact-bin、回退推导、闸、-NoOpen）；
- `dshconsole/data/switch-dsh-web.ps1`：`-CleanupOnly` 逗号修复史、UAC exit 1、`Start-Dsh` 闸；
- `dshconsole/__init__.py`、`version_info.txt`、`CHANGELOG.md`、`README.md`：2.2.6 同步。
