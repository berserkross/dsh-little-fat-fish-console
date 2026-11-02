"""托盘：可用性探测、菜单文案、动作一律投递回主线程、失败要降级（C1）。"""
import sys
import threading
import time
import unittest
from types import SimpleNamespace
from unittest import mock

from dshconsole import tray


class FakeMenuItem:
    def __init__(self, text, action, default=False):
        self.text = text
        self.action = action
        self.default = default


class FakeIcon:
    def __init__(self, name, image, title, menu):
        self.name = name
        self.image = image
        self.title = title
        self.menu = menu
        self.stopped = False
        self.run_error = None

    def run(self):
        if self.run_error is not None:
            raise self.run_error
        self.stopped = True

    def stop(self):
        self.stopped = True

    def update_menu(self):
        pass


def fake_pystray(icon_cls=FakeIcon):
    return SimpleNamespace(Icon=icon_cls, MenuItem=FakeMenuItem,
                           Menu=lambda *items: list(items))


class AvailabilityTests(unittest.TestCase):
    def test_result_is_a_pair_and_failures_explain_themselves(self):
        ok, why = tray.available()
        self.assertIsInstance(ok, bool)
        if ok:
            self.assertIsNone(why)
        else:
            self.assertIn("托盘库", why)

    def test_a_missing_library_degrades_instead_of_crashing(self):
        with mock.patch.dict(sys.modules, {"pystray": None}):
            ok, why = tray.available()
            self.assertFalse(ok)
            self.assertIn("托盘库", why)
            started, reason = tray.Tray().start([("退出", lambda: None)])
        self.assertFalse(started)
        self.assertIn("托盘库", reason)
        self.assertFalse(tray.Tray().running)


class MenuTests(unittest.TestCase):
    def test_labels_may_be_callables_and_take_the_menu_item(self):
        # 真实 bug：pystray 以 text(item) 调用，零参 callable 会 TypeError。
        t = tray.Tray()
        t._items = [(lambda: "显示主窗口", lambda: None), ("退出", lambda: None)]
        menu = t._menu(fake_pystray())
        self.assertEqual(menu[0].text(menu[0]), "显示主窗口")
        self.assertEqual(menu[1].text(menu[1]), "退出")
        self.assertTrue(menu[0].default)
        self.assertFalse(menu[1].default)

    def test_actions_are_posted_to_the_main_thread_not_run_in_the_tray_thread(self):
        posted = []
        t = tray.Tray(post=lambda fn, *args: posted.append(fn))
        ran = []
        t._items = [("退出", lambda: ran.append("退出"))]
        menu = t._menu(fake_pystray())
        menu[0].action(None, menu[0])
        self.assertEqual(ran, [])              # 托盘线程没有直接碰界面
        self.assertEqual(len(posted), 1)       # 只是把动作交给主线程
        posted[0]()                            # 主线程执行时它才真的跑
        self.assertEqual(ran, ["退出"])

    def test_update_menu_without_an_icon_is_a_no_op(self):
        tray.Tray().update_menu([("退出", lambda: None)])      # 不该抛


class LifecycleTests(unittest.TestCase):
    def test_a_tray_thread_that_dies_reports_back(self):
        events = []
        fake = fake_pystray()
        with mock.patch.dict(sys.modules, {"pystray": fake}):
            t = tray.Tray(post=lambda fn, *args: events.append(fn(*args)),
                          on_lost=lambda reason: events.append(reason))
            started, why = t.start([("退出", lambda: None)])
            self.assertTrue(started)
            self.assertIsNone(why)
            t._icon.run_error = RuntimeError("boom")
            t._thread = threading.Thread(target=t._run, daemon=True)
            t._thread.start()
            for _ in range(50):
                if events:
                    break
                time.sleep(0.02)
        self.assertIn("托盘不可用（boom）", events)
        self.assertIn("boom", t.reason)

    def test_stop_is_safe_before_start_and_idempotent(self):
        t = tray.Tray()
        t.stop()
        t.stop()
        self.assertFalse(t.running)

    def test_running_reflects_whether_an_icon_exists(self):
        t = tray.Tray()
        self.assertFalse(t.running)
        t._icon = FakeIcon("x", None, "t", [])
        self.assertTrue(t.running)
        t.stop()
        self.assertFalse(t.running)


if __name__ == "__main__":
    unittest.main()
