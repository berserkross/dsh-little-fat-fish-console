"""GUI 的进程守卫、异常显式化、可注入探测口（不实例化 Tk，不弹窗阻塞）。"""
import io
import unittest
from contextlib import redirect_stderr
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

try:
    import dsh_gui
except Exception as exc:  # noqa: BLE001 - 缺 GUI 依赖时跳过
    raise unittest.SkipTest("无法导入 GUI：" + str(exc))

from dshconsole import adopt, psrun, snapshot, status, tasks

FAKE_BIN_JS = r"C:\自检\node_modules\@deepseek-ai\dsh\lib\bin.js"


class Widget:
    """够用的控件替身：记下 configure / pack 的调用。"""

    def __init__(self):
        self.kw = {}
        self.packed = False

    def configure(self, **kw):
        self.kw.update(kw)

    def pack(self, **kw):
        self.packed = True
        self.kw.update(kw)

    def pack_forget(self):
        self.packed = False


class FakeApp:
    def __init__(self):
        self.logged = []
        self._candidates = []
        self._adopt_shown = False
        self._token = None
        self._log_follow = True
        self._close_to_tray = True
        self.refreshed = 0
        self.lbl_service = Widget()
        self.lbl_phone = Widget()
        self.lbl_net = Widget()
        self.lbl_detail = Widget()
        self.lbl_residue = Widget()
        self.btn_adopt = Widget()
        self.lbl_close_hint = Widget()
        self._queue = tasks.TaskQueue()                      # 真队列：on_change 同步执行
        self._snapshot = snapshot.Snapshot(lambda: None, ttl=60)

    def _post(self, fn, *args):
        fn(*args)                # 主线程投递在测试里同步执行

    def logline(self, text):
        self.logged.append(text)

    def _append_log(self, lines, prefix="", limit=dsh_gui.MAX_LOG_LINES):
        for line in lines:
            self.logged.append(prefix + line)

    def log_async(self, text):
        self.logged.append(text)

    def after(self, _ms, fn, *args):
        fn(*args)            # 主线程回调在测试里同步执行

    def clear_qr(self):
        pass

    def refresh(self, force=False):
        self.refreshed += 1

    def _sync_adopt_button(self):
        dsh_gui.ConsoleApp._sync_adopt_button(self)

    def _on_residue_click(self):
        dsh_gui.ConsoleApp._on_residue_click(self)

    def _cleanup_residue(self):
        dsh_gui.ConsoleApp._cleanup_residue(self)

    def _startup_line(self, state):
        return dsh_gui.ConsoleApp._startup_line(self, state)

    def _sync_primary(self, phase):
        dsh_gui.ConsoleApp._sync_primary(self, phase)

    def _sync_close_hint(self):
        dsh_gui.ConsoleApp._sync_close_hint(self)

    def _on_tray_lost(self, reason):
        dsh_gui.ConsoleApp._on_tray_lost(self, reason)

    def _tray_items(self):
        return dsh_gui.ConsoleApp._tray_items(self)

    def _pick_candidate(self, cands):
        return dsh_gui.ConsoleApp._pick_candidate(self, cands)

    def _sync_detail(self, state):
        dsh_gui.ConsoleApp._sync_detail(self, state)

    def _sync_group_labels(self):
        dsh_gui.ConsoleApp._sync_group_labels(self)

    def _log_net_once(self, state):
        dsh_gui.ConsoleApp._log_net_once(self, state)


def degraded(pid=9856, path=FAKE_BIN_JS):
    return status.Status(phase=status.Phase.DEGRADED, pids=[], port_open=True,
                         phone_open=False, ts_ip=None, lan_ips=None, notes=[],
                         others=[(pid, path)])


def running():
    return status.Status(phase=status.Phase.RUNNING, pids=[9856], port_open=True,
                         phone_open=False, ts_ip=None, lan_ips=None, notes=[])


