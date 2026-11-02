"""界面主题与主操作映射（批次 D）：只验「长什么样、点哪颗」，不建窗口。"""
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
        dots = [ui_theme.PHASE_STYLE[p].dot for p in PHASES]
        self.assertEqual(len(set(dots)), len(PHASES), dots)
        self.assertTrue(all(dot.strip() for dot in dots))

    def test_sweep_is_a_ratio(self):
        for phase in PHASES:
            sweep = ui_theme.PHASE_STYLE[phase].sweep
            self.assertGreater(sweep, 0.0, phase)
            self.assertLessEqual(sweep, 1.0, phase)
        # 启动中 / 未知是「没走满的环」：环的完整度本身也是信息
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
    def test_ring_is_about_120px(self):
        self.assertEqual(ui_theme.RING_SIZE, 120)
        self.assertLess(ui_theme.RING_THICKNESS, ui_theme.RING_SIZE / 2)

    def test_log_defaults_to_15_rows(self):
        self.assertEqual(ui_theme.LOG_ROWS_COLLAPSED, 15)
        self.assertGreater(ui_theme.LOG_LINE_PX, 0)

    def test_overlay_and_drawer_sizes_are_positive(self):
        for width, height in (ui_theme.OVERLAY_QR, ui_theme.OVERLAY_LOG):
            self.assertGreater(width, 0)
            self.assertGreater(height, 0)
        self.assertGreater(ui_theme.DRAWER_WIDTH, 0)
        self.assertGreater(ui_theme.DRAWER_ROW_HEIGHT, 0)


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
