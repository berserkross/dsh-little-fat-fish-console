"""dshconsole.actions 的单元测试：落盘现场、逐步记步、收尾抹掉、写不进去不拦人。"""
from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from dshconsole import actions


class ActionBookTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.book = Path(self._tmp.name) / actions.FILE_NAME
        patcher = mock.patch.object(actions, "path", return_value=self.book)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_begin_records_name_step_and_pid(self):
        actions.begin("重启 DSH", "查 DSH 进程")
        payload = actions.read()
        self.assertEqual(payload["name"], "重启 DSH")
        self.assertEqual(payload["step"], "查 DSH 进程")
        self.assertEqual(payload["pid"], os.getpid())
        self.assertGreater(payload["startedAt"], 0)

    def test_step_only_moves_the_bookmark(self):
        actions.begin("重启 DSH", "查 DSH 进程")
        actions.step("等端口关闭")
        payload = actions.read()
        self.assertEqual(payload["name"], "重启 DSH")
        self.assertEqual(payload["step"], "等端口关闭")

    def test_finish_leaves_nothing_behind(self):
        actions.begin("重启 DSH", "查 DSH 进程")
        actions.finish()
        self.assertIsNone(actions.read())
        self.assertIsNone(actions.unfinished())

    def test_unfinished_describes_where_it_broke(self):
        actions.begin("重启 DSH", "等端口关闭")
        text = actions.describe(actions.unfinished())
        self.assertIn("重启 DSH", text)
        self.assertIn("等端口关闭", text)
        self.assertIn("没有正常收尾", text)

    def test_step_without_a_begin_is_ignored(self):
        actions.step("等端口关闭")
        self.assertIsNone(actions.read())

    def test_a_new_action_replaces_the_old_book(self):
        actions.begin("重启 DSH", "查 DSH 进程")
        actions.begin("关闭 DSH", "等端口关闭")
        payload = actions.read()
        self.assertEqual((payload["name"], payload["step"]), ("关闭 DSH", "等端口关闭"))

    def test_unwritable_book_never_raises(self):
        blocker = Path(self._tmp.name) / "blocker"
        blocker.write_text("x", encoding="utf-8")
        with mock.patch.object(actions, "path", return_value=blocker / actions.FILE_NAME):
            actions.begin("重启 DSH", "查 DSH 进程")        # 目录建不出来，也不许抛
            actions.finish()
            self.assertIsNone(actions.read())


if __name__ == "__main__":
    unittest.main()