class AdoptButtonTests(unittest.TestCase):
    app_cls = dsh_gui.ConsoleApp

    def test_button_appears_only_for_degraded_with_candidates(self):
        app = FakeApp()
        self.app_cls._apply_status(app, running())
        self.assertEqual(app._candidates, [])
        self.assertFalse(app._adopt_shown)
        self.assertFalse(app.btn_adopt.packed)

        self.app_cls._apply_status(app, degraded())
        self.assertEqual([c.pid for c in app._candidates], [9856])
        self.assertTrue(app._adopt_shown)
        self.assertTrue(app.btn_adopt.packed)
        self.assertIn("改为控制运行中的实例", app.btn_adopt.kw["text"])
        self.assertIn("9856", app.btn_adopt.kw["text"])

    def test_button_disappears_once_status_recovers(self):
        app = FakeApp()
        self.app_cls._apply_status(app, degraded())
        self.app_cls._apply_status(app, running())
        self.assertFalse(app._adopt_shown)
        self.assertFalse(app.btn_adopt.packed)
        self.assertEqual(app._candidates, [])

    def test_multiple_candidates_are_announced_not_auto_picked(self):
        app = FakeApp()
        state = status.Status(phase=status.Phase.DEGRADED, others=[(1, FAKE_BIN_JS),
                                                                  (2, FAKE_BIN_JS)])
        self.app_cls._apply_status(app, state)
        self.assertEqual(len(app._candidates), 2)
        self.assertIn("2 个候选", app.btn_adopt.kw["text"])

    def test_degraded_without_candidates_keeps_button_hidden(self):
        app = FakeApp()
        self.app_cls._apply_status(app, status.Status(phase=status.Phase.DEGRADED,
                                                      others=None))
        self.assertFalse(app._adopt_shown)


class AdoptActionTests(unittest.TestCase):
    app_cls = dsh_gui.ConsoleApp

    def test_single_candidate_is_adopted_and_global_config_replaced(self):
        app = FakeApp()
        app._candidates = [adopt.Candidate(pid=7, bin_js=FAKE_BIN_JS, harness=Path(FAKE_BIN_JS))]
        new_cfg = SimpleNamespace(harness=Path(r"C:\harness"), port=3080, token_log=None)
        with mock.patch.object(dsh_gui.adopt, "adopt",
                               lambda cfg, cand: (new_cfg, "已改为控制 C:\\harness（PID 7）")), \
             mock.patch.object(dsh_gui, "CFG"), mock.patch.object(dsh_gui, "HARNESS"), \
             mock.patch.object(dsh_gui, "PORT"), mock.patch.object(dsh_gui, "TOKEN_LOG"):
            self.app_cls._adopt(app)
            self.assertIs(dsh_gui.CFG, new_cfg)
            self.assertEqual(dsh_gui.PORT, 3080)
        self.assertTrue(any("已改为控制" in line for line in app.logged))

    def test_refusal_is_logged_and_explained(self):
        app = FakeApp()
        app._candidates = [adopt.Candidate(pid=7, bin_js=FAKE_BIN_JS, harness=None)]
        shown = []
        app._ask_main = lambda fn, *args: shown.append(args)
        with mock.patch.object(dsh_gui.adopt, "adopt",
                               lambda cfg, cand: (None, "推不出 harness，请用 --harness 指定")):
            self.app_cls._adopt(app)
        self.assertIn("--harness", app.logged[0])
        self.assertTrue(shown)            # 同时弹一次说明，不静默

    def test_no_candidate_is_logged(self):
        app = FakeApp()
        self.app_cls._adopt(app)
        self.assertIn("没有可采纳的候选进程", app.logged[0])

    def test_cancel_from_picker_is_logged(self):
        app = FakeApp()
        app._candidates = [adopt.Candidate(pid=1, bin_js=FAKE_BIN_JS, harness=None),
                           adopt.Candidate(pid=2, bin_js=FAKE_BIN_JS, harness=None)]
        app._ask_main = lambda fn, *args: None
        self.app_cls._adopt(app)
        self.assertIn("已取消", app.logged[0])

    def test_picker_parses_only_valid_indexes(self):
        app = FakeApp()
        cands = [adopt.Candidate(pid=1, bin_js=FAKE_BIN_JS, harness=None),
                 adopt.Candidate(pid=2, bin_js=FAKE_BIN_JS, harness=None)]
        for raw, want in (("2", 1), ("1", 0), ("0", None), ("9", None), ("abc", None), ("", None)):
            with mock.patch.object(dsh_gui.ctk, "CTkInputDialog",
                                   lambda **kw: SimpleNamespace(get_input=lambda: raw)):
                self.assertEqual(dsh_gui.ConsoleApp._pick_candidate(app, cands), want, raw)


