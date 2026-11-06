# 交接：小肥鱼控制台 阶段 0–4（交给 Claude Code）

> 交付对象：Claude Code（下称 CC）。写这份文档的是 DSH 会话（下称 DSH）。
> 日期：2026-11-07。仓库：`C:\Users\Ibash\Documents\Codex\apps\dsh-console`。
> 你的任务：完成阶段 0–4 → 推 GitHub（含 exe）→ 写交付文档，含两份交接（给 DSH、给 Codex）。
> 读完后先做第 0 节的自检，再动手；本文所有数字都要你自己复核，不要盲信。

---

## 0. 先自检（3 分钟，不改任何文件）

```bash
cd C:/Users/Ibash/Documents/Codex/apps/dsh-console
git log --oneline -3          # 期望 HEAD 为 c5be2f3（若已推进，以实际为准并在交付文档里写明）
git status --porcelain        # 期望为空
py -3.11 -m unittest discover -s tests -t . 2>&1 | tail -3   # 期望 Ran 361 tests, OK
```

若 `git status` 不干净、或测试不是 361 全绿：**先停下来**，在交付文档里记录并询问用户，不要在此基础上改。

---

## 1. 背景：你接手的是什么

小肥鱼控制台是 DeepSeek Harness（DSH）的桌面控制台：启停 `dsh web`、把服务开给手机、看状态与日志。
上一轮（2026-11-05/06，另一个 CC 会话）修了一个「假活」闭环 bug：

- 手机访问用 `netsh portproxy` 在 3080 建转发，由 svchost 监听；换网络后旧规则不清理；
- `launch-dsh.ps1` 原来用 `netstat | Select-String ":3080 LISTENING"` 判断「DSH 在跑」→ 把 svchost 的转发当成 DSH → 点启动不启动 → 浏览器 000/超时；
- `_stop()` 只杀 node、不拆转发 → 停止后端口永远「在线」→ 假活永久，且永远报「未完全停止」。

那批改动已经由 DSH 复核并提交为两个 commit（**不要改写、不要 squash**）：

| commit | 内容 |
|---|---|
| `f294001` | fix(lifecycle)：launch 改进程检测 + 探测 5s→2s；switch 增 `Remove-AllProxies`/`-CleanupOnly`；`_stop()` 有残留自动清理；`_start()` 端口在线即拒绝；起不来/认不出 PID 不再打印「启动完成」 |
| `c5be2f3` | fix(probe)：端口占用者只认 `127.0.0.1` 监听；`_process_pairs` 命令行读不到时整体判未知 |

DSH 已完成的体检（你要在此基础上继续，不是重做）：

- `HEAD` 曾为 `2590566`，之后加了上面两个 commit；工作区干净；
- `361 tests OK`；两份 ps1 `[Parser]::ParseFile` 均 PARSE OK；
- **关键缺口**：`-CleanupOnly` 的调用路径零测试；`_start` 守卫、重启中止、`_process_pairs` 返回 None 均无测试；
- **已知 bug**：`dsh_gui.py` 的 `_stop()` 调 `self._run_switch(...)` 但**没接返回值**，下一行无条件写「端口转发残留清理完成」——用户取消 UAC 也报成功；
- `probe._process_pairs` 现在「任一 node 进程命令行读不到 → 整体 None」，管理员态 DSH + 普通权限 GUI 时可能永远 UNKNOWN；
- `switch-dsh-web.ps1:92 Remove-Proxy` 已无调用者（死代码）；`Remove-AllProxies` 只匹配 `v4tov4`，IPv6 规则残留不会被清；
- 版本仍 `2.2.5` / `2.2.5.0`，CHANGELOG 未记这批维修。

---

## 2. 环境与硬约束（违反会直接坏东西）

### 2.1 路径与工具

