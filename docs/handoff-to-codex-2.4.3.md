# 交接：小肥鱼控制台 2.4.2 → 2.4.3（交给 Codex）

- 交接方：DSH（本机 DSH Web，3080）
- 接手方：Codex
- 日期：2026-11-22
- 仓库：`C:\Users\Ibash\Documents\Codex\apps\dsh-console`（GitHub：berserkross/dsh-little-fat-fish-console）
- 当前分支状态：main 领先 origin/main **1 个提交**（`dc7209a` 未 push）

---

## 一、项目是什么

一个小而专的 Windows 桌面控制台（Python 3.11 + tkinter/customtkinter + PyInstaller onedir），
只服务**一台本机的 DSH Web 安装**：启动/停止/重启 3080 上的 DSH、把服务临时开给手机
（Tailscale + 3081 免 token 直连 + 60 秒一次性动作码），以及看状态和日志。

**不是** Web GUI，**不是**插件宿主，**不要**引入框架级重构或新依赖。

---

## 二、本轮已完成（2026-11-22，勿重做）

### 2.1 onefile → onedir（提交 465cd66，已推、已发 Release v2.4.1）
- 症状：双击桌面快捷方式毫无反应，或弹 PyInstaller 引导层「Could not create temporary directory!」，
  且一行日志都不写。
- 根因：**onefile 产物**在启动时解包 32 MB 到 `%TEMP%\_MEIxxxx` 失败（本机装了腾讯电脑管家，
  Defender 已让位）。同机现场编的 8 MB hello onefile 能正常解包 ⇒ 机制没坏，是这份产物的解包被拦。
- 修法：`DSHConsole.spec` 改成 `EXE(..., exclude_binaries=True)` + `COLLECT`，产物
  `dist\DSHConsole\DSHConsole.exe`（约 6 MB）+ `_internal\`（整目录约 73 MB）。
  `tests/test_packaging.py` 6 例锁死「不许回 onefile」。
- 部署：`…\2026-11-02\pc-dsh\outputs\repair-20261105\console\DSHConsole-app\`，
  桌面快捷方式 `C:\Users\Ibash\Desktop\小肥鱼控制台.lnk` 指该目录。

### 2.2 落盘日志不再静默（提交 ea98821，已推）
- `dshconsole/journal.py`：`write()` 返回 `True/False`、失败原因进 `last_error()`、
  失败时把同一行抄到 `fallback_path()`＝`%LOCALAPPDATA%\dsh-console\console.log`。
- `dsh_gui.py`：`logline` 拆成 `_emit_log_line()`（只写界面）+ `_warn_journal_once()`
  （第一次失败在界面里说一句，含真实异常名，不刷屏）。`_append_log` 落盘分支同样接入。
- 测试：`tests/test_journal.py` 4 例、`tests/test_lifecycle.py` 2 例。

### 2.3 版本位 2.4.2（提交 dc7209a，**未 push**）
- 四处已改：`version_info.txt`(2,4,2,0 / '2.4.2.0')、`dshconsole/__init__.py`、
  `CHANGELOG.md`（新增 `## [2.4.2]`）、`README.md`（横幅 + 共 519 个用例）。
- 已构建、已签名（Valid）、已部署、正在运行（PID 12616，3081 返回 302）。
- 顺带修掉一处测试污染：`test_no_fallback_when_localappdata_missing` 原会退回真实
  `%APPDATA%`，曾往用户日志写 4 行脏数据；现已用 `DSH_CONSOLE_CONFIG` 关进临时目录。

---

## 三、现状与坑（接手前必读）

### 3.1 发版顺序是硬约束
`scripts/check_docs.py` 会校验「Release vX.Y.Z 是否存在」。**必须先建 GitHub Release，再 push**，
否则 push 触发的 CI 必红。完整顺序写在 `docs/build-and-signing.md` 第七节。补救办法：
`gh release create vX.Y.Z ...` 之后 `gh workflow run check.yml --ref main`。

本地闸门（CI 用 token 才会跑 Release 检查，本地默认跳过，所以**本地绿 ≠ CI 绿**）：
```
GITHUB_TOKEN=$(gh auth token) GITHUB_REPOSITORY=berserkross/dsh-little-fat-fish-console \
  py -3.11 scripts/check_docs.py
```

### 3.2 本机特有的坑（都是踩过的）
- `robocopy /MIR` 在这台机器上**静默失败**（退出码 16，一个文件都不复制），部署请用
  `cp -a dist/DSHConsole/. <目标>/ `。
- bash 安全网会 BLOCK `rm -rf`、`find -exec rm -rf`；递归删除只走
  `%USERPROFILE%\.agents\safe-delete.ps1 -Path <绝对路径> -Recurse`。
- `tools.edit` 会动 CRLF/BOM：`.ps1` 带中文必须是 **UTF-8 with BOM + CRLF**，否则
  PowerShell 5.1 报「参数列表中缺少 ')'」。
- 构建前必须 `unset TCL_LIBRARY TK_LIBRARY`，否则 tkinter 被静默排除（判据：
  `build/DSHConsole/Analysis-00.toc` 里 `_tkinter` 出现 4 次）。
- **不要停/重启 3080 上的 DSH**：DSH 承载着正在工作的会话。控制台代码只在 3081 和进程管理上动手。
- 测试命令：`py -3.11 -m unittest discover -s tests -t .`（519 tests）；自检：
  `py -3.11 dsh_gui.py --selftest`。

