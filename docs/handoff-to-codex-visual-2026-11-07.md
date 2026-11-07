# 交接：阶段 5 视觉外包（CC → Codex）

> 交付对象：Codex 会话（视觉阶段）。本文件由 Claude Code（CC）在完成阶段 0–4 后按
> `docs/handoff-to-claude-code-2026-11-07.md` §8 的要求撰写。
> 日期：2026-11-07。仓库：`C:\Users\Ibash\Documents\Codex\apps\dsh-console`。
> 现状快照：本文件基于 commit `28a8668` 之后的 main（以实际 HEAD 为准）。

## 1. 代码地图（视觉相关）

### 1.1 `dsh_gui.py` —— 窗口 / 布局 / 主题入口

- `ConsoleApp.__init__`：窗口尺寸 `ui_theme.WINDOW_SIZE`（960×700）、最小 `WINDOW_MIN`（620×560）；
  构造顺序：`_build()` → 托盘 → `_start_log_tail()` → `refresh` 轮询。
- `_build()` / `_build_header()` / `_build_primary()`：头部（玻璃徽章 + 状态灯 `widgets.StatusLamp`
  + 状态词 + `lbl_detail`（PID·端口，**启动中会显示秒数+日志行**）+ `lbl_residue`（残留芯片，
  残留态才 pack）+ 右端手机访问标签）；主按钮一颗通栏。
- 状态条颜色来自 `ui_theme.PHASE_STYLE`（`DEGRADED` 琥珀、其余见字典）；琥珀色常量
  `AMBER = "#FFC168"`。
- 残留芯片：`_apply_status` 里按 `state.residue` 显隐，点击 → `_on_residue_click` →
  `_cleanup_residue()`；文本「端口转发残留 · 点此清理」。
- 启动展示：`_startup_line()`（STARTING 时「启动中 x.x s · 最近一行启动日志」，RUNNING 后
  停留 2 秒），日志行已过 `textutil.redact_text`。

### 1.2 `dshconsole/widgets.py` —— 自绘控件

- `StatusLamp`（状态灯：颜色 + 弧长 + 状态词）、`QrOverlay`（二维码浮层）等自绘控件集中在此；
  视觉改动优先改这里，而不是在 `dsh_gui.py` 里堆样式。

### 1.3 `dshconsole/data/art/` —— 手写 SVG 素材

- `mascot_hero@256.png` / `mascot_idle@72.png` / `mascot_running@72.png` /
  `mascot_error@72.png` / `mascot_logo@32.png` + `src/`（SVG 源）+ `ASSETS.md`（素材清单与用法）；
- 素材由 `scripts/render-art.py` 从 `src/` 渲染生成（改 SVG 后用该脚本重渲染 PNG）。

## 2. 怎么出图（现有截图与校验管线）

| 脚本 | 用途 | 用法 |
|---|---|---|
| `tests/shoot_ui.py` | 多尺寸/多状态截图（01 停止…03c 启动中…11 黑底垫后），注入假状态、不碰真实 DSH | `py -3.11 tests\shoot_ui.py`，输出 `%TEMP%\ui_v4\` |
| `tests/verify_shots.py` | 像素校验（窗口逻辑尺寸、布局场景一致性、白底/黑底垫后穿透自检 A1） | `py -3.11 tests\verify_shots.py` |
| `tests/measure_chips.py` | 按钮网格测量表：同列 x0/x1 极差 ≤1px、列宽一致、末项通栏 | `py -3.11 tests\measure_chips.py` |
| `dsh_gui.py --selftest` | 全链路自检（注入式，不弹窗不碰真机） | `py -3.11 dsh_gui.py --selftest` |

## 3. 硬约束（违反即拒收）

1. `py -3.11 dsh_gui.py --selftest` 必须过；单测必须全绿（当前 392 条，`unittest discover -s tests -t .`）。
2. **现有布局断言不许改**（`test_layout.py`、`verify_shots.py` 的 A1 与场景断言、`measure_chips.py` 的判定）。
3. **不许引入同人图**：只用项目自绘素材（`dshconsole/data/art/`）与官方可分发素材；
   新素材一律先入 `art/src/` 再经 `scripts/render-art.py` 渲染。
4. 视觉旋钮停在 commit `bc52002`（`feat(theme): 视觉旋钮：外部 JSON 预设覆盖 + 字阶倍率`）：
   主题已有外部 JSON 预设机制，改视觉优先走预设，不要散写死色值。
5. **风格方向尚未确定，等用户提供参考图；Codex 不得自行定风格。**先按用户参考图出方案，
   未获用户确认前不要落地到代码。

## 4. 验收口径

1. `960×700`（默认）与 `620×560`（最小）两版截图，两种尺寸下关键状态（至少：停止、运行中、
   异常、残留、启动中）均可辨；
2. `--selftest` OK、单测全绿；
3. 截图为 `tests/shoot_ui.py` 产物 + 更新后的像素校验（如扩展 `verify_shots.py`，断言只能增
   加场景、不得放宽既有判定）。

## 5. 视觉阶段与本会话改动的交汇点（别弄坏这些）

- 状态条中段的文字宽度会随「启动中 x.x s · <日志行>」变化（`_sync_detail`）：改字体/宽度时
  注意别让长行把布局撑跳；
- 残留芯片是**动态 pack/pack_forget** 的控件：几何断言（measure_chips 类）如果要覆盖它，
  必须先在残留态注入状态再量；
- 截图目录 `%TEMP%\ui_v4\` 在 shoot_ui 每次运行前会被覆盖式使用（同名文件重写），取证脚本
  以最新一次运行为准。
