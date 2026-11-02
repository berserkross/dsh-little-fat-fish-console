"""布局契约（批次 F）：13 项操作平铺可见、每颗按钮都接上回调、整屏塞得进 700px。

这些断言刻意不建窗口：DPI 相关的窗口尺寸用 ui_theme 里的预算算，
真窗口的人工核对走 %TEMP%\\ui_v3 下的截图。
"""
import math
import unittest

try:
    import dsh_gui
except Exception as exc:      # noqa: BLE001 - 缺 GUI 依赖时跳过
    raise unittest.SkipTest("无法导入 GUI：" + str(exc))

from dshconsole import status, ui_theme, widgets


def _entries():
    return [(title, icon, text, name)
            for title, group in dsh_gui.ACTION_GROUPS
            for icon, text, name in group]


class ActionGroupsTests(unittest.TestCase):
    """功能网格是唯一入口：它必须覆盖全部操作，且不得有任何折叠。"""

    def test_three_semantic_groups_in_order(self):
        titles = [title for title, _entries in dsh_gui.ACTION_GROUPS]
        self.assertEqual(titles, ["服务", "手机访问", "工具"])

    def test_every_entry_wires_a_real_callback(self):
        for title, icon, text, name in _entries():
            self.assertTrue(text.strip(), title)
            self.assertTrue(icon.strip(), f"{title}/{text} 缺图标")
            self.assertTrue(callable(getattr(dsh_gui.ConsoleApp, name, None)),
                            f"{title}/{text} -> {name}")

    def test_buttons_and_callbacks_are_unique(self):
        texts = [text for _t, _i, text, _n in _entries()]
        names = [name for _t, _i, _t2, name in _entries()]
        self.assertEqual(len(set(texts)), len(texts), texts)
        self.assertEqual(len(set(names)), len(names), names)

    def test_every_entry_carries_a_distinct_glyph(self):
        """每颗按钮都要有图标，而且图标不能重样 —— 重样就等于没有图标。"""
        icons = [icon for _t, icon, _t2, _n in _entries()]
        self.assertEqual(len(set(icons)), len(icons), icons)
        for icon in icons:
            self.assertEqual(len(icon), 1, f"图标应是一个字形：{icon!r}")
            self.assertFalse(icon.isspace(), icon)

    def test_phone_access_entries_are_visible(self):
        """用户最找不到的那颗：手机访问的四项必须在网格里，不进任何折叠。"""
        names = {name for _t, _i, _t2, name in _entries()}
        for name in ("on_phone_access", "on_copy", "on_phone_on", "on_phone_off"):
            self.assertIn(name, names)

    def test_no_folding_entry_point_is_left(self):
        """抽屉与「⋯」都不许回来：留着类就等于留着入口。"""
        self.assertFalse(hasattr(widgets, "DrawerMenu"))
        for name in ("_open_drawer", "_drawer_items", "_place_drawer"):
            self.assertFalse(hasattr(dsh_gui.ConsoleApp, name), name)

    def test_start_and_stop_live_only_on_the_primary_button(self):
        """同一个动作只许一个入口：启停归主按钮，服务组只留从属动作。"""
        names = [name for _t, _i, _t2, name in _entries()]
        self.assertNotIn("on_start", names)
        self.assertNotIn("on_stop", names)
        for name in ("on_restart", "on_refresh", "on_change_port"):
            self.assertIn(name, names)
        # 启停没丢：主按钮的映射里仍在
        got = {dsh_gui.primary_action(phase)[1]
               for phase in (status.Phase.STOPPED, status.Phase.RUNNING)}
        self.assertEqual(got, {"start", "stop"})

    def test_group_count_matches_the_spec(self):
        """15 项 → 13 项：启停合并到主按钮后，服务组少两颗。"""
        self.assertEqual(len(_entries()), 13)


class LayoutBudgetTests(unittest.TestCase):
    """150% DPI 下逻辑高 700：头部 + 主按钮 + 网格 + 日志下限 + 底栏必须自己塞得下。"""

    @staticmethod
    def _card_height(group) -> int:
        rows = math.ceil(len(group) / 2)          # 组内 2 列
        return 9 + 15 + 6 + rows * (ui_theme.GRID_BTN_H + ui_theme.GRID_PAD)

    def _stack_height(self) -> int:
        card = max(self._card_height(group) for _t, group in dsh_gui.ACTION_GROUPS)
        foot = 6 + 18 + 6
        return (ui_theme.PAD + ui_theme.HEADER_H + ui_theme.GAP
                + ui_theme.ACTION_H + ui_theme.GAP + card + ui_theme.GAP
                + 8 + 18 + 4 + 10 + ui_theme.LOG_ROWS_MIN * ui_theme.LOG_LINE_PX
                + 10 + ui_theme.GAP + foot + ui_theme.PAD)

    def test_whole_layout_fits_a_900px_window(self):
        need = self._stack_height()
        self.assertLessEqual(need, 900, f"头部+主按钮+网格+日志共需 {need}px")

    def test_whole_layout_fits_the_default_window(self):
        need = self._stack_height()
        self.assertLessEqual(need, ui_theme.WINDOW_SIZE[1],
                             f"默认窗口 {ui_theme.WINDOW_SIZE[1]}px 装不下 {need}px")

    def test_grid_is_short_enough_to_leave_the_log_room(self):
        for title, group in dsh_gui.ACTION_GROUPS:
            rows = math.ceil(len(group) / 2)
            self.assertLessEqual(rows, 3, f"{title} 组 {rows} 行：日志要留够空间")
        self.assertGreaterEqual(ui_theme.WINDOW_MIN[1], 400)

    def test_two_columns_at_the_narrow_window(self):
        """900×900 都不能塌：窄窗仍走两列，组卡吃满宽度。"""
        self.assertEqual(ui_theme.grid_columns(ui_theme.WINDOW_MIN[0]), 2)
        self.assertEqual(ui_theme.grid_columns(ui_theme.WINDOW_SIZE[0]), 3)


if __name__ == "__main__":
    unittest.main()
