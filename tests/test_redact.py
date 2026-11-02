"""日志脱敏：token 打码；剪贴板仍放完整地址。"""
from __future__ import annotations

import unittest

from dshconsole import addresses, textutil

NL = chr(10)


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

    def make_app(self):
        class Fake:
            def __init__(self):
                self.logged = []
                self.clipboard = ""
                self._token = "http://127.0.0.1:3080/?token=abc123"

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

        return Fake()

    def test_copy_local_masks_log_but_keeps_full_clipboard(self):
        app = self.make_app()
        self.app_cls.on_copy_local(app)
        self.assertEqual(app.clipboard, "http://127.0.0.1:3080/?token=abc123")
        self.assertIn("token=****", app.logged[-1])
        self.assertNotIn("abc123", "".join(app.logged))

    def test_copy_uses_the_chosen_address_and_masks_the_token(self):
        app = self.make_app()
        chosen = addresses.Address("100.124.206.105", "Tailscale", "tailscale")
        app._ask_address = lambda title, kinds=None: (chosen, 3080)   # 下拉里选中的那一条
        self.app_cls.on_copy(app)
        self.assertEqual(app.clipboard, "http://100.124.206.105:3080/?token=abc123")
        logs = "".join(app.logged)
        self.assertIn("Tailscale", logs)
        self.assertIn("token=****", logs)
        self.assertNotIn("abc123", logs)

    def test_copy_honours_the_edited_port(self):
        app = self.make_app()
        chosen = addresses.Address("10.23.115.16", "以太网", "lan")
        app._ask_address = lambda title, kinds=None: (chosen, 3099)
        self.app_cls.on_copy(app)
        self.assertEqual(app.clipboard, "http://10.23.115.16:3099/?token=abc123")

    def test_cancelled_chooser_copies_nothing(self):
        app = self.make_app()
        app._ask_address = lambda title, kinds=None: None
        self.app_cls.on_copy(app)
        self.assertEqual(app.clipboard, "")
        self.assertEqual(app.logged, [])

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
