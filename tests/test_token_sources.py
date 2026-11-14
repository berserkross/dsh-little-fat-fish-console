"""token 采集：日志可能有两份，取最新写入那份的最后一条。

控制台自己拉起 DSH 时写 harness/dsh-web.stdout.log；别的会话用 dsh-power-xc 的
restart_harness 重启时改道写 DSH_HOME/dsh-web.log（lib/index.js:297 的 serverLog）。
只认前者，3081 就会一直跳一把死钥匙。
"""
import os
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace

import dsh_gui


class TokenSourceTests(unittest.TestCase):
    def setUp(self):
        self._log, self._cfg = dsh_gui.TOKEN_LOG, dsh_gui.CFG
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.stdout_log = self.root / "dsh-web.stdout.log"
        dsh_gui.TOKEN_LOG = self.stdout_log
        dsh_gui.CFG = SimpleNamespace(dsh_home=self.root)

    def tearDown(self):
        dsh_gui.TOKEN_LOG, dsh_gui.CFG = self._log, self._cfg
        self._tmp.cleanup()

    def write(self, path: Path, token: str, age: float = 0.0) -> Path:
        path.write_text(f"dsh web: http://127.0.0.1:{dsh_gui.PORT}/?token={token}\n",
                        encoding="utf-8")
        if age:
            stamp = time.time() - age
            os.utime(path, (stamp, stamp))
        return path

    def test_harness_log_used_when_it_is_the_only_one(self):
        self.write(self.stdout_log, "from-stdout")
        self.assertEqual(dsh_gui.token_url(),
                         f"http://127.0.0.1:{dsh_gui.PORT}/?token=from-stdout")

    def test_dsh_home_log_wins_when_it_is_newer(self):
        self.write(self.stdout_log, "stale-token", age=600)
        self.write(self.root / "dsh-web.log", "restarted-token")
        self.assertEqual(dsh_gui.token_suffix(dsh_gui.token_url() or ""), "restarted-token")

    def test_stdout_log_wins_when_it_is_newer(self):
        self.write(self.root / "dsh-web.log", "old-external", age=600)
        self.write(self.stdout_log, "fresh-console")
        self.assertEqual(dsh_gui.token_suffix(dsh_gui.token_url() or ""), "fresh-console")

    def test_missing_files_are_skipped_not_fatal(self):
        self.write(self.root / "dsh-web.log", "only-home")
        self.assertEqual(dsh_gui.token_suffix(dsh_gui.token_url() or ""), "only-home")

    def test_no_logs_means_no_url(self):
        self.assertIsNone(dsh_gui.token_url())

    def test_only_lines_for_the_configured_port_count(self):
        self.stdout_log.write_text(
            "dsh web: http://127.0.0.1:3999/?token=wrong-port\n", encoding="utf-8")
        self.assertIsNone(dsh_gui.token_url())

    def test_last_line_wins_within_one_log(self):
        self.stdout_log.write_text(
            f"dsh web: http://127.0.0.1:{dsh_gui.PORT}/?token=first\n"
            f"dsh web: http://127.0.0.1:{dsh_gui.PORT}/?token=second\n", encoding="utf-8")
        self.assertEqual(dsh_gui.token_suffix(dsh_gui.token_url() or ""), "second")


if __name__ == "__main__":
    unittest.main()
