"""布局契约（批次 E）：功能必须平铺可见、每颗按钮都接上回调、整屏塞得进 900px。

这些断言刻意不建窗口：DPI 相关的窗口尺寸用 ui_theme 里的预算算，
真窗口的人工核对走 %TEMP%\\ui_v2 下的截图。
"""
import unittest

try:
    import dsh_gui
except Exception as exc:      # noqa: BLE001 - 缺 GUI 依赖时跳过
    raise unittest.SkipTest("无法导入 GUI：" + str(exc))

from dshconsole import ui_theme, widgets


class ActionGroupsTests(unittest.TestCase):
    """功能网格是唯一入口：它必须覆盖全部操作，且不得有任何折叠。"""

    def test_three_semantic_groups_in_order(self):
        titles = [title for title, _entries in dsh_gui.ACTION_GROUPS]
        self.assertEqual(titles, ["服务", "手机访问", "工具"])

    def test_every_entry_wires_a_real_callback(self):
        for title, entries in dsh_gui.ACTION_GROUPS:
            for text, name in entries:
                self.assertTrue(text.strip(), title)
                self.assertTrue(callable(getattr(dsh_gui.ConsoleApp, name, None)),
                                f"{title}/{text} -> {name}")

    def test_buttons_and_callbacks_are_unique(self):
        texts = [text for _t, entries in dsh_gui.ACTION_GROUPS for text, _n in entries]
        names = [name for _t, entries in dsh_gui.ACTION_GROUPS for _x, name in entries]
        self.assertEqual(len(set(texts)), len(texts), texts)
        self.assertEqual(len(set(names)), len(names), names)

    def test_phone_access_entries_are_visible(self):
        """用户最找不到的那颗：手机访问的四项必须在网格里，不进任何折叠。"""
        names = {name for _t, entries in dsh_gui.ACTION_GROUPS for _x, name in entries}
        for name in ("on_phone_access", "on_copy", "on_phone_on", "on_phone_off"):
            self.assertIn(name, names)

    def test_no_folding_entry_point_is_left(self):
        """抽屉与「⋯」都不许回来：留着类就等于留着入口。"""
        self.assertFalse(hasattr(widgets, "DrawerMenu"))
        for name in ("_open_drawer", "_drawer_items", "_place_drawer"):
            self.assertFalse(hasattr(dsh_gui.ConsoleApp, name), name)

    def test_start_and_stop_are_both_reachable(self):
        """主按钮在一屏只显示一颗，所以两颗都得在网格里常驻可点。"""
        names = [name for _t, entries in dsh_gui.ACTION_GROUPS for _x, name in entries]
        self.assertIn("on_start", names)
        self.assertIn("on_stop", names)


class LayoutBudgetTests(unittest.TestCase):
    """150% DPI 下逻辑高只有 640：网格 + 15 行日志 + 底栏必须自己塞得下。"""

    def _stack_height(self) -> int:
        rows = max(len(entries) for _t, entries in dsh_gui.ACTION_GROUPS)   # 3 列时最高一列
        card = (8 + 15 + 4) + rows * (ui_theme.GRID_BTN_H + ui_theme.GRID_PAD)
        log_head = 8 + 18 + 4 + 10
        return (ui_theme.PAD + ui_theme.STATUS_BAR_H + ui_theme.GAP
                + ui_theme.ACTION_H + ui_theme.GAP + card + ui_theme.GAP
                + log_head + ui_theme.LOG_ROWS_COLLAPSED * ui_theme.LOG_LINE_PX
                + 10 + 6 + 18 + ui_theme.PAD)

    def test_whole_layout_fits_a_900px_window(self):
        need = self._stack_height()
        self.assertLessEqual(need, 900, f"状态条+主操作+网格+15 行日志共需 {need}px")

    def test_whole_layout_fits_the_default_window(self):
        need = self._stack_height()
        self.assertLessEqual(need, ui_theme.WINDOW_SIZE[1],
                             f"默认窗口 {ui_theme.WINDOW_SIZE[1]}px 装不下 {need}px")

    def test_grid_is_short_enough_to_leave_the_log_room(self):
        rows = max(len(entries) for _t, entries in dsh_gui.ACTION_GROUPS)
        self.assertLessEqual(rows, 6)        # 再多就该拆组了
        self.assertGreaterEqual(ui_theme.WINDOW_MIN[1], 400)


if __name__ == "__main__":
    unittest.main()