- 仓库：`C:\Users\Ibash\Documents\Codex\apps\dsh-console`（git，分支 `main`）——**就在这台 PC 上、就用这一份工作副本**，不要另 clone、不要新建 worktree
- 远端：`https://github.com/berserkross/dsh-little-fat-fish-console.git`（`origin`）
- GitHub CLI：`C:/Users/Ibash/AppData/Local/Programs/gh/bin/gh.exe`（已登录 `berserkross`，scopes 含 repo/workflow）
- Python：`py -3.11`（3.11.9）；PyInstaller 6.22.3
- 签名脚本：`scripts\sign-self-signed.ps1 -Exe <exe>`（证书 CN=YANG TIANRUI，指纹 `049AD1900E335BF8C9C3BB4F70619085BF2DA537`，Valid + DigiCert 时间戳）

### 2.2 三条会咬人的坑

1. **`TCL_LIBRARY` / `TK_LIBRARY` 泄漏**：从跑过 onefile exe 的终端里构建时，这两个变量可能指向已删除的 `%TEMP%\_MEIxxxx\_tcl_data`，PyInstaller 会**静默排除 tkinter**，产物从 32 MB 掉到 29 MB，双击弹 `Unhandled exception in script`（`ModuleNotFoundError: No module named 'tkinter'`），构建日志一句错都不报。
   - 构建前：`Remove-Item Env:TCL_LIBRARY, Env:TK_LIBRARY -ErrorAction SilentlyContinue`（bash 用 `env -u TCL_LIBRARY -u TK_LIBRARY …`）
   - 判据：`build-<ver>/DSHConsole/Analysis-00.toc` 里 `_tkinter` 出现 **4 次**；少了就是被排除。
2. **中文文本不要用 pwsh `Get-Content`/`Set-Content` 改**：会把 UTF-8 读成 cp936 再写回，整篇 mojibake。中文文案一律用编辑器的 read/edit/write 工具。
3. **`.ps1` 必须 UTF-8 BOM + CRLF**：PS 5.1 按 ANSI 解码中文会报「参数列表中缺少 ')'」。改完必须 `[System.Management.Automation.Language.Parser]::ParseFile()` 校验。

### 2.3 不许做的事

- 停/重启 3080 上的 DSH **已获用户授权**（2026-11-07 明确答复「可以，随时做，不用问」），包括 `--stop-selftest`（`dsh_gui.py:2454`，会写 `%TEMP%\dsh-stop-selftest.txt`）与真实点击「停止」。但每次停服后必须**恢复到运行状态**并验证 `http://127.0.0.1:3080/` 有应答，交付文档里写明你打断过几次会话。
- 不许改 `apps\deepseek-harness`（DSH 本体）与 `.dsh` 配置；只改 `apps\dsh-console`。
- 不许新增第三方依赖；不许改 `DSHConsole.spec` 的 `datas`/`hiddenimports` 结构（除非有实测理由并在交付文档说明）。
- 不许为了测试通过去改断言或删用例。

---

## 3. 阶段 0 — 补测试（先把安全带系上）

目标：让新行为有回归网。全部用**注入式**测试，不碰真机、不启停 DSH。

必须新增（文件名自定，建议追加到 `tests/test_gui_hooks.py` 或新建 `tests/test_lifecycle.py`）：

1. `_stop()`：端口 `_port_open()` 返回 True、`_pids_provider()` 返回空、`probe.portproxy_targets` 返回非空 → 断言调用了 `-CleanupOnly`（注入 `_run_switch` 记录参数）。
2. `_stop()`：`portproxy_targets` 返回 `(None, "…")` → 断言**不**调用清理，且日志含「查不到」。
3. `_start()`：端口在线时（无论 `force` 真/假）→ 断言不启动、日志含占用者提示。
4. `_restart_*`：`_pids_provider()` 返回 `([], None)` 且端口在线 → 断言中止、不调 `_stop`/`_start`。
5. `probe._process_pairs`：其中一个进程 `command_line` 为空/不可读 → 断言返回 `(None, "部分 node 进程命令行不可读取，无法安全判定 DSH 是否运行")`。

