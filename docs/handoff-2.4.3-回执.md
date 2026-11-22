# 小肥鱼控制台 2.4.3 交接回执

- 日期：2026-11-22
- 执行方：Codex
- 仓库：`berserkross/dsh-little-fat-fish-console`
- 发布代码提交：`acc9ce155be086ba5a263a63e8abbf4dbc3112f5`
- Release 标签目标：当前 main 上包含本回执的最终提交，可用 `git rev-parse v2.4.3` 核对
- Release：https://github.com/berserkross/dsh-little-fat-fish-console/releases/tag/v2.4.3
- 代码 CI：https://github.com/berserkross/dsh-little-fat-fish-console/actions/runs/44972239537
- 回执前最终 CI：https://github.com/berserkross/dsh-little-fat-fish-console/actions/runs/44973063419

## 一、逐项结论

### 任务 A：工作区整理

已完成安全整理，部分需要 DSH 决策的项目保持原状：

- 三个无绝对路径引用、无快捷方式指向的日期目录已移入 `worklogs\2026\`。
- 七份根级交接/指南文档已移入 `docs\handoff\`，相关引用同步更新。
- 三张未被引用的截图已移入 `_archive\screenshots\`。
- 未删除任何用户数据。
- 正式部署点、3080 DSH 本体、Git 仓库、当前会话目录、敏感文件和仍需恢复资料的目录均未搬动。

详细搬移清单和待决定项见
`C:\Users\Ibash\Documents\Codex\2026-11-22\c-users-ibash-documents-codex-apps\outputs\工作区整理-2026-11-22.md`。

### 任务 B：2.4.3

已完成代码修复、测试、构建、签名、GitHub Release、CI 和正式部署。

## 二、实际改动

- `dshconsole/journal.py`：定位到主日志 PermissionError、LocalAppData WinError 5；用户目录内的打包版改为优先写安装目录 `logs\console.log`，其余位置继续作为回退。回退成功时，回退文件也持久化每个失败位置的异常。
- `dsh_gui.py`：窗口构造前后各写一条启动记录；界面事件先落盘，再刷新控件，避免 Tk 绘制异常吞掉启动证据。
- `tests/test_journal.py`、`tests/test_lifecycle.py`：覆盖安装目录优先、配置目录回退、失败原因落盘、先落盘后刷新控件，以及 Windows 8.3 短路径。
- `dshconsole/__init__.py`、`version_info.txt`、`README.md`、`CHANGELOG.md`：版本与文档更新到 2.4.3，用例数更新为 524。
- `docs/build-and-signing.md`：发布顺序改为先推发布分支、按确切 SHA 创建 Release、最后推 main。

## 三、验证证据

```text
Ran 524 tests in 14.306s
OK

SELFTEST OK
STOP SELFTEST OK
文档一致性检查通过。
```

- CI `44972239537`：`completed / success`，语法、依赖、文档、GUI 自检、524 项测试和 onedir 构建全部通过。
- exe FileVersion / ProductVersion：`2.4.3.0`。
- 签名：`Valid — Signature verified.`，有 DigiCert 时间戳。
- Release 标签 SHA：`acc9ce155be086ba5a263a63e8abbf4dbc3112f5`。
- ZIP：`DSHConsole-2.4.3.zip`，32,934,329 字节。
- ZIP SHA256：`57bcf6e531df70ae945c0afc13647df14ce2b29e2ccaae01be0a9c6937420f49`。
- exe SHA256：`095933d5f1fdb852eb150f9b1b528613ea9c978a34d735b67f3ac94e05ce6491`。
- GitHub Release 附件重新下载后的 SHA256 与本地 ZIP 完全一致。

### 真机部署

- 正式路径：`C:\Users\Ibash\Documents\Codex\2026-11-02\pc-dsh\outputs\repair-20261105\console\DSHConsole-app`
- 当前控制台 PID：`44572`
- 控制台日志：`DSHConsole-app\logs\console.log`
- 日志已记录窗口构造前后事件，未再出现 AppData 回退警告。
- 3081：`LISTENING`，当前 Tailscale 根地址返回 `200`。
- 3080：仍由本机 DSH `node.exe` PID `30328` 占用，返回 `401`；部署期间未停止或重启 3080。

3081 当前返回 200 而不是交接中期望的 302。控制台日志明确说明：当前
3080 不是控制台本次启动的实例，控制台找到的 token 被 3080 拒绝，因此显示提示页。
要得到 302 必须重启 3080，交由控制台重新接管；交接铁律禁止重启承载会话的 DSH，所以本次保持 3080 原进程不动。

打包版 `--selftest` 在不继承真实用户 TEMP 的工具沙箱中曾因受限 Temp 目录无法写文件而停住；源码自检与 CI 的 GUI 自检均通过。正式桌面启动已验证正常。

## 四、目录变更

### 已搬移

- `2026-11-03` → `worklogs\2026\2026-11-03`
- `2026-11-15` → `worklogs\2026\2026-11-15`
- `2026-11-18` → `worklogs\2026\2026-11-18`
- 七份根级交接/指南文档 → `docs\handoff\`
- 三张未被引用截图 → `_archive\screenshots\`

日期目录搬移前后文件数与总字节数一致；文档和截图搬移前后 SHA256 一致。

### 待 DSH 决定

- 空目录 `2026-11-13`、`2026-11-19`、`temp_design_folder`
- `dsh-prompt-ab-test`
- `office-preview-test-20261105`
- 其余大目录的长期归档策略

## 五、遗留与风险

- 3081 当前是 token 不匹配提示页；在不重启 3080 的约束下未强行修复。
- 根目录 `api keys.txt` 含潜在敏感信息，本次没有读取、移动或打包。
- 聊天状态数据库仍引用部分旧日期目录，因此这些目录保守保留。
- 两个旧输出目录含恢复资料，未搬入删除区。

## 六、回滚

### 正式部署

- 切换前完整副本：
  `...\console\backups\DSHConsole-app-2.4.2-before-2.4.3-20261122-0939`
- 切换时保留的旧现场目录：
  `...\console\DSHConsole-app.previous-live-2.4.2-20261122-0942`

回滚步骤：

1. 关闭当前 2.4.3 控制台 PID `44572`，只动控制台，不动 3080。
2. 把当前 `DSHConsole-app` 移到单独的失败备份目录。
3. 把上述旧现场目录移回 `DSHConsole-app`。
4. 启动旧版，确认日志与新部署前一致。

### Git / Release

- 修复发布提交：`acc9ce1`
- 前一提交：`90aabff`
- 再前一提交：`c01cfda`
- Full Rollback 可把 main 恢复到 `ea98821`；Release `v2.4.3` 可删除整体回滚。Release 版本不建议与代码 main 分开倒回。

### 工作区

按整理记录中的映射把目录、文档、截图移回原位，并恢复旧绝对路径引用。本次没有删除项。
