"""dshconsole.children 的单元测试：记账、原子写、状态机、遗留判定。

这里最贵的一条是「PID 被复用」：账本里的号还在，但那个号现在跑的是别的程序。
所以遗留判定只能拿「当前真的走同一个 bin.js 的 pid 集合」去比对，
不能只看进程号是否存在。
"""
from __future__ import annotations

import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from dshconsole import children


class LedgerPathTests(unittest.TestCase):
    def test_path_follows_config_location(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = Path(tmp) / "config.json"
            with mock.patch.dict(os.environ, {"DSH_CONSOLE_CONFIG": str(cfg)}):
                self.assertEqual(children.path(), Path(tmp) / children.LEDGER_NAME)


class LedgerRoundTripTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.target = Path(self._tmp.name) / children.LEDGER_NAME

    def tearDown(self):
        self._tmp.cleanup()

    def test_record_then_load(self):
        self.assertTrue(children.record(100, [11, 12], target=self.target, bin_js="C:/x/bin.js"))
        ledger = children.load(self.target)
        self.assertEqual(ledger["consolePid"], 100)
        self.assertEqual(ledger["status"], children.STATUS_RUNNING)
        self.assertEqual(ledger["binJs"], "C:/x/bin.js")
        self.assertEqual([e["pid"] for e in children.entries(ledger)], [11, 12])

    def test_record_skips_self_and_garbage(self):
        children.record(100, [100, 0, -3, "12", "abc", None], target=self.target)
        self.assertEqual([e["pid"] for e in children.entries(children.load(self.target))], [12])

    def test_record_accepts_dicts_and_keeps_started_at(self):
        children.record(100, [{"pid": 7, "startedAt": 1000.0}, {"pid": 8}], target=self.target)
        items = children.entries(children.load(self.target))
        self.assertEqual(items[0], {"pid": 7, "startedAt": 1000.0})
        self.assertGreater(items[1]["startedAt"], 0.0)

    def test_record_leaves_no_temp_files(self):
        children.record(100, [11], target=self.target)
        leftovers = [p.name for p in self.target.parent.iterdir() if p.name != self.target.name]
        self.assertEqual(leftovers, [])

    def test_load_rejects_broken_or_foreign_ledger(self):
        self.assertIsNone(children.load(self.target))              # 文件不存在
        self.target.write_text("{not json", encoding="utf-8")
        self.assertIsNone(children.load(self.target))
        self.target.write_text(json.dumps({"version": 99}), encoding="utf-8")
        self.assertIsNone(children.load(self.target))

    def test_write_failure_is_swallowed(self):
        blocked = Path(self._tmp.name) / "file-not-dir"
        blocked.write_text("x", encoding="utf-8")
        self.assertFalse(children.record(100, [11], target=blocked / children.LEDGER_NAME))


class LedgerMarkTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.target = Path(self._tmp.name) / children.LEDGER_NAME
        children.record(100, [11], target=self.target)

    def tearDown(self):
        self._tmp.cleanup()

    def test_mark_updates_status(self):
        self.assertTrue(children.mark(children.STATUS_LEFT, target=self.target))
        self.assertEqual(children.load(self.target)["status"], children.STATUS_LEFT)

    def test_mark_refuses_other_console_ledger(self):
        self.assertFalse(children.mark(children.STATUS_STOPPED, target=self.target, console_pid=999))
        self.assertEqual(children.load(self.target)["status"], children.STATUS_RUNNING)

    def test_stopped_is_final_for_left(self):
        children.mark(children.STATUS_STOPPED, target=self.target)
        self.assertFalse(children.mark(children.STATUS_LEFT, target=self.target))
        self.assertEqual(children.load(self.target)["status"], children.STATUS_STOPPED)

    def test_mark_without_ledger_is_false(self):
        self.assertFalse(children.mark(children.STATUS_LEFT, target=Path(self._tmp.name) / "none.json"))


class LeftoversTests(unittest.TestCase):
    def ledger(self, console_pid=100, status=children.STATUS_LEFT, pids=(11, 12)):
        return {"version": children.VERSION, "consolePid": console_pid, "status": status,
                "updatedAt": time.time(), "dsh": [{"pid": p, "startedAt": 1000.0} for p in pids]}

    def test_alive_leftover_is_reported(self):
        items = children.leftovers(self.ledger(), [11, 12], current_pid=200)
        self.assertEqual([i["pid"] for i in items], [11, 12])

    def test_dead_pid_is_not_a_leftover(self):
        self.assertEqual(children.leftovers(self.ledger(), [12], current_pid=200)[0]["pid"], 12)
        self.assertEqual(children.leftovers(self.ledger(), [], current_pid=200), [])

    def test_pid_reuse_is_not_a_leftover(self):
        # 号还在，但它已经不属于 DSH：alive 集合由 dsh_processes 按 bin.js 判定，这里就是空的。
        self.assertEqual(children.leftovers(self.ledger(), [999], current_pid=200), [])

    def test_own_ledger_is_not_a_leftover(self):
        self.assertEqual(children.leftovers(self.ledger(console_pid=100), [11], current_pid=100), [])

    def test_stopped_ledger_never_warns(self):
        ledger = self.ledger(status=children.STATUS_STOPPED)
        self.assertEqual(children.leftovers(ledger, [11, 12], current_pid=200), [])

    def test_garbage_inputs_are_empty(self):
        self.assertEqual(children.leftovers(None, [11], current_pid=1), [])
        self.assertEqual(children.leftovers({}, [11], current_pid=1), [])
        self.assertEqual(children.leftovers({"consolePid": "x", "dsh": "nope"}, [11], current_pid=1), [])
        self.assertEqual(children.leftovers(self.ledger(), None, current_pid=200), [])

    def test_describe_mentions_pid(self):
        self.assertIn("PID 11", children.describe({"pid": 11, "startedAt": 1000.0}))


if __name__ == "__main__":
    unittest.main()