### 3.3 一条未闭环的悬案（2.4.3 的重点之一）
2.4.2 已上线，但**启动后依旧没有写一行 console.log，也没有生成备用落点文件**；
而同机 Python 脚本往同一个真实路径写入是成功的（权限没问题）。目前判断更可能是
`logline` 根本没被调到（而不是写了被拒），需要一次定向验证：在 `main()` 里
`ConsoleApp` 构造前后各写一行到 `journal.write`，确认到底卡在哪一步。

---

## 四、外包任务 A：整理工作区目录

目标目录：`C:\Users\Ibash\Documents\Codex` 与 `C:\Users\Ibash\Documents\Codex\2026-11-02\pc-dsh\outputs`

现状（DSH 已侦察）：
- `Codex\` 根下平铺着 12 个日期目录（2026-09-15 … 2026-11-22）、多个散落的
  `*.md` 交接/指南文档，以及 `_repair`、`acl-recovery`、`apps\` 等目录。
- `Codex\2026-11-02\pc-dsh\outputs\` 下只有三项：`dsh-prompt-ab-test`、
  `office-preview-test-20261105`、`repair-20261105`（后者是控制台的部署点，**不能动**）。

要求：
1. 先做**只读测绘**：列出目录树、体积、最后修改时间，找出重复/空壳/废弃项，形成一张
   「建议保留 / 建议归档 / 建议删除」清单。**先出清单再动手**。
2. 目标结构建议（可调整，但要在回执里说明理由）：日期目录收进 `worklogs/YYYY/`，
   散落的 `*.md` 收进 `docs/handoff/`（按主题或日期命名），临时产物归 `_archive/`。
3. **铁律**：
   - `repair-20261105\console\DSHConsole-app\` 是正在运行的部署点，**绝对不许移动或删除**；
   - `apps\deepseek-harness\` 是 3080 上正在跑的 DSH 本体，**绝对不许动**；
   - `apps\dsh-console\` 是 Git 仓库，只在仓库内部整理；
   - 删除只走 `safe-delete.ps1`；不确定的一律归档不删除，并在回执里列出待 DSH 决定项。
4. 每搬动一项都要验证：新位置可读、引用它的地方（文档里的路径、快捷方式）同步更新。

---

## 五、外包任务 B：迭代到 2.4.3（简洁性 + 可读性）

范围：`dsh_gui.py`（3042 行）与 `dshconsole/`（24 个模块）。

原则（务必守住）：
- **行为不变优先于美观**：任何重构后 519 个测试必须全绿、`--selftest` 必须 OK；
  改行为的必须在 CHANGELOG 里单独列一条并说明原因。
- **不要引入新依赖**，不要上框架，不要改打包形态（onedir 是刚定的）。
- 重点找这些味道：`dsh_gui.py` 里超长的方法、重复的 UI 装配样板、
  魔法数字/魔法字符串、`except Exception: pass` 这类会吞掉证据的地方、
  可以合并的配置读写样板。**每删一处「吞异常」都要留一条可观测路径。**
- 顺手把 §3.3 那条悬案（日志根本没落盘）定位并修掉，写进 CHANGELOG。
- 版本位按 2.4.2 的四处一起改到 2.4.3；README 用例数随实际改。

发布流程（严格按序）：
1. 改代码 + 版本位 → 跑全量测试 + selftest + 本地闸门；
2. `unset TCL_LIBRARY TK_LIBRARY && py -3.11 -m PyInstaller --noconfirm DSHConsole.spec`
   → 签名 `scripts/sign-self-signed.ps1` → 检查 FileVersion 2.4.3.0 与 Valid；
3. `zip` 出 `dist\DSHConsole-2.4.3.zip`；
4. **先** `gh release create v2.4.3 dist/DSHConsole-2.4.3.zip --target main ...`；
5. **再** `git push origin main`；
6. `gh workflow run check.yml --ref main` 并确认 9 步全绿；
7. 用 `cp -a` 部署到 `DSHConsole-app\`（先停旧控制台进程），重启控制台，
   确认 3081 返回 302、3080 的 DSH 未受影响。

---

## 六、交付物：回执单

完成（或部分完成）后，写一份回执单交还 DSH，放在仓库 `docs/handoff-2.4.3-回执.md`
（或你更合适的项目内位置），必须包含：

1. **逐项结论**：任务 A、任务 B 各自「已完成 / 部分完成 / 未做」，未做的写原因；
2. **实际改动清单**：文件级，每项一句「改了什么、为什么」；
3. **验证证据**：测试数与结果、selftest 输出、签名状态、FileVersion、CI run 链接、
   3081/3080 现场探测结果（贴真实命令输出片段，不要只写「通过」）；
4. **目录变更明细**：搬了什么、搬去哪、哪些是待 DSH 决定的；
5. **遗留与风险**：你判断需要 DSH 拍板的事项，以及你自己不确定的地方；
6. **可回滚方式**：每个破坏性动作的撤销办法（备份路径、git 提交号、Release 版本）。

---

## 七、给 Codex 的一句话

这只肥鱼只做一件事：把本机 3080 的 DSH 照顾好。**宁可少改，不可改坏**——
任何「顺手优化」都要先问自己：出问题时，用户还能不能从日志里看出发生了什么。
