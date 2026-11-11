"""阶段 0 生命周期回归：停止清理、启动守卫、重启中止、进程未知判定。

全部注入式：不碰真机、不启停 DSH、不弹窗。FakeApp 只实现生命周期路径用到的口，
其余按需以实例属性注入（与 tests/test_gui_hooks.py 同一模式）。
"""
import unittest
from unittest import mock

try:
    import dsh_gui
except Exception as exc:  # noqa: BLE001 - 缺 GUI 依赖时跳过
    raise unittest.SkipTest("无法导入 GUI：" + str(exc))

from types import SimpleNamespace

from dshconsole import probe, psrun, single


def _ok_result() -> psrun.PsResult:
    return psrun.PsResult(ok=True, code=0, stdout="done", stderr="", error=None)


def _fail_result(why: str = "cancelled by user") -> psrun.PsResult:
    return psrun.PsResult(ok=False, code=1, stdout="", stderr=why, error=None)


class FakeApp:
    """够用的替身：只实现 _stop/_start/_restart 走到断言的路径所需。"""

    def __init__(self):
        self.logged = []
        self._pids_provider = lambda: (None, "not wired")
        self._port_open = lambda: False
        self._run_switch = lambda *a, **kw: None
        self._ask_main = lambda fn, *args: None
        self.switch_calls: list = []

    def log_async(self, text):
        self.logged.append(text)

    def refresh(self, force=False):
        pass

    def _cleanup_residue(self):
        dsh_gui.ConsoleApp._cleanup_residue(self)

    def _port_owner_text(self):
        return "占用者未知"


def _record_switch(app, result):
    """把 _run_switch 换成记录器：记下 (script, args, kwargs) 并返回给定结果。"""

    def recorder(script, *args, **kw):
        app.switch_calls.append((script, args, kw))
        return result

    return recorder


class StopCleanupTests(unittest.TestCase):
    """_stop() 的转发残留清理路径（P1 修复所在）。"""

    app_cls = dsh_gui.ConsoleApp

    def _residue_app(self, switch_result=None):
        app = FakeApp()
        app._port_open = lambda: True           # 端口被转发占着：停止后仍"在线"
        app._pids_provider = lambda: ([], None)  # 但本机 DSH 进程已经没了
        app._run_switch = _record_switch(app, switch_result)
        return app

    def test_stop_with_residue_runs_cleanup(self):
        app = self._residue_app(switch_result=_ok_result())
        with mock.patch.object(dsh_gui.probe, "portproxy_targets",
                               lambda port: (["127.0.0.1"], None)), \
             mock.patch.object(dsh_gui.time, "sleep", lambda _s: None):
            self.app_cls._stop(app, [])
        self.assertEqual(len(app.switch_calls), 1)
        _script, args, kw = app.switch_calls[0]
        self.assertIn("-CleanupOnly", args)
        self.assertIn("-NoPause", args)
        self.assertEqual(kw.get("timeout"), 120)

    def test_stop_cleanup_success_is_logged(self):
        app = self._residue_app(switch_result=_ok_result())
        with mock.patch.object(dsh_gui.probe, "portproxy_targets",
                               lambda port: (["127.0.0.1"], None)), \
             mock.patch.object(dsh_gui.time, "sleep", lambda _s: None):
            self.app_cls._stop(app, [])
        self.assertTrue(any("端口转发残留清理完成" in line for line in app.logged))

    def test_stop_cleanup_failure_is_logged_not_claimed_done(self):
        # P1：用户取消 UAC 时 _run_switch 返回失败——当前代码仍无条件报"完成"，
        # 这条用例先红，修完返回值接取后转绿。
        app = self._residue_app(switch_result=_fail_result("用户取消了 UAC"))
        with mock.patch.object(dsh_gui.probe, "portproxy_targets",
                               lambda port: (["127.0.0.1"], None)), \
             mock.patch.object(dsh_gui.time, "sleep", lambda _s: None):
            self.app_cls._stop(app, [])
        self.assertTrue(any("端口转发残留清理失败" in line for line in app.logged),
                        "失败必须如实上报，实际日志：" + " | ".join(app.logged))
        self.assertFalse(any("端口转发残留清理完成" in line for line in app.logged))

    def test_stop_cleanup_probe_failure_skips_cleanup(self):
        app = self._residue_app()
        with mock.patch.object(dsh_gui.probe, "portproxy_targets",
                               lambda port: (None, "端口转发查询失败")), \
             mock.patch.object(dsh_gui.time, "sleep", lambda _s: None):
            self.app_cls._stop(app, [])
        self.assertEqual(app.switch_calls, [])
        self.assertTrue(any("查不到" in line for line in app.logged))


