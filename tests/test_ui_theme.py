"""界面主题与主操作映射（批次 E）：只验「长什么样、点哪颗」，不建窗口。"""
import unittest

from dshconsole import status, ui_theme

PHASES = (status.Phase.STOPPED, status.Phase.STARTING, status.Phase.RUNNING,
          status.Phase.DEGRADED, status.Phase.UNKNOWN)


class PhaseStyleTests(unittest.TestCase):
    def test_every_phase_has_a_style(self):
        self.assertEqual(set(ui_theme.PHASE_STYLE), set(PHASES))

    def test_colors_are_pairwise_distinct(self):
        colors = [ui_theme.PHASE_STYLE[p].color for p in PHASES]
        self.assertEqual(len(set(colors)), len(PHASES), colors)

    def test_each_phase_carries_a_text_marker(self):
        """不能只靠颜色区分五态：灰度截图和色弱用户只能看字/形状。"""
        words = [ui_theme.PHASE_WORD[p] for p in PHASES]
        self.assertEqual(len(set(words)), len(PHASES), words)
        self.assertTrue(all(word.strip() for word in words))

    def test_sweep_is_a_ratio(self):
        for phase in PHASES:
            sweep = ui_theme.PHASE_STYLE[phase].sweep
            self.assertGreater(sweep, 0.0, phase)
            self.assertLessEqual(sweep, 1.0, phase)
        # 启动中 / 未知是「没走满的灯」：弧长本身也是信息
        self.assertLess(ui_theme.PHASE_STYLE[status.Phase.STARTING].sweep, 1.0)
        self.assertLess(ui_theme.PHASE_STYLE[status.Phase.UNKNOWN].sweep, 1.0)

    def test_phase_labels_are_distinct_short_words(self):
        labels = [phase.label for phase in PHASES]
        self.assertEqual(len(set(labels)), len(PHASES), labels)
        self.assertTrue(all(label.strip() for label in labels))

    def test_style_is_immutable(self):
        style = ui_theme.PHASE_STYLE[status.Phase.RUNNING]
        with self.assertRaises(Exception):
            style.color = "#000000"      # type: ignore[misc]


class SizeConstantTests(unittest.TestCase):
    def test_status_lamp_is_a_small_dot(self):
        """批次 E 把 107px 的大环换成小圆点：它必须比状态条矮得多。"""
        self.assertGreater(ui_theme.STATUS_LAMP, 0)
        self.assertLessEqual(ui_theme.STATUS_LAMP, 16)
        self.assertGreater(ui_theme.STATUS_BAR_H, ui_theme.STATUS_LAMP * 2)

    def test_log_defaults_to_15_rows(self):
        self.assertEqual(ui_theme.LOG_ROWS_COLLAPSED, 15)
        self.assertGreater(ui_theme.LOG_LINE_PX, 0)

    def test_overlay_sizes_are_positive(self):
        for width, height in (ui_theme.OVERLAY_QR, ui_theme.OVERLAY_LOG):
            self.assertGreater(width, 0)
            self.assertGreater(height, 0)

    def test_ring_and_drawer_constants_are_gone(self):
        """大环和抽屉都删了，留着常量就会被下一个改动悄悄用回去。"""
        for name in ("RING_SIZE", "RING_THICKNESS", "DRAWER_WIDTH", "DRAWER_ROW_HEIGHT"):
            self.assertFalse(hasattr(ui_theme, name), name)

    def test_grid_columns_breakpoints(self):
        self.assertEqual(ui_theme.grid_columns(ui_theme.COLUMNS_3_MIN), 3)
        self.assertEqual(ui_theme.grid_columns(ui_theme.COLUMNS_3_MIN - 1), 2)
        self.assertEqual(ui_theme.grid_columns(ui_theme.COLUMNS_2_MIN), 2)
        self.assertEqual(ui_theme.grid_columns(ui_theme.COLUMNS_2_MIN - 1), 1)
        self.assertEqual(ui_theme.grid_columns(0), 1)
        # 默认窗口宽度就得是 3 列：功能网格一开窗就是全展开的样子
        self.assertEqual(ui_theme.grid_columns(ui_theme.WINDOW_SIZE[0]), 3)

    def test_tokens_the_frozen_qr_overlay_needs_still_exist(self):
        """QrOverlay 是禁改件：它引用的 token 少一个就让整个手机访问浮层打不开。"""
        for name in ("CARD", "CARD2", "BORDER", "TEXT", "DIM", "SLATE", "SLATE_DARK",
                     "WHITE_PANEL", "FONT", "MONO", "OVERLAY_QR"):
            self.assertTrue(hasattr(ui_theme, name), name)

    def test_window_min_fits_inside_the_default_window(self):
        self.assertLessEqual(ui_theme.WINDOW_MIN[0], ui_theme.WINDOW_SIZE[0])
        self.assertLessEqual(ui_theme.WINDOW_MIN[1], ui_theme.WINDOW_SIZE[1])


class PrimaryActionTests(unittest.TestCase):
    """一屏一颗主按钮：文案随状态变，点下去仍走原来那颗回调。"""

    def setUp(self):
        try:
            import dsh_gui
        except Exception as exc:      # noqa: BLE001 - 缺 GUI 依赖时跳过
            raise unittest.SkipTest("无法导入 GUI：" + str(exc))
        self.gui = dsh_gui

    def test_labels_follow_the_five_phases(self):
        got = {p: self.gui.primary_action(p)[:2] for p in PHASES}
        self.assertEqual(got[status.Phase.STOPPED], ("启动 DSH", "start"))
        self.assertEqual(got[status.Phase.STARTING], ("停止 DSH", "stop"))
        self.assertEqual(got[status.Phase.RUNNING], ("停止 DSH", "stop"))
        self.assertEqual(got[status.Phase.DEGRADED], ("修复/重启", "restart"))
        self.assertEqual(got[status.Phase.UNKNOWN], ("重新探测", "refresh"))

    def test_callback_name_exists_on_the_app(self):
        app = self.gui.ConsoleApp
        for phase in PHASES:
            _label, name, _color, _hover = self.gui.primary_action(phase)
            self.assertTrue(hasattr(app, "on_" + name), name)

    def test_colors_come_from_the_theme(self):
        allowed = {ui_theme.PRIMARY, ui_theme.AMBER, ui_theme.SLATE, ui_theme.RED}
        for phase in PHASES:
            self.assertIn(self.gui.primary_action(phase)[2], allowed, phase)


if __name__ == "__main__":
    unittest.main()
