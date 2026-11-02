"""异常显式化：脱敏、截断、三处钩子都要真的接上。"""
import io
import sys
import threading
import unittest
from contextlib import redirect_stderr
from types import SimpleNamespace

from dshconsole import errors


def _boom(message: str = "boom"):
    try:
        raise ValueError(message)
    except ValueError as exc:
        return type(exc), exc, exc.__traceback__


class SummarizeTests(unittest.TestCase):
    def test_includes_type_message_and_traceback(self):
        text = errors.summarize(*_boom())
        self.assertIn("ValueError: boom", text)
        self.assertIn("Traceback (most recent call last)", text)

    def test_secret_in_message_is_redacted(self):
        exc_type, exc, tb = _boom("GET /?token=abc123 失败")
        text = errors.summarize(exc_type, exc, tb)
        self.assertNotIn("abc123", text)
        self.assertIn("token=****", text)

    def test_long_text_is_truncated_with_marker(self):
        exc_type, exc, tb = _boom("x" * 5000)
        text = errors.summarize(exc_type, exc, tb, max_chars=120)
        self.assertTrue(text.startswith(errors.TRUNCATED))
        self.assertLessEqual(len(text), len(errors.TRUNCATED) + 120)

    def test_limit_keeps_only_tail_frames(self):
        exc_type, exc, tb = _boom()
        text = errors.summarize(exc_type, exc, tb, limit=1)
        self.assertIn("ValueError", text)

    def test_broken_exc_type_does_not_raise(self):
        text = errors.summarize(object, object(), None)
        self.assertTrue(text)


class InstallTests(unittest.TestCase):
    def setUp(self):
        self.seen = []
        self.old_sys = sys.excepthook
        self.old_thread = threading.excepthook
        errors.install(self.seen.append)

    def tearDown(self):
        sys.excepthook = self.old_sys
        threading.excepthook = self.old_thread

    def test_sys_hook_writes_redacted_traceback(self):
        sys.excepthook(*_boom("token=zzz9"))
        self.assertEqual(len(self.seen), 1)
        self.assertIn("未捕获异常", self.seen[0])
        self.assertIn("ValueError", self.seen[0])
        self.assertNotIn("zzz9", self.seen[0])

    def test_keyboard_interrupt_is_not_an_error(self):
        sys.excepthook(KeyboardInterrupt, KeyboardInterrupt(), None)
        self.assertEqual(self.seen, [])

    def test_thread_hook_names_the_thread(self):
        args = SimpleNamespace(exc_type=RuntimeError, exc_value=RuntimeError("后台"),
                               exc_traceback=None,
                               thread=SimpleNamespace(name="worker-7"))
        threading.excepthook(args)
        self.assertEqual(len(self.seen), 1)
        self.assertIn("后台线程异常（worker-7）", self.seen[0])
        self.assertIn("RuntimeError: 后台", self.seen[0])

    def test_system_exit_in_thread_is_ignored(self):
        args = SimpleNamespace(exc_type=SystemExit, exc_value=SystemExit(0),
                               exc_traceback=None, thread=SimpleNamespace(name="t"))
        threading.excepthook(args)
        self.assertEqual(self.seen, [])

    def test_broken_sink_falls_back_to_stderr(self):
        def sink(_text):
            raise RuntimeError("日志框坏了")
        errors.install(sink)
        buffer = io.StringIO()
        with redirect_stderr(buffer):
            sys.excepthook(*_boom())
        self.assertIn("ValueError: boom", buffer.getvalue())


if __name__ == "__main__":
    unittest.main()