class ExceptionVisibilityTests(unittest.TestCase):
    app_cls = dsh_gui.ConsoleApp

    def test_background_failure_logs_traceback_and_leaves_queue_idle(self):
        app = FakeApp()

        def work():
            raise RuntimeError("后台炸了")

        task = self.app_cls._submit(app, "测试任务", work)
        self.assertTrue(app._queue.wait_idle(5))
        joined = "\n".join(app.logged)
        self.assertIs(task.state, tasks.State.FAILED)     # 失败有明确状态，不靠全局锁
        self.assertTrue(app._queue.idle())                # 队列回到空闲：不会有永久禁用的按钮
        self.assertIn("出错：后台炸了", joined)
        self.assertIn("Traceback", joined)                # 有栈帧摘要，不是只有一句话
        self.assertGreaterEqual(app.refreshed, 1)         # 失败后仍然刷新一次状态

    def test_tk_callback_error_logs_redacted_traceback(self):
        app = FakeApp()
        try:
            raise ValueError("回调里炸了 token=abcd1234")
        except ValueError as exc:
            self.app_cls._on_callback_error(app, type(exc), exc, exc.__traceback__)
        joined = "\n".join(app.logged)
        self.assertTrue(app._queue.idle())                # 回调炸了也不留任何「进行中」状态
        self.assertIn("界面回调异常", joined)
        self.assertIn("ValueError", joined)
        self.assertNotIn("abcd1234", joined)

    def test_broken_log_widget_does_not_swallow_the_error(self):
        app = FakeApp()

        def broken(_text):
            raise RuntimeError("日志框坏了")

        app.logline = broken
        buffer = io.StringIO()
        try:
            raise ValueError("x")
        except ValueError as exc:
            with redirect_stderr(buffer):     # 日志框坏时退回 stderr，而不是吞掉
                self.app_cls._on_callback_error(app, type(exc), exc, exc.__traceback__)
        self.assertIn("ValueError: x", buffer.getvalue())


class LogScrollTests(unittest.TestCase):
    """滚到末尾要便宜：see("end") 实测一次吃掉 56 ms，yview_moveto 近乎免费。"""

    app_cls = dsh_gui.ConsoleApp

    def test_scroll_prefers_the_cheap_yview_moveto(self):
        app = FakeApp()
        calls = []
        app.log = SimpleNamespace(yview_moveto=lambda frac: calls.append(("yview", frac)),
                                  see=lambda index: calls.append(("see", index)))
        self.app_cls._scroll_log_to_end(app)
        self.assertEqual(calls, [("yview", 1.0)])

    def test_scroll_falls_back_to_see_without_yview_moveto(self):
        app = FakeApp()
        calls = []
        app.log = SimpleNamespace(see=lambda index: calls.append(("see", index)))
        self.app_cls._scroll_log_to_end(app)
        self.assertEqual(calls, [("see", "end")])

    def test_scroll_swallows_a_dead_widget(self):
        app = FakeApp()

        def boom(*_a, **_k):
            raise RuntimeError("窗口没了")

        app.log = SimpleNamespace(yview_moveto=boom, see=boom)
        self.app_cls._scroll_log_to_end(app)      # 退出路径上不许抛


class TestabilityTests(unittest.TestCase):
    def test_gui_does_not_monkeypatch_module_globals(self):
        source = Path(dsh_gui.__file__).read_text(encoding="utf-8")
        self.assertNotIn('globals()["', source)

    def test_probe_seams_are_instance_level(self):
        source = Path(dsh_gui.__file__).read_text(encoding="utf-8")
        self.assertIn("self._pids_provider", source)
        self.assertIn("self._status_provider", source)


class TrayFallbackTests(unittest.TestCase):
    """托盘起不来或托盘线程没了：退回普通窗口，不许抛 AttributeError（页脚提示要同步）。"""

    app_cls = dsh_gui.ConsoleApp

    def _fake_tray(self, ok, why):
        return SimpleNamespace(start=lambda items: (ok, why), running=False,
                               stop=lambda: None)

    def test_start_failure_falls_back_to_plain_window(self):
        app = FakeApp()
        app._close_to_tray = True
        app._tray = None
        app._window_label = "显示窗口"
        for attr in ("_toggle_window", "_tray_copy", "on_stop", "_quit"):
            setattr(app, attr, lambda: None)      # 托盘菜单项只是被列出来，不会被调用
        with mock.patch.object(dsh_gui.tray, "Tray", lambda **_kw: self._fake_tray(False, "没有可用的托盘库")):
            self.assertFalse(self.app_cls._start_tray(app))
        self.assertIsNone(app._tray)
        self.assertFalse(app._close_to_tray)
        self.assertEqual(app.lbl_close_hint.kw["text"], "关闭按钮：退出程序")
        self.assertTrue(any("按普通窗口运行" in line for line in app.logged))

    def test_tray_lost_resets_close_hint(self):
        app = FakeApp()
        app._close_to_tray = True
        app._tray = SimpleNamespace(running=True, stop=lambda: None)
        app._window_label = "显示窗口"
        self.app_cls._on_tray_lost(app, "托盘线程退出")
        self.assertIsNone(app._tray)
        self.assertFalse(app._close_to_tray)
        self.assertEqual(app.lbl_close_hint.kw["text"], "关闭按钮：退出程序")
        self.assertTrue(any("退回普通窗口" in line for line in app.logged))