顺带修掉已知 bug（P1）：`_stop()` 里接住 `_run_switch` 的返回值，成功才写「清理完成」，失败写「清理失败：<why>」。

**验收**：`361 + 5 = 366` 条全绿（若你顺带加了别的用例，总数以实际为准并写进交付文档）；`git status` 只有本阶段的意图内改动。

提交：`test(lifecycle): 覆盖停止清理、启动守卫与进程未知判定`（一个 commit，别混入阶段 1 的版本号）。

---

## 4. 阶段 1 — 发 2.2.6（让修复有名字、有签名、有唯一副本）

1. 版本三处同步：`dshconsole/__init__.py` 的 `__version__`、`version_info.txt` 的 `FileVersion`/`ProductVersion`（`2.2.6.0`）、`CHANGELOG.md` 新增 `## [2.2.6] - <日期>`（写清假活根因、清理逻辑、启动守卫、进程判定收紧）；`README.md` 的版本行与用例数、产物字节。
2. 清 TCL/TK 环境变量后干净构建：
   ```
   py -3.11 -m PyInstaller --noconfirm --clean --distpath dist-2.2.6 --workpath build-2.2.6 DSHConsole.spec
   ```
   确认 `Analysis-00.toc` 里 `_tkinter` 4 次、产物 > 32 MB。
3. 签名：`powershell -File scripts\sign-self-signed.ps1 -Exe dist-2.2.6\DSHConsole.exe`，记录 `Get-AuthenticodeSignature` 状态、FileVersion、字节数、SHA256。
4. **三处落点统一到同一份**（用户 2026-11-07 已授权由你替换，现在三份 exe 互不相同）：
   - `dist-2.2.6\DSHConsole.exe`
   - 用户实际启动点：`C:\Users\Ibash\Documents\Codex\2026-11-02\pc-dsh\outputs\repair-20261105\console\DSHConsole.exe`（先备份为 `.bak-2.2.6`）
   - 桌面：`C:\Users\Ibash\Desktop\小肥鱼控制台.exe`（同名 .lnk 指向它，替换文件即可，不需要改 lnk）
5. 提交 + 打 tag + 发 Release（exe 作为资产）：
   ```
   gh release create v2.2.6 "dist-2.2.6/DSHConsole.exe" --title "v2.2.6 — 端口转发残留不再造成假活" --notes-file <临时说明文件>
   ```

**验收**：三处 exe 的 SHA256 完全一致且 `Valid`；`gh release view v2.2.6 --json assets` 显示 `uploaded`；CI（push 触发）绿。

---

## 5. 阶段 2 — 让「假活」在界面上可见

1. 状态条：当 `probe.portproxy_targets(3080)` 非空、且 `_pids_provider()` 为空时，显示琥珀色「端口转发残留」标记；悬停/点击给出「清理」动作（复用 `-CleanupOnly`，走脚本自带的 UAC 通道）。
2. `-CleanupOnly` 结果可见（阶段 0 已修返回值，这里补 UI：成功/失败都写进日志与状态）。
3. `dshconsole/diagnostics.py` 的诊断包里追加：`netsh interface portproxy show v4tov4` 全表 + 最近 20 条启动失败摘要（沿用现有脱敏管线）。

**验收**：新增 2–3 条注入式用例；诊断包解压后能看到 portproxy 表；UI 截图（`tests/shoot_ui.py`）里残留态可辨。

---

## 6. 阶段 3 — 单一入口（用户已选方案 A）

目标：掐死「多入口无互斥」这个 EADDRINUSE 的根因（历史累计 129 次）。

方案 A 的两件事：

