"""托盘卡片的口径：三行状态怎么读、卡片贴哪儿、两击确认什么时候算数。

这些都是纯函数，不建窗口 —— 卡片长什么样交给 tests/shoot_ui.py 那类截图脚本来验。
"""
from __future__ import annotations

import unittest

from dshconsole import status
from dshconsole import traycard


def _st(**kwargs) -> status.Status:
    base = dict(phase=status.Phase.STOPPED, pids=[], port_open=False, phone_open=False)
    base.update(kwargs)
    return status.Status(**base)


class DescribeTests(unittest.TestCase):
    def test_running_shows_pids_and_green(self):
        rows = traycard.describe(_st(phase=status.Phase.RUNNING, pids=[4321]), port=3080)
        self.assertEqual(rows[0].label, "DSH")
        self.assertEqual(rows[0].tone, "ok")
        self.assertIn("PID 4321", rows[0].text)

    def test_more_than_two_pids_says_how_many(self):
        rows = traycard.describe(_st(phase=status.Phase.RUNNING, pids=[1, 2, 3]), port=3080)
        self.assertIn("PID 1、2", rows[0].text)
        self.assertIn("3 个", rows[0].text)

    def test_stopped_is_calm_grey_not_red(self):
        rows = traycard.describe(_st(phase=status.Phase.STOPPED), port=3080)
        self.assertEqual(rows[0].tone, "off")
        self.assertEqual(rows[0].text, "没在跑")

    def test_degraded_names_the_squatter(self):
        st = _st(phase=status.Phase.DEGRADED, port_open=True, serving=True,
                 others=[(41544, r"C:\fake\bin.js")])
        rows = traycard.describe(st, port=3080)
        self.assertEqual(rows[0].tone, "warn")
        self.assertIn("占用 PID 41544", rows[0].text)

    def test_unknown_phase_is_not_reported_as_stopped(self):
        rows = traycard.describe(_st(phase=status.Phase.UNKNOWN, pids=None), port=3080)
        self.assertEqual(rows[0].tone, "off")
        self.assertEqual(rows[0].text, "没查到")

    def test_port_answers_http(self):
        st = _st(phase=status.Phase.RUNNING, pids=[1], port_open=True, serving=True)
        row = traycard.describe(st, port=3080)[1]
        self.assertEqual((row.label, row.tone), ("3080", "ok"))

    def test_port_open_but_silent_is_amber(self):
        st = _st(phase=status.Phase.RUNNING, pids=[1], port_open=True, serving=False)
        self.assertEqual(traycard.describe(st, port=3080)[1].tone, "warn")

    def test_port_open_without_probe_still_admits_it(self):
        st = _st(phase=status.Phase.RUNNING, pids=[1], port_open=True, serving=None)
        row = traycard.describe(st, port=3080)[1]
        self.assertEqual(row.tone, "warn")
        self.assertIn("没测", row.text)

    def test_port_unprobed_is_not_off(self):
        st = _st(phase=status.Phase.UNKNOWN, pids=None, port_open=None)
        self.assertEqual(traycard.describe(st, port=3080)[1].text, "没查到")

    def test_phone_reachable_shows_address(self):
        st = _st(phase=status.Phase.RUNNING, pids=[1], port_open=True, serving=True,
                 phone_open=True, ts_ip="100.124.206.105")
        row = traycard.describe(st, port=3080)[2]
        self.assertEqual(row.tone, "ok")
        self.assertIn("100.124.206.105", row.text)

    def test_residue_outranks_phone_open(self):
        st = _st(phase=status.Phase.RUNNING, pids=[1], port_open=True, serving=True,
                 phone_open=True, residue=True)
        row = traycard.describe(st, port=3080)[2]
        self.assertEqual((row.tone, row.text), ("warn", "转发残留"))

    def test_three_rows_in_fixed_order(self):
        rows = traycard.describe(_st(), port=3080)
        self.assertEqual([row.label for row in rows], ["DSH", "3080", "手机"])


class CardPositionTests(unittest.TestCase):
    WORK = (0, 0, 1920, 1080)

    def test_sits_above_the_cursor(self):
        x, y = traycard.card_position((1000, 800), (300, 260), self.WORK)
        self.assertEqual((x, y), (718, 532))

    def test_right_edge_is_clamped_inside_the_work_area(self):
        x, _y = traycard.card_position((1910, 1070), (300, 260), self.WORK)
        self.assertEqual(x, 1620)

    def test_top_edge_is_clamped_not_off_screen(self):
        _x, y = traycard.card_position((1005, 10), (300, 260), self.WORK)
        self.assertEqual(y, 0)

    def test_work_area_narrower_than_the_card_pins_top_left(self):
        self.assertEqual(traycard.card_position((100, 100), (300, 260), (0, 0, 200, 200)),
                         (0, 0))

    def test_second_monitor_uses_its_own_work_area(self):
        x, y = traycard.card_position((3000, 900), (300, 260), (1920, 0, 3840, 1040))
        self.assertEqual((x, y), (2718, 632))

    def test_cursor_near_a_monitors_left_edge_pins_to_that_monitor(self):
        x, _y = traycard.card_position((2100, 900), (300, 260), (1920, 0, 3840, 1040))
        self.assertEqual(x, 1920)     # 不越回左屏，卡片留在这块屏上


class RepeatConfirmTests(unittest.TestCase):
    def test_first_press_only_arms(self):
        confirm = traycard.RepeatConfirm("停止 DSH", "再点一次确认停止")
        self.assertFalse(confirm.press(100.0))
        self.assertEqual(confirm.text(100.1), "再点一次确认停止")

    def test_second_press_inside_the_window_confirms(self):
        confirm = traycard.RepeatConfirm("停止 DSH", "再点一次确认停止")
        confirm.press(100.0)
        self.assertTrue(confirm.press(101.5))
        self.assertEqual(confirm.text(101.6), "停止 DSH")

    def test_expired_window_falls_back_to_arming(self):
        confirm = traycard.RepeatConfirm("停止 DSH", "再点一次确认停止", window=2.0)
        confirm.press(100.0)
        self.assertFalse(confirm.press(102.5))
        self.assertEqual(confirm.text(102.6), "再点一次确认停止")

    def test_reset_disarms(self):
        confirm = traycard.RepeatConfirm("退出", "再点一次确认退出")
        confirm.press(1.0)
        confirm.reset()
        self.assertFalse(confirm.armed(1.1))


if __name__ == "__main__":
    unittest.main()
