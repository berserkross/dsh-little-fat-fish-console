"""手机访问界面层：二维码/复制只认手机可达的候选，绝不回落 127.0.0.1。

全部注入式：不联网、不跑 tailscale 真命令、不开窗口。
"""
from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest import mock

from dshconsole import addresses, phone, tailscale

SERVE_HOST = "selftest.tail1234.ts.net"


def serve_candidate(host: str = SERVE_HOST):
    return addresses.Candidate(host=host, tier=addresses.TIER_SERVE, label="MagicDNS（tailscale serve）",
                               url=f"http://{host}/", port=addresses.SCHEME_PORTS["http"])


def tailscale_candidate(host: str = "100.101.102.103", port: int = 3080):
    return addresses.Candidate(host=host, tier=addresses.TIER_TAILSCALE, label="Tailscale",
                               url=f"http://{host}:{port}/", port=port)


def lan_candidate(host: str = "192.168.1.20", port: int = 3080):
    return addresses.Candidate(host=host, tier=addresses.TIER_LAN, label="以太网",
                               url=f"http://{host}:{port}/", port=port)


def loopback_candidate():
    return addresses.Candidate(host="127.0.0.1", tier=addresses.TIER_LOOPBACK, label="本机",
                               url="http://127.0.0.1:3080/", port=3080)


def fake_plan(*cands, qr_url=None, mode=None, failures=(), next_step="下一步：先登录 Tailscale。",
              serve_host="", scheme=addresses.SCHEME_HTTP):
    """手机访问计划替身：只带界面真正读的字段，故意不去调真 detect。"""
    first = cands[0].url if cands else None
    return SimpleNamespace(candidates=tuple(cands), qr_url=qr_url if qr_url is not None else first,
                           mode=mode or (phone.MODE_PROXY if cands else phone.MODE_NONE),
                           port=3080, failures=tuple(failures), next_step=next_step,
                           serve_host=serve_host, scheme=scheme, degraded=bool(failures))


def load_gui():
    try:
        import dsh_gui
    except Exception as exc:      # noqa: BLE001 - 缺 GUI 依赖时跳过
        raise unittest.SkipTest("无法导入 GUI：" + str(exc))
    return dsh_gui


class PhoneViewTests(unittest.TestCase):
    """纯函数层：候选 → 下拉行 / 二维码地址 / 下一步文案。"""

    @classmethod
    def setUpClass(cls):
        cls.gui = load_gui()

    def test_service_order_is_kept(self):
        plan_obj = fake_plan(serve_candidate(), tailscale_candidate(), lan_candidate())
        rows = self.gui.phone_rows(plan_obj)
        self.assertEqual([cand.host for _text, cand in rows],
                         [SERVE_HOST, "100.101.102.103", "192.168.1.20"])
        self.assertTrue(all(text.startswith("http") for text, _cand in rows))

    def test_default_row_follows_qr_url(self):
        tail, lan = tailscale_candidate(), lan_candidate()
        plan_obj = fake_plan(tail, lan, qr_url=lan.url)
        self.assertEqual(self.gui.phone_default_row(plan_obj), lan.display())

    def test_default_row_without_candidates_is_none(self):
        self.assertIsNone(self.gui.phone_default_row(fake_plan()))
        self.assertIsNone(self.gui.phone_default_row(None))

    def test_qr_and_copy_urls_never_use_loopback(self):
        plan_obj = fake_plan(serve_candidate(), tailscale_candidate())
        for choice in (None, self.gui.phone_rows(plan_obj)[0][0],
                       self.gui.phone_rows(plan_obj)[1][0]):
            cand = self.gui.phone_candidate(plan_obj, choice)
            url = self.gui.phone_candidate_url(cand, "abc123")
            self.assertTrue(url, choice)
            self.assertNotIn("127.0.0.1", url)
        self.assertEqual(self.gui.phone_candidate_url(self.gui.phone_candidate(plan_obj), "abc123"),
                         "http://" + SERVE_HOST + "/?token=abc123")

    def test_loopback_candidate_is_refused(self):
        plan_obj = fake_plan(loopback_candidate())
        self.assertIsNone(self.gui.phone_candidate(plan_obj))
        self.assertIsNone(self.gui.phone_candidate_url(loopback_candidate(), "abc123"))

    def test_unknown_choice_is_refused_not_substituted(self):
        plan_obj = fake_plan(tailscale_candidate())
        self.assertIsNone(self.gui.phone_candidate(plan_obj, "（别的什么东西）"))

    def test_existing_token_is_not_duplicated(self):
        cand = tailscale_candidate()
        with_token = addresses.Candidate(host=cand.host, tier=cand.tier, label=cand.label,
                                         url=cand.url + "?token=keep", port=cand.port)
        self.assertEqual(self.gui.phone_candidate_url(with_token, "abc123"),
                         cand.url + "?token=keep")
        self.assertIsNone(self.gui.phone_candidate_url(cand, None))

    def test_next_steps_quote_the_structured_reason(self):
        reason = tailscale.Reason("daemon_down", "tailscaled 没在跑：先打开 Tailscale 客户端。")
        plan_obj = fake_plan(failures=(reason,), next_step="先登录 Tailscale。")
        text = self.gui.phone_next_steps(plan_obj)
        self.assertIn("先登录 Tailscale。", text)
        self.assertIn(reason.text, text)
        self.assertIn("端口 3080", text)      # 判定清单也跟着
        self.assertIn(reason.text, self.gui.phone_reason_text(plan_obj))

    def test_next_steps_survive_a_failed_detection(self):
        text = self.gui.phone_next_steps(None)
        self.assertIn("探测失败", text)
        self.assertEqual(self.gui.phone_reason_text(None), "")

    def test_switch_args_carry_the_serve_host(self):
        args = self.gui.switch_args(fake_plan(serve_candidate(), serve_host=SERVE_HOST))
        self.assertEqual(args[-2:], ["-ServeHost", SERVE_HOST + ":80"])
        self.assertNotIn("-ServeHost", self.gui.switch_args(fake_plan(tailscale_candidate())))

    def test_selftest_plan_has_two_nonloopback_candidates(self):
        plan_obj = self.gui._selftest_phone_plan(3080)
        self.assertEqual(plan_obj.mode, phone.MODE_SERVE)
        self.assertEqual(len(plan_obj.candidates), 2)
        self.assertTrue(all(cand.phone_reachable for cand in plan_obj.candidates))
        self.assertEqual(plan_obj.qr_url, "http://" + SERVE_HOST + "/")
        self.assertNotIn("127.0.0.1", plan_obj.qr_url)
        copy_url = self.gui.phone_candidate_url(self.gui.phone_candidate(plan_obj), "selftest-token")
        self.assertNotIn("127.0.0.1", copy_url)
        self.assertEqual(plan_obj.qr_url.split("/")[2], "selftest.tail1234.ts.net")


