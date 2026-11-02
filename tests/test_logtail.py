"""日志跟随：只追加新内容、截断重同步、每行都脱敏、行数上限（C2）。"""
import tempfile
import unittest
from pathlib import Path

from dshconsole import logtail, textutil


class FollowerTests(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix="dsh-log-"))
        self.path = self.dir / "dsh-web.stdout.log"

    def write(self, text, mode="a"):
        with self.path.open(mode, encoding="utf-8") as handle:
            handle.write(text)

    def test_first_read_replays_the_existing_tail_then_follows(self):
        self.write("旧行一\n旧行二\n")
        follower = logtail.Follower(self.path)
        self.assertEqual(follower.read(), ["旧行一", "旧行二"])   # 打开窗口前 DSH 说过的话
        self.assertEqual(follower.read(), [])                    # 不会重复
        self.write("新行\n")
        self.assertEqual(follower.read(), ["新行"])

    def test_a_file_bigger_than_the_window_starts_at_the_tail(self):
        self.write("".join(f"第{i}行\n" for i in range(8000)))   # 远超 TAIL_BYTES
        self.assertGreater(self.path.stat().st_size, logtail.TAIL_BYTES)
        follower = logtail.Follower(self.path)
        lines = follower.read()
        self.assertLess(len(lines), 8000)                    # 没有重放整个历史
        self.assertNotIn("\ufffd", lines[0])                 # 头一行那半截被整个丢掉
        self.assertTrue(lines[0].startswith("第"))
        self.assertEqual(lines[-1], "第7999行")

    def test_only_new_content_is_returned(self):
        self.path.write_text("", encoding="utf-8")
        follower = logtail.Follower(self.path)
        follower.read()
        self.write("a\n")
        self.assertEqual(follower.read(), ["a"])
        self.assertEqual(follower.read(), [])       # 没有新内容就什么也不给

    def test_half_line_waits_for_the_rest(self):
        self.path.write_text("", encoding="utf-8")
        follower = logtail.Follower(self.path)
        follower.read()
        self.write("只有半行")
        self.assertEqual(follower.read(), [])
        self.write("补完\n")
        self.assertEqual(follower.read(), ["只有半行补完"])

    def test_truncation_resyncs_from_the_beginning(self):
        self.write("第一行内容长一些\n")            # 比替换后的内容长，才是一次真正的截断
        follower = logtail.Follower(self.path)
        follower.read()
        self.write("新\n", mode="w")               # 文件被截断重写，变小了
        self.assertEqual(follower.read(), [logtail.TRUNCATED_NOTE, "新"])

    def test_missing_file_is_silent(self):
        follower = logtail.Follower(self.dir / "还没出现.log")
        self.assertEqual(follower.read(), [])

    def test_every_line_is_redacted(self):
        self.path.write_text("", encoding="utf-8")
        follower = logtail.Follower(self.path)
        follower.read()
        self.write("dsh web: http://127.0.0.1:3080/?token=abc123\n"
                   "Cookie: session=deadbeef\nsk-proj-ABCDEFG\n")
        lines = follower.read()
        joined = "\n".join(lines)
        self.assertNotIn("abc123", joined)
        self.assertNotIn("deadbeef", joined)
        self.assertNotIn("sk-proj-ABCDEFG", joined)
        self.assertIn("token=****", joined)
        self.assertEqual(joined.count("****"), 3)

    def test_overlong_line_is_truncated(self):
        self.path.write_text("", encoding="utf-8")
        follower = logtail.Follower(self.path)
        follower.read()
        self.write("x" * 5000 + "\n")
        line = follower.read()[0]
        self.assertLess(len(line), logtail.MAX_LINE + 40)
        self.assertIn("本行过长", line)


class LogTailerTests(unittest.TestCase):
    def test_poll_collects_new_lines_from_every_file(self):
        first = Path(tempfile.mkdtemp(prefix="dsh-log-")) / "a.log"
        second = first.with_name("b.log")
        first.write_text("", encoding="utf-8")
        second.write_text("", encoding="utf-8")
        sink = []
        tailer = logtail.LogTailer([first, second], lambda path, lines: sink.append((path, lines)))
        tailer.poll()                                  # 先各自定位到末尾
        first.write_text("来自 a\n", encoding="utf-8")
        second.write_text("来自 b token=zzz\n", encoding="utf-8")
        found = dict(tailer.poll())
        self.assertEqual(found[first], ["来自 a"])
        self.assertEqual(found[second], ["来自 b token=****"])

    def test_interval_has_a_floor_so_it_cannot_busy_loop(self):
        tailer = logtail.LogTailer([], lambda path, lines: None, interval=0.0)
        self.assertGreaterEqual(tailer.interval, 0.3)

    def test_start_and_stop_the_background_thread(self):
        path = Path(tempfile.mkdtemp(prefix="dsh-log-")) / "a.log"
        path.write_text("", encoding="utf-8")
        sink = []
        tailer = logtail.LogTailer([path], lambda p, lines: sink.extend(lines), interval=0.3)
        tailer.start()
        try:
            self.assertTrue(tailer.running)
            with path.open("a", encoding="utf-8") as handle:
                handle.write("后台跟到的一行\n")
            for _ in range(40):
                if sink:
                    break
                threading_wait()
        finally:
            tailer.stop()
        self.assertIn("后台跟到的一行", sink)
        self.assertFalse(tailer.running)


def threading_wait():
    import time
    time.sleep(0.1)


class ReadTailTests(unittest.TestCase):
    def test_read_tail_keeps_only_the_last_lines_and_masks(self):
        path = Path(tempfile.mkdtemp(prefix="dsh-log-")) / "a.log"
        path.write_text("\n".join(f"第{i}行" for i in range(600)) + "token=abc123\n",
                        encoding="utf-8")
        text = logtail.read_tail(path, 10)
        self.assertNotIn("第589行", text)
        self.assertIn("第599行", text)
        self.assertNotIn("abc123", text)

    def test_read_tail_of_a_missing_file_explains_itself(self):
        text = logtail.read_tail(Path(tempfile.mkdtemp()) / "nope.log")
        self.assertIn("读不到", text)


if __name__ == "__main__":
    unittest.main()
