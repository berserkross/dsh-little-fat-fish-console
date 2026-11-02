"""单实例守卫：互斥体判重、降级路径、找窗口失败不抛。"""
import types
import unittest
from unittest import mock

from dshconsole import single


class GuardTests(unittest.TestCase):
    def test_blocked_property(self):
        self.assertTrue(single.Guard(False, "已在运行").blocked)
        self.assertFalse(single.Guard(True).blocked)
        self.assertFalse(single.Guard(None, "跳过").blocked)

    def test_non_windows_degrades_instead_of_blocking(self):
        with mock.patch.object(single, "os", types.SimpleNamespace(name="posix")):
            guard = single.acquire()
        self.assertIsNone(guard.acquired)
        self.assertFalse(guard.blocked)
        self.assertIn("非 Windows", guard.reason)

    @unittest.skipUnless(single.os.name == "nt", "只在 Windows 上验证命名互斥体")
    def test_second_acquire_in_same_process_is_blocked(self):
        first = single.acquire("Local\\DshConsole.UnitTest")
        self.assertTrue(first.acquired)
        self.assertIsNotNone(single._HANDLE)          # 句柄保活：不能被回收
        second = single.acquire("Local\\DshConsole.UnitTest")
        self.assertFalse(second.acquired)
        self.assertTrue(second.blocked)
        self.assertIn("已经有一个", second.reason)

    def test_focus_window_without_such_title_returns_false(self):
        self.assertFalse(single.focus_window("绝对不存在的窗口标题-DSH-自检"))

    def test_focus_window_off_windows_returns_false(self):
        with mock.patch.object(single, "os", types.SimpleNamespace(name="posix")):
            self.assertFalse(single.focus_window("任何标题"))


if __name__ == "__main__":
    unittest.main()
