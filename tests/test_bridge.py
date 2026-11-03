"""免 token 直连：只做「跳一次」的门，两个结果都必须说清。

真起一个 HTTP 服务在回环端口上验，而不是只测字符串拼接 —— 这条路的全部风险都在
「302 的 Location 带的是哪把 token」「没有 token 时会不会把 401 甩给手机」。
"""
from __future__ import annotations

import socket
import unittest
import urllib.error
import urllib.request

from dshconsole import bridge


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


class RedirectUrlTests(unittest.TestCase):
    def test_url_carries_token_and_dsh_port(self):
        self.assertEqual(bridge.redirect_url("100.1.2.3", 3080, "tok"),
                         "http://100.1.2.3:3080/?token=tok")


class RelayTests(unittest.TestCase):
    def _start(self, token="tok", port=None):
        port = port or free_port()
        relay = bridge.Relay("127.0.0.1", port=port, dsh_port=3080,
                             token_provider=lambda: token)
        relay.start()
        self.addCleanup(relay.stop)
        return relay

    def _get(self, url):
        opener = urllib.request.build_opener(_NoRedirect())
        try:
            with opener.open(url, timeout=3) as response:
                return response.status, dict(response.headers), response.read()
        except urllib.error.HTTPError as exc:
            return exc.code, dict(exc.headers), b""

    def test_request_is_bounced_with_the_live_token(self):
        relay = self._start("tok-123")
        status, headers, _body = self._get(relay.url + "some/page?x=1")
        self.assertEqual(status, 302)
        self.assertEqual(headers.get("Location"), "http://127.0.0.1:3080/?token=tok-123")
        self.assertEqual(headers.get("Cache-Control"), "no-store")

    def test_missing_token_answers_a_page_instead_of_a_broken_redirect(self):
        relay = self._start(None)
        status, headers, body = self._get(relay.url)
        self.assertEqual(status, 200)
        self.assertIn("text/html", headers.get("Content-Type", ""))
        self.assertIn("token", body.decode("utf-8"))

    def test_token_is_read_per_request(self):
        box = {"token": "first"}
        port = free_port()
        relay = bridge.Relay("127.0.0.1", port=port, token_provider=lambda: box["token"])
        relay.start()
        self.addCleanup(relay.stop)
        _status, headers, _body = self._get(relay.url)
        self.assertIn("first", headers.get("Location", ""))
        box["token"] = "second"          # DSH 重启换了 token，不用重开这个开关
        _status, headers, _body = self._get(relay.url)
        self.assertIn("second", headers.get("Location", ""))

    def test_stop_releases_the_port(self):
        port = free_port()
        relay = bridge.Relay("127.0.0.1", port=port, token_provider=lambda: "tok")
        relay.start()
        self.assertTrue(relay.running)
        relay.stop()
        self.assertFalse(relay.running)
        again = bridge.Relay("127.0.0.1", port=port, token_provider=lambda: "tok")
        again.start()                    # 端口能立刻再绑 = 真的关干净了
        self.addCleanup(again.stop)

    def test_busy_port_raises_oserror(self):
        first = self._start()
        second = bridge.Relay(first.host, port=first.port, token_provider=lambda: "tok")
        with self.assertRaises(OSError):
            second.start()


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """不要让 urllib 帮我们跟 302 —— 我们要看的就是那条 302。"""

    def redirect_request(self, *_args, **_kwargs):
        return None


if __name__ == "__main__":
    unittest.main()
