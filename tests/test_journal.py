"""dshconsole.journal 的单元测试：落盘、轮换、失败静默、尾巴读取。"""
from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from dshconsole import journal


class JournalPathTests(unittest.TestCase):
    def test_path_follows_config_location(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = Path(tmp) / "config.json"
            with mock.patch.dict(os.environ, {"DSH_CONSOLE_CONFIG": str(cfg)}):
                self.assertEqual(journal.path(), Path(tmp) / journal.LOG_NAME)


class JournalWriteTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.target = Path(self._tmp.name) / "console.log"

    def tearDown(self):
        self._tmp.cleanup()

    def test_write_appends_timestamped_line(self):
        journal.write("重启②：端口已关闭", target=self.target)
        journal.write("启动完成", target=self.target)
        rows = self.target.read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(rows), 2)
        self.assertRegex(rows[0], r"^\[\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\] 重启②：端口已关闭$")
        self.assertTrue(rows[1].endswith("启动完成"))

    def test_multiline_is_one_stamped_entry_per_call(self):
        journal.write("第一行\n第二行\n", target=self.target)
        text = self.target.read_text(encoding="utf-8")
        self.assertTrue(text.endswith("第一行\n第二行\n"))
        self.assertEqual(text.count("["), 1, "一次写入只盖一个时间戳")

    def test_token_is_redacted_on_disk(self):
        journal.write("已直接拉起：http://127.0.0.1:3080/?token=SECRET123", target=self.target)
        text = self.target.read_text(encoding="utf-8")
        self.assertNotIn("SECRET123", text)

    def test_rotates_when_too_big(self):
        self.target.write_text("x" * (journal.ROTATE_BYTES + 1), encoding="utf-8")
        journal.write("新的开始", target=self.target)
        backup = self.target.with_name(self.target.name + ".1")
        self.assertTrue(backup.is_file(), "超限要先换一份，不能无限长")
        self.assertIn("新的开始", self.target.read_text(encoding="utf-8"))

    def test_unwritable_target_does_not_raise(self):
        # 目录不存在且无法创建：旁证写不进去也绝不能反过来把界面搞崩
        bad = Path(tempfile.gettempdir()) / "no-such-dir-journal" / "x" / "console.log"
        with mock.patch("pathlib.Path.mkdir", side_effect=OSError("denied")):
            journal.write("随便", target=bad)


class JournalTailTests(unittest.TestCase):
    def test_tail_returns_last_nonempty_lines(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "dsh-web.stderr.log"
            path.write_text("a\n\n b\n c\n\n", encoding="utf-8")
            self.assertEqual(journal.tail_lines(path, 2), [" b", " c"])

    def test_tail_of_missing_file_is_empty(self):
        self.assertEqual(journal.tail_lines(None), [])
        self.assertEqual(journal.tail_lines("C:/definitely/not/here.log"), [])


if __name__ == "__main__":
    unittest.main()