class SelfKillGuardTests(unittest.TestCase):
    """_stop()：PID 会被系统回收 —— 永远不许对控制台自己的 PID 动手。"""

    app_cls = dsh_gui.ConsoleApp

    def test_own_pid_is_skipped(self):
        import os

        app = FakeApp()
        app._port_open = lambda: False
        killed = []

        def fake_run(cmd, **kw):
            killed.append(cmd)
            return _ok_result()

        with mock.patch.object(dsh_gui.psrun, "run_ps_cmd", fake_run), \
             mock.patch.object(dsh_gui.time, "sleep", lambda _s: None):
            self.app_cls._stop(app, [os.getpid()])
        self.assertEqual(killed, [], "对自己执行 Stop-Process 等于「点重启把窗口关了」")
        self.assertTrue(any("控制台自己" in line for line in app.logged))

    def test_other_pid_still_stopped(self):
        app = FakeApp()
        app._port_open = lambda: False
        killed = []

        def fake_run(cmd, **kw):
            killed.append(cmd)
            return _ok_result()

        with mock.patch.object(dsh_gui.psrun, "run_ps_cmd", fake_run), \
             mock.patch.object(dsh_gui.time, "sleep", lambda _s: None):
            self.app_cls._stop(app, [4242])
        self.assertEqual(len(killed), 1)
        self.assertIn("4242", killed[0])


class StartGuardTests(unittest.TestCase):
    """_start()：端口在线时无论 force 都不再拉第二份。"""

    app_cls = dsh_gui.ConsoleApp

    def test_start_refuses_when_port_open(self):
        for force in (False, True):
            with self.subTest(force=force):
                app = FakeApp()
                app._port_open = lambda: True
                with mock.patch.object(self.app_cls, "_start_direct") as direct:
                    self.app_cls._start(app, force=force)
                direct.assert_not_called()
                self.assertTrue(any("已在监听" in line for line in app.logged))
                self.assertTrue(any("占用者未知" in line for line in app.logged))


class RestartAbortTests(unittest.TestCase):
    """_restart()：端口被占但认不出本机 PID 时中止，绝不叠加启动。"""

    app_cls = dsh_gui.ConsoleApp

    def test_restart_aborts_when_port_open_without_pids(self):
        app = FakeApp()
        app._pids_provider = lambda: ([], None)
        app._port_open = lambda: True
        with mock.patch.object(self.app_cls, "_stop") as stop, \
             mock.patch.object(self.app_cls, "_start") as start:
            self.app_cls._restart(app)
        stop.assert_not_called()
        start.assert_not_called()
        self.assertTrue(any("重启中止" in line for line in app.logged))


class RestartBreadcrumbTests(unittest.TestCase):
    """_restart()：每一步都留时间戳痕迹 —— 「只关了没起」要能看出停在哪一步。"""

    app_cls = dsh_gui.ConsoleApp

    def test_restart_logs_phase_two_then_starts(self):
        app = FakeApp()
        app._pids_provider = lambda: ([4242], None)
        app._port_open = lambda: False
        app._ask_main = lambda fn, *args: True
        app._wait_port = lambda want, timeout: True
        app._wait_started = lambda timeout, note_every=10.0: True
        start = mock.Mock()
        app._stop = mock.Mock()
        app._start = start
        self.app_cls._restart(app)
        start.assert_called_once_with(force=True)
        app._stop.assert_called_once_with([4242])
        self.assertTrue(any("重启②" in line for line in app.logged),
                        "没有「已关闭，开始拉起」这一步的痕迹：" + " | ".join(app.logged))
        self.assertTrue(any("重启完成" in line for line in app.logged))

    def test_restart_reports_abort_when_port_stays_open(self):
        app = FakeApp()
        app._pids_provider = lambda: ([4242], None)
        app._port_open = lambda: True
        app._ask_main = lambda fn, *args: True
        app._wait_port = lambda want, timeout: False
        app._dump_tails = lambda: app.logged.append("（日志尾巴）")
        start = mock.Mock()
        app._stop = mock.Mock()
        app._start = start
        self.app_cls._restart(app)
        start.assert_not_called()
        self.assertIn("（日志尾巴）", app.logged, "中止时要把真实日志尾巴摆出来")


