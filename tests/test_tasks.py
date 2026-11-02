"""命令队列：串行、可取消排队中的任务、失败不拖死队列（C5）。"""
import threading
import unittest

from dshconsole import tasks


class SubmitTests(unittest.TestCase):
    def test_task_runs_and_lands_in_done(self):
        queue = tasks.TaskQueue()
        done = []
        task = queue.submit("干活", lambda: 42, on_done=done.append)
        self.assertTrue(queue.wait_idle(5))
        self.assertIs(task.state, tasks.State.DONE)
        self.assertEqual(task.result, 42)
        self.assertEqual(done, [task])

    def test_failure_is_captured_and_the_queue_keeps_going(self):
        queue = tasks.TaskQueue()
        boom = queue.submit("会炸", lambda: 1 / 0)
        after = queue.submit("还得跑", lambda: "ok")
        self.assertTrue(queue.wait_idle(5))
        self.assertIs(boom.state, tasks.State.FAILED)
        self.assertIsInstance(boom.error, ZeroDivisionError)
        self.assertIs(after.state, tasks.State.DONE)
        self.assertEqual(after.result, "ok")


class CancelTests(unittest.TestCase):
    def test_only_queued_tasks_can_be_cancelled(self):
        gate = threading.Event()
        queue = tasks.TaskQueue()
        first = queue.submit("慢的", gate.wait)
        second = queue.submit("排队的", lambda: "不该跑")
        try:
            for _ in range(50):
                if queue.running is first:
                    break
                threading.Event().wait(0.02)
            self.assertFalse(queue.cancel(first.id))       # 正在执行：不强杀
            self.assertTrue(queue.cancel(second.id))
            self.assertIs(second.state, tasks.State.CANCELLED)
        finally:
            gate.set()
        self.assertTrue(queue.wait_idle(5))
        self.assertIs(first.state, tasks.State.DONE)
        self.assertIsNone(second.result)                    # 取消了就是没跑

    def test_cancel_all_pending_reports_how_many(self):
        gate = threading.Event()
        queue = tasks.TaskQueue()
        queue.submit("慢的", gate.wait)
        for index in range(3):
            queue.submit(f"排队{index}", lambda: None)
        try:
            for _ in range(50):
                if len(queue.pending()) == 3:
                    break
                threading.Event().wait(0.02)
            self.assertEqual(queue.cancel_all_pending(), 3)
            self.assertEqual(queue.pending(), [])
        finally:
            gate.set()
        queue.wait_idle(5)


class DescribeTests(unittest.TestCase):
    def test_describe_says_how_many_are_ahead(self):
        gate = threading.Event()
        queue = tasks.TaskQueue()
        first = queue.submit("第一个", gate.wait)
        second = queue.submit("第二个", lambda: None)
        third = queue.submit("第三个", lambda: None)
        try:
            self.assertEqual(queue.describe(second), "第二个：排队中（前面还有 1 个）")
            self.assertEqual(queue.describe(third), "第三个：排队中（前面还有 2 个）")
            self.assertEqual(queue.ahead(second), 1)
        finally:
            gate.set()
        queue.wait_idle(5)
        self.assertEqual(queue.describe(first), "第一个：成功")

    def test_on_change_fires_for_submit_start_and_finish(self):
        calls = []
        queue = tasks.TaskQueue(on_change=lambda: calls.append("change"))
        queue.submit("干活", lambda: None)
        queue.wait_idle(5)
        self.assertGreaterEqual(len(calls), 3)      # 入队 / 开始 / 结束

    def test_state_labels_are_the_user_facing_words(self):
        self.assertEqual(tasks.State.QUEUED.label, "排队中")
        self.assertEqual(tasks.State.RUNNING.label, "执行中")
        self.assertEqual(tasks.State.DONE.label, "成功")
        self.assertEqual(tasks.State.FAILED.label, "失败")
        self.assertEqual(tasks.State.CANCELLED.label, "已取消")


if __name__ == "__main__":
    unittest.main()