REAL_METHODS = ("_phone_plan_for_ui", "_show_phone_steps", "_on_qr_pick",
                "_fill_qr_addresses", "_pick_phone_address", "on_copy",
                "_phone_on", "_phone_off")


def bind_real(app, gui):
    """把 ConsoleApp 的真实方法绑到替身上：测的是真代码，不是复写的一份。"""
    for name in REAL_METHODS:
        setattr(app, name, getattr(gui.ConsoleApp, name).__get__(app, type(app)))
    return app


class FakeWidget:
    def __init__(self):
        self.kwargs = []
        self.value = None

    def configure(self, **kwargs):
        self.kwargs.append(kwargs)
        if "values" in kwargs:
            self.values = kwargs["values"]

    def set(self, value):
        self.value = value

    def get(self):
        return self.value


class FakeOverlay:
    def __init__(self):
        self.picker = FakeWidget()
        self.image_label = FakeWidget()
        self.hint = FakeWidget()


class FakeApp:
    """只带被测方法真正碰的属性；没有 Tk 也能跑。"""

    def __init__(self, plan_obj=None, token="http://127.0.0.1:3080/?token=abc123"):
        self.logged = []
        self.clipboard = ""
        self._token = token
        self._phone_now = None
        self._phone_planner = lambda *args, **kwargs: plan_obj
        self._qr_photo = None
        self._qr_url = None
        self._qr_overlay = None
        self.qr_calls = []
        self.switch_calls = []
        self.reset_calls = 0
        self.ready = (True, None)
        self.serve_reset_reason = None

    def logline(self, text):
        self.logged.append(text)

    def log_async(self, text):
        self.logged.append(text)

    def _current_token(self):
        return self._token

    def clipboard_clear(self):
        self.clipboard = ""

    def clipboard_append(self, text):
        self.clipboard += text

    def _qr(self, url, label):
        self.qr_calls.append((url, label))
        self._qr_url = url
        self._qr_photo = object()

    def _run_switch(self, *args, **kwargs):
        self.switch_calls.append((args, kwargs))
        return SimpleNamespace(stdout="切换脚本输出", stderr="")

    def _serve_reset(self):
        self.reset_calls += 1
        return self.serve_reset_reason


