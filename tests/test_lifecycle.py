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

from dshconsole import probe, psrun


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


if __name__ == "__main__":
    unittest.main()
