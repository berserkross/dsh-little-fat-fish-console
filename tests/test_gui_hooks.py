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

from dshconsole import adopt, status

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
        self._busy = False
        self._candidates = []
        self._adopt_shown = False
        self._token = None
        self.refreshed = 0
        self.lbl_service = Widget()
        self.lbl_phone = Widget()
        self.lbl_net = Widget()
        self.btn_adopt = Widget()

    def logline(self, text):
        self.logged.append(text)

    def log_async(self, text):
        self.logged.append(text)

    def after(self, _ms, fn, *args):
        fn(*args)            # 主线程回调在测试里同步执行

    def clear_qr(self):
        pass

    def refresh(self):
        self.refreshed += 1

    def _sync_adopt_button(self):
        dsh_gui.ConsoleApp._sync_adopt_button(self)

    def _pick_candidate(self, cands):
        return dsh_gui.ConsoleApp._pick_candidate(self, cands)


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

    def test_background_failure_logs_traceback_and_releases_busy(self):
        app = FakeApp()
        app._busy = True

        def work():
            raise RuntimeError("后台炸了")

        self.app_cls._wrap(app, work)
        joined = "\n".join(app.logged)
        self.assertFalse(app._busy)                      # 不会卡在「进行中」
        self.assertIn("出错：后台炸了", joined)
        self.assertIn("Traceback", joined)               # 有栈帧摘要，不是只有一句话
        self.assertEqual(app.refreshed, 1)               # 失败后仍然刷新一次状态

    def test_tk_callback_error_logs_redacted_traceback_and_clears_busy(self):
        app = FakeApp()
        app._busy = True
        try:
            raise ValueError("回调里炸了 token=abcd1234")
        except ValueError as exc:
            self.app_cls._on_callback_error(app, type(exc), exc, exc.__traceback__)
        joined = "\n".join(app.logged)
        self.assertFalse(app._busy)
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


class TestabilityTests(unittest.TestCase):
    def test_gui_does_not_monkeypatch_module_globals(self):
        source = Path(dsh_gui.__file__).read_text(encoding="utf-8")
        self.assertNotIn('globals()["', source)

    def test_probe_seams_are_instance_level(self):
        source = Path(dsh_gui.__file__).read_text(encoding="utf-8")
        self.assertIn("self._pids_provider", source)
        self.assertIn("self._status_provider", source)


if __name__ == "__main__":
    unittest.main()