class QrOverlayTests(unittest.TestCase):
    """浮层：有候选就画码，没候选只写下一步，回环永远进不来。"""

    @classmethod
    def setUpClass(cls):
        cls.gui = load_gui()

    def make_app(self, plan_obj, overlay=True):
        app = FakeApp(plan_obj)
        if overlay:
            app._qr_overlay = FakeOverlay()
        return bind_real(app, self.gui)

    def test_fill_uses_plan_candidates_in_order(self):
        plan_obj = fake_plan(serve_candidate(), tailscale_candidate(), lan_candidate())
        app = self.make_app(plan_obj)
        app._fill_qr_addresses()
        picker = app._qr_overlay.picker
        self.assertEqual(len(picker.values), 3)
        self.assertEqual(picker.value, self.gui.phone_rows(plan_obj)[0][0])
        self.assertEqual(len(app.qr_calls), 1)
        self.assertNotIn("127.0.0.1", app.qr_calls[0][0])
        self.assertEqual(app.qr_calls[0][0], "http://" + SERVE_HOST + "/?token=abc123")

    def test_fill_without_candidates_shows_next_steps_only(self):
        reason = tailscale.Reason("not_logged_in", "Tailscale 没登录：请先 tailscale up。")
        plan_obj = fake_plan(failures=(reason,), mode=phone.MODE_NONE)
        app = self.make_app(plan_obj)
        app._fill_qr_addresses()
        picker = app._qr_overlay.picker
        self.assertEqual(picker.values, [self.gui.NO_PHONE_ROW])
        self.assertEqual(picker.value, self.gui.NO_PHONE_ROW)
        self.assertEqual(app.qr_calls, [])          # 一张码都不许画
        self.assertIsNone(app._qr_url)
        shown = app._qr_overlay.image_label.kwargs[-1]
        self.assertIsNone(shown.get("image"))
        self.assertIn(reason.text, shown.get("text", ""))
        self.assertNotIn("127.0.0.1", "".join(app.logged))

    def test_pick_loopback_explicitly_shows_steps(self):
        app = self.make_app(fake_plan(loopback_candidate()))
        app._fill_qr_addresses()
        self.assertEqual(app.qr_calls, [])
        text = app._qr_overlay.image_label.kwargs[-1].get("text", "")
        self.assertTrue(text)

    def test_pick_unknown_row_does_not_fall_back(self):
        plan_obj = fake_plan(tailscale_candidate())
        app = self.make_app(plan_obj)
        app._on_qr_pick(self.gui.NO_PHONE_ROW)
        self.assertEqual(app.qr_calls, [])


class CopyAndSwitchTests(unittest.TestCase):
    """复制地址与 UAC 开关：只讲事实，不改写 tailscale 的原话。"""

    @classmethod
    def setUpClass(cls):
        cls.gui = load_gui()

    def make_app(self, plan_obj):
        app = FakeApp(plan_obj)
        app._ask_address = lambda *args, **kwargs: getattr(app, "dialog_return", None)
        return bind_real(app, self.gui)

    def test_copy_never_yields_loopback(self):
        plan_obj = fake_plan(serve_candidate(), tailscale_candidate(), lan_candidate())
        app = self.make_app(plan_obj)
        app.dialog_return = (plan_obj.candidates[0], 80)   # 下拉里选中的那一条
        with mock.patch.object(self.gui, "messagebox"):
            app.on_copy()
        self.assertEqual(app.clipboard, "http://" + SERVE_HOST + "/?token=abc123")
        self.assertNotIn("127.0.0.1", app.clipboard)
        self.assertNotIn("127.0.0.1", "".join(app.logged))
        self.assertNotIn("abc123", "".join(app.logged))     # 日志仍然打码

    def test_copy_without_candidates_copies_nothing(self):
        reason = tailscale.Reason("cli_missing", "找不到 tailscale 命令。")
        app = self.make_app(fake_plan(failures=(reason,), mode=phone.MODE_NONE))
        with mock.patch.object(self.gui, "messagebox") as box:
            app.on_copy()
        self.assertEqual(app.clipboard, "")
        self.assertTrue(box.showinfo.called)
        self.assertIn(reason.text, "".join(app.logged))

    def test_phone_on_skips_uac_when_serve_is_ready(self):
        app = self.make_app(fake_plan(serve_candidate(), mode=phone.MODE_SERVE,
                                      serve_host=SERVE_HOST))
        app._phone_on()
        self.assertEqual(app.switch_calls, [])
        self.assertIn("已就绪", "".join(app.logged))
        self.assertIn(SERVE_HOST, "".join(app.logged))

    def test_phone_on_reports_tailscale_reason_verbatim(self):
        reason = tailscale.Reason("daemon_down", "tailscaled 没在跑：先打开 Tailscale 客户端。")
        plan_obj = fake_plan(tailscale_candidate(), failures=(reason,), serve_host=SERVE_HOST)
        app = self.make_app(plan_obj)
        with mock.patch.object(self.gui, "phone_ready", lambda: (True, None)):
            app._phone_on()
        self.assertEqual(len(app.switch_calls), 1)
        args = app.switch_calls[0][0]
        self.assertIn("-ServeHost", args)
        self.assertIn(SERVE_HOST + ":80", args)
        logs = "".join(app.logged)
        self.assertIn(reason.text, logs)                  # 原样，不改写
        self.assertIn("已开启", logs)

    def test_phone_off_shows_reset_reason_verbatim(self):
        app = self.make_app(fake_plan())
        app.serve_reset_reason = tailscale.Reason("serve_failed", "tailscale serve reset 失败。")
        app._phone_off()
        self.assertEqual(app.reset_calls, 1)
        self.assertIn("tailscale serve reset 失败。", "".join(app.logged))
        self.assertIn("-Restore", app.switch_calls[0][0])