class WaitStartedTests(unittest.TestCase):
    """_wait_started()：冷启动慢也不能提前宣布失败，超时才认输。"""

    app_cls = dsh_gui.ConsoleApp

    def test_returns_true_when_port_opens_late(self):
        app = FakeApp()
        opened = {"at": 3}

        def port_open():
            opened["at"] -= 1
            return opened["at"] <= 0

        app._port_open = port_open
        with mock.patch.object(dsh_gui.time, "sleep", lambda _s: None):
            self.assertTrue(self.app_cls._wait_started(app, 60.0, note_every=999))

    def test_reports_progress_while_waiting(self):
        app = FakeApp()
        ticks = {"n": 0}

        def port_open():
            ticks["n"] += 1
            return False

        app._port_open = port_open
        with mock.patch.object(dsh_gui.time, "sleep", lambda _s: None):
            self.assertFalse(self.app_cls._wait_started(app, 0.0))
        self.assertFalse(app.logged, "没到报进度的时间点就不该刷屏")

    def test_timeout_returns_false(self):
        app = FakeApp()
        app._port_open = lambda: False
        with mock.patch.object(dsh_gui.time, "sleep", lambda _s: None):
            self.assertFalse(self.app_cls._wait_started(app, 0.0))


class DumpTailsTests(unittest.TestCase):
    """_dump_tails()：失败时把真实日志尾巴贴进界面，而不是一句「请查看」。"""

    app_cls = dsh_gui.ConsoleApp

    def _app(self):
        app = FakeApp()
        app._dump_tails = lambda: self.app_cls._dump_tails(app)
        return app

    def test_prints_label_and_lines(self):
        app = self._app()
        cfg = SimpleNamespace(stderr_log="C:/x/stderr.log")
        with mock.patch.object(dsh_gui, "CFG", cfg), \
             mock.patch.object(dsh_gui, "TOKEN_LOG", "C:/x/stdout.log"), \
             mock.patch.object(dsh_gui.journal, "tail_lines",
                               lambda src, limit=8: ["boom"] if "stderr" in str(src) else []):
            self.app_cls._dump_tails(app)
        self.assertIn("—— stderr 最后 1 行 ——", app.logged)
        self.assertIn("boom", app.logged)

    def test_says_so_when_both_logs_empty(self):
        app = self._app()
        cfg = SimpleNamespace(stderr_log=None)
        with mock.patch.object(dsh_gui, "CFG", cfg), \
             mock.patch.object(dsh_gui, "TOKEN_LOG", None), \
             mock.patch.object(dsh_gui.journal, "tail_lines", lambda src, limit=8: []):
            self.app_cls._dump_tails(app)
        self.assertTrue(any("都没有内容" in line for line in app.logged))


class ProcessPairsTests(unittest.TestCase):
    """probe._process_pairs：任一命令行读不到就整体判未知，不猜。"""

    def test_unreadable_command_line_marks_whole_unknown(self):
        data = [{"ProcessId": 1, "CommandLine": "node bin.js"},
                {"ProcessId": 2}]
        pairs, err = probe._process_pairs(data)
        self.assertIsNone(pairs)
        self.assertEqual(err, "部分 node 进程命令行不可读取，无法安全判定 DSH 是否运行")

    def test_empty_command_line_marks_whole_unknown(self):
        data = [{"ProcessId": 1, "CommandLine": ""}]
        pairs, err = probe._process_pairs(data)
        self.assertIsNone(pairs)
        self.assertIn("无法安全判定", err)


class StartGateTests(unittest.TestCase):
    """_start() 的启动串行化闸：多入口互斥，拿不到闸就不拉起。"""

    app_cls = dsh_gui.ConsoleApp

    def _gated_app(self):
        app = FakeApp()
        app._port_open = lambda: False
        app._wait_started = lambda timeout, note_every=10.0: True
        app._verify_token_after_start = lambda: None
        return app

    def test_start_blocked_by_gate_logs_and_does_not_launch(self):
        app = self._gated_app()
        called = []
        app._start_direct = lambda: called.append(1) or True
        lock = single.StartLock(False, "另一个入口正在启动 DSH，稍后再试")
        with mock.patch.object(dsh_gui.single, "acquire_start_lock", lambda: lock):
            self.app_cls._start(app)
        self.assertFalse(called)
        self.assertTrue(any("闸门拦住" in line for line in app.logged))

    def test_start_proceeds_when_gate_open(self):
        app = self._gated_app()
        app._pids_provider = lambda: ([123], None)
        app._start_direct = lambda: True
        lock = single.StartLock(True, "")
        with mock.patch.object(dsh_gui.single, "acquire_start_lock", lambda: lock), \
             mock.patch.object(dsh_gui.time, "sleep", lambda _s: None):
            self.app_cls._start(app)
        self.assertTrue(any("启动完成" in line for line in app.logged))


if __name__ == "__main__":
    unittest.main()