1. **ps1 退成薄壳**：`launch-dsh.ps1` 只保留「启动/停止」动作，运行状态判定统一走 GUI 那套 `probe.classify`（本机 bin.js 才认）；不再自己用「任意 bin.js 进程」判断。
2. **启动串行化**：启动前获取命名互斥体 `Local\DshConsole.DshStart`（名字已定稿，用户无既有约定；`dshconsole/single.py` 已有同类实现可参考），拿不到就提示「另一个入口正在启动」并退出，不做第二次拉起。GUI、ps1、switch、restart 四条路径都要过这道闸。

**验收**（用户已授权随时停服）：交替执行「GUI 启动 → 关闭 → 双击脚本 → 关闭 → 重启」共 10 轮，`apps\deepseek-harness\dsh-web.stderr.log` 中 EADDRINUSE 出现 0 次；每轮只有一个 node 实例。10 轮结束后必须把 DSH 恢复到运行状态并验证 200；若中途出现异常，先恢复服务再排查，不要留在停止态。

---

## 7. 阶段 4 — 启动耗时可视化

不改 DSH 本体。控制台在「启动中」阶段显示：已用秒数 + 最近一行启动日志（`logtail` 已有跟随能力），替代无限转圈。实测基线：token ≈13.8s，HTTP 200 ≈15.5s（主要成本是 60+ 插件，不在控制台范围内）。

**验收**：冷启动截图里能看到秒数递增与日志行；启动完成后停留 2 秒再切回正常状态。

---

## 8. 收尾（必须做，顺序不能乱）

1. **推送**：`git push origin main` + `git push origin v2.2.6`；确认 CI 绿（`gh run list --limit 1`）。
2. **Release**：见阶段 1 第 5 步，资产必须是签名后的 exe。
3. **写两份交接文档**（都放 `docs/`，随代码一起提交推送）：
   - `docs/handoff-to-dsh-2026-11-<dd>.md` —— 给 DSH（下一个开发会话）的**进度同步**：做完的阶段、版本与产物 SHA256、验收证据（测试数、CI、Release 链接）、未验证项与原因、下一步建议、以及你对代码的改动清单（文件 + 行号级要点）。
   - `docs/handoff-to-codex-visual-2026-11-<dd>.md` —— 给 Codex 的**阶段 5 视觉外包**交接：
     - 代码地图：`dsh_gui.py`（窗口/布局/主题）、`dshconsole/widgets.py`（自绘控件）、`dshconsole/data/art/`（手写 SVG 素材 + `scripts/render-art.py`）；
     - 怎么出图：`tests/shoot_ui.py`（多尺寸截图）、`tests/verify_shots.py`（像素校验）、`tests/measure_chips.py`；
     - 约束：`--selftest` 必须过、现有布局断言不许改、不许引入同人图、只用项目自绘与官方可分发票素材；
     - 现状：视觉旋钮停在 `bc52002`，风格方向**尚未确定**，等用户提供参考图；Codex 不得自行定风格；
     - 验收口径：960×700 与 620×560 两版截图、`--selftest` OK、单测全绿。
4. **给用户的收尾报告**（会话里直接回复，不用写文件）：做了什么、证据、没做什么、下一步。

---

## 9. 报告格式（每阶段结束时在会话里说一次）

- 阶段：做了什么（文件 + 要点）
- 证据：命令 + 关键输出（测试数、PARSE OK、`_tkinter` 次数、SHA256、CI 结论）
- 没做/未验证：明确列出，不许含糊
- 下一步：一句话

---

## 10. 事实核对清单（你动手前应亲自确认）

- `git log --oneline -3` 是否以 `c5be2f3` 开头；
- `py -3.11 -m unittest discover -s tests -t .` 是否 361 全绿；
- 两份 ps1 是否 PARSE OK；
- `dist-2.2.5\DSHConsole.exe`（32,257,544 B、Valid）确实**不含**这批维修；部署点那份（32,251,099 B）**未签名**；
- `dsh_gui.py` 中 `_stop()` 的 `_run_switch` 调用是否仍未接返回值（若已修，说明有人先动过，记录之）。

以上任何一条与本文不符：以你的实测为准，并在交付文档里写明差异。
