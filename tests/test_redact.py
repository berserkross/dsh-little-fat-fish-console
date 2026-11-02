"""日志脱敏：token 打码；剪贴板仍放完整地址。"""
from __future__ import annotations

import unittest
from types import SimpleNamespace

from dshconsole import addresses, textutil

NL = chr(10)


def tailscale_candidate(host: str = "100.124.206.105", port: int = 3080):
    """手机可达的 Tailscale 候选（不再用旧的 Address 层）。"""
    return addresses.Candidate(host=host, tier=addresses.TIER_TAILSCALE, label="Tailscale",
                               url=f"http://{host}:{port}/", port=port)


def lan_candidate(host: str = "192.168.1.20", port: int = 3080):
    return addresses.Candidate(host=host, tier=addresses.TIER_LAN, label="以太网",
                               url=f"http://{host}:{port}/", port=port)


def plan_with(*cands, qr_url=None):
    """手机访问计划的替身：只有界面真正读的那几个字段。"""
    return SimpleNamespace(candidates=tuple(cands), qr_url=qr_url or (cands[0].url if cands else None),
                           mode="serve" if cands else "none", port=3080, failures=(),
                           next_step="", serve_host="", scheme="http")


class RedactTests(unittest.TestCase):
    def test_url_token_is_masked(self):
        self.assertEqual(textutil.redact("http://100.1.2.3:3080/?token=abc123"),
                         "http://100.1.2.3:3080/?token=****")

    def test_masked_value_keeps_other_query_params(self):
        self.assertEqual(textutil.redact("http://127.0.0.1:3080/?token=abc123&x=1"),
                         "http://127.0.0.1:3080/?token=****&x=1")

    def test_bare_token_is_masked(self):
        self.assertEqual(textutil.redact("token=abc123"), "token=****")

    def test_text_without_token_is_unchanged(self):
        plain = "DeepSeek Harness 已停止。"
        self.assertEqual(textutil.redact(plain), plain)

    def test_empty_text(self):
        self.assertEqual(textutil.redact(""), "")

    def test_multiple_tokens_all_masked(self):
        text = "http://a:3080/?token=one" + NL + "http://b:3080/?token=two"
        expected = "http://a:3080/?token=****" + NL + "http://b:3080/?token=****"
        self.assertEqual(textutil.redact(text), expected)

    def test_idempotent(self):
        once = textutil.redact("?token=abc123")
        self.assertEqual(textutil.redact(once), once)

    def test_prefixed_parameter_is_not_a_token(self):
        self.assertEqual(textutil.redact("mytoken=keep"), "mytoken=keep")

    def test_redact_urls_is_an_alias(self):
        text = "?token=abc"
        self.assertEqual(textutil.redact_urls(text), textutil.redact(text))


class GuiLogTests(unittest.TestCase):
    """复制动作实测：日志框里 token 打码，剪贴板里是完整地址。"""

    @classmethod
    def setUpClass(cls):
        try:
            import dsh_gui
        except Exception as exc:  # noqa: BLE001 - 缺 GUI 依赖时跳过
            raise unittest.SkipTest("无法导入 GUI：" + str(exc))
        cls.gui = dsh_gui
        cls.app_cls = dsh_gui.ConsoleApp

    def make_app(self, plan_obj=None):
        class Fake:
            def __init__(self):
                self.logged = []
                self.clipboard = ""
                self._token = "http://127.0.0.1:3080/?token=abc123"
                self._phone_now = plan_obj
                self._phone_planner = lambda *args, **kwargs: plan_obj

            def clipboard_clear(self):
                self.clipboard = ""

            def clipboard_append(self, text):
                self.clipboard += text

            def logline(self, text):
                self.logged.append(text)

            def log_async(self, text):
                self.logged.append(text)

            def _current_token(self):
                return self._token

        app = Fake()
        for name in ("_phone_plan_for_ui", "_pick_phone_address"):
            setattr(app, name, getattr(self.app_cls, name).__get__(app, type(app)))
        return app

    def test_copy_local_masks_log_but_keeps_full_clipboard(self):
        app = self.make_app()
        self.app_cls.on_copy_local(app)
        self.assertEqual(app.clipboard, "http://127.0.0.1:3080/?token=abc123")
        self.assertIn("token=****", app.logged[-1])
        self.assertNotIn("abc123", "".join(app.logged))

    def test_copy_uses_the_chosen_phone_address_and_masks_the_token(self):
        tail, lan = tailscale_candidate(), lan_candidate()
        app = self.make_app(plan_with(tail, lan))
        app._ask_address = lambda *args, **kwargs: (tail, 3080)   # 下拉里选中的那一条
        self.app_cls.on_copy(app)
        self.assertEqual(app.clipboard, "http://100.124.206.105:3080/?token=abc123")
        logs = "".join(app.logged)
        self.assertIn("Tailscale", logs)
        self.assertIn("token=****", logs)
        self.assertNotIn("abc123", logs)

    def test_copy_skips_the_dialog_when_only_one_candidate(self):
        only = tailscale_candidate("100.124.206.105", 3099)
        app = self.make_app(plan_with(only))
        app._ask_address = lambda *args, **kwargs: self.fail("只有一条候选时不该弹选择框")
        self.app_cls.on_copy(app)
        self.assertEqual(app.clipboard, "http://100.124.206.105:3099/?token=abc123")

    def test_cancelled_chooser_copies_nothing(self):
        app = self.make_app(plan_with(tailscale_candidate(), lan_candidate()))
        app._ask_address = lambda *args, **kwargs: None
        self.app_cls.on_copy(app)
        self.assertEqual(app.clipboard, "")
        self.assertIn("取消", "".join(app.logged))

    def test_stop_refuses_when_pids_are_unknown(self):
        app = self.make_app()
        asked, killed = [], []
        app._ask_main = lambda fn, *args: asked.append(args)
        app._stop = lambda pids: killed.append(pids)
        app._pids_provider = lambda: (None, "超时：30 秒内没有返回")   # 实例级注入，不改模块全局
        self.app_cls._stop_prepare(app)
        self.assertEqual(killed, [])
        self.assertTrue(asked)

    def test_stop_lists_pids_and_asks_first(self):
        app = self.make_app()
        asked, killed = [], []
        app._ask_main = lambda fn, *args: (asked.append(args), False)[1]
        app._stop = lambda pids: killed.append(pids)
        app._pids_provider = lambda: ([111, 222], None)
        self.app_cls._stop_prepare(app)
        self.assertEqual(killed, [])
        self.assertIn("PID 111", asked[0][1])
        self.assertIn("PID 222", asked[0][1])

    def test_stop_kills_only_after_confirmation(self):
        app = self.make_app()
        killed = []
        app._ask_main = lambda fn, *args: True
        app._stop = lambda pids: killed.append(pids)
        app._pids_provider = lambda: ([111], None)
        self.app_cls._stop_prepare(app)
        self.assertEqual(killed, [[111]])


if __name__ == "__main__":
    unittest.main()