class ResidueChipTests(unittest.TestCase):
    """状态条上的「端口转发残留」芯片：残留态可见、点击走 -CleanupOnly、结果如实写日志。"""

    app_cls = dsh_gui.ConsoleApp

    def _residue_state(self):
        return status.Status(phase=status.Phase.STOPPED, pids=[], port_open=False,
                             phone_open=False, ts_ip=None, lan_ips=None, notes=[],
                             residue=True)

    def test_apply_status_shows_residue_chip(self):
        app = FakeApp()
        self.app_cls._apply_status(app, self._residue_state())
        self.assertIn("残留", app.lbl_residue.kw.get("text", ""))

    def test_apply_status_hides_chip_when_clean(self):
        app = FakeApp()
        state = status.Status(phase=status.Phase.STOPPED, pids=[], port_open=False,
                              phone_open=False, ts_ip=None, lan_ips=None, notes=[],
                              residue=False)
        self.app_cls._apply_status(app, state)
        self.assertEqual(app.lbl_residue.kw.get("text", ""), "")

    def test_residue_click_runs_cleanup_and_logs_success(self):
        app = FakeApp()
        calls = []
        app._run_switch = (lambda script, *args, **kw:
                           calls.append((script, args, kw)) or
                           psrun.PsResult(ok=True, code=0, stdout="", stderr="", error=None))
        with mock.patch.object(dsh_gui.probe, "portproxy_targets",
                               lambda port: (["127.0.0.1"], None)):
            self.app_cls._on_residue_click(app)
        self.assertEqual(len(calls), 1)
        self.assertIn("-CleanupOnly", calls[0][1])
        self.assertTrue(any("端口转发残留清理完成" in line for line in app.logged))

    def test_residue_cleanup_failure_is_logged(self):
        app = FakeApp()
        app._run_switch = lambda *a, **kw: psrun.PsResult(
            ok=False, code=1, stdout="", stderr="用户取消了 UAC", error=None)
        with mock.patch.object(dsh_gui.probe, "portproxy_targets",
                               lambda port: (["127.0.0.1"], None)):
            self.app_cls._on_residue_click(app)
        self.assertTrue(any("端口转发残留清理失败" in line for line in app.logged))


class StartupLineTests(unittest.TestCase):
    """阶段 4：启动中状态条显示已用秒数 + 最近一行启动日志；完成后停留 2 秒再回正常。"""

    app_cls = dsh_gui.ConsoleApp

    def test_starting_phase_shows_elapsed_and_redacted_log_line(self):
        app = FakeApp()
        app._start_epoch = 100.0
        state = status.Status(phase=status.Phase.STARTING, pids=[123], port_open=False)
        with mock.patch.object(dsh_gui.time, "time", lambda: 113.5), \
             mock.patch.object(dsh_gui.logtail, "read_tail",
                               lambda path, count: "dsh web: http://127.0.0.1:3080/?token=secret\n"):
            self.app_cls._sync_detail(app, state)
        text = app.lbl_detail.kw.get("text", "")
        self.assertIn("启动中 13.5s", text)
        self.assertNotIn("secret", text)          # 日志行含 token，必须脱敏

    def test_after_running_holds_two_seconds_then_normal(self):
        app = FakeApp()
        app._start_epoch = 100.0
        state = status.Status(phase=status.Phase.RUNNING, pids=[123], port_open=True)
        with mock.patch.object(dsh_gui.time, "time", lambda: 115.0):
            self.app_cls._sync_detail(app, state)
        self.assertIn("启动完成", app.lbl_detail.kw.get("text", ""))
        with mock.patch.object(dsh_gui.time, "time", lambda: 118.0):
            self.app_cls._sync_detail(app, state)
        self.assertIn("PID 123", app.lbl_detail.kw.get("text", ""))

    def test_seconds_tick_with_elapsed_time(self):
        app = FakeApp()
        app._start_epoch = 100.0
        state = status.Status(phase=status.Phase.STARTING, pids=[123], port_open=False)
        with mock.patch.object(dsh_gui.logtail, "read_tail", lambda path, count: ""):
            with mock.patch.object(dsh_gui.time, "time", lambda: 100.0):
                self.app_cls._sync_detail(app, state)
            first = app.lbl_detail.kw.get("text", "")
            with mock.patch.object(dsh_gui.time, "time", lambda: 101.5):
                self.app_cls._sync_detail(app, state)
            second = app.lbl_detail.kw.get("text", "")
        self.assertNotEqual(first, second)          # 秒数在递增


if __name__ == "__main__":
    unittest.main()
