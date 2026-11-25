"""免 token 直连：只做「跳一次」的门，两个结果都必须说清。

真起一个 HTTP 服务在回环端口上验，而不是只测字符串拼接 —— 这条路的全部风险都在
「302 的 Location 带的是哪把 token」「没有 token 时会不会把 401 甩给手机」。
"""
from __future__ import annotations

import json
import socket
import unittest
import urllib.error
import urllib.request

from dshconsole import bridge


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


class TargetAuthorityTests(unittest.TestCase):
    def test_port_is_swapped_to_the_dsh_port(self):
        self.assertEqual(bridge.target_authority("100.1.2.3:3081", 3080), "100.1.2.3:3080")
        self.assertEqual(bridge.target_authority("127.0.0.1:58553", 3080), "127.0.0.1:3080")

    def test_host_without_port_is_kept_for_the_serve_path(self):
        self.assertEqual(bridge.target_authority("valkiriya.tail679d87.ts.net", 3080),
                         "valkiriya.tail679d87.ts.net")


class MintCookieTests(unittest.TestCase):
    def test_exchange_uses_the_callers_authority_and_returns_set_cookie(self):
        seen = {}

        class FakeResponse:
            status = 303

            def read(self):
                return b""

            def getheader(self, name):
                return "dsh-auth-z=1; Path=/" if name == "Set-Cookie" else None

        class FakeConn:
            def __init__(self, host, port, timeout=None):
                seen["host"], seen["port"] = host, port

            def request(self, method, path, headers=None):
                seen["path"], seen["headers"] = path, headers or {}

            def getresponse(self):
                return FakeResponse()

            def close(self):
                seen["closed"] = True

        cookie = bridge.mint_cookie("100.1.2.3:3080", "tok-9", 3080,
                                    client=lambda host, port, timeout: FakeConn(host, port, timeout))
        self.assertEqual(cookie, "dsh-auth-z=1; Path=/")
        self.assertEqual(seen["host"], "127.0.0.1")
        self.assertEqual(seen["port"], 3080)
        self.assertEqual(seen["path"], "/?token=tok-9")
        self.assertEqual(seen["headers"], {"Host": "100.1.2.3:3080"})
        self.assertTrue(seen["closed"])


class RedirectUrlTests(unittest.TestCase):
    def test_url_carries_token_and_dsh_port(self):
        self.assertEqual(bridge.redirect_url("100.1.2.3", 3080, "tok"),
                         "http://100.1.2.3:3080/?token=tok")


class RelayTests(unittest.TestCase):
    def _start(self, token="tok", port=None):
        port = port or free_port()
        # mint 注入成「换不到 cookie」：这两个用例测的是退回带 token 跳转那条老路，
        # 不测「真的连上本机 3080」——测试不该依赖机器上有没有在跑的 DSH。
        relay = bridge.Relay("127.0.0.1", port=port, dsh_port=3080,
                             token_provider=lambda: token, mint=lambda authority, tok: None)
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
        relay = bridge.Relay("127.0.0.1", port=port, token_provider=lambda: box["token"],
                             mint=lambda authority, tok: None)
        relay.start()
        self.addCleanup(relay.stop)
        _status, headers, _body = self._get(relay.url)
        self.assertIn("first", headers.get("Location", ""))
        box["token"] = "second"          # DSH 重启换了 token，不用重开这个开关
        _status, headers, _body = self._get(relay.url)
        self.assertIn("second", headers.get("Location", ""))

    def test_cookie_is_handed_to_the_phone_and_address_has_no_token(self):
        port = free_port()
        relay = bridge.Relay("127.0.0.1", port=port, dsh_port=3080,
                             token_provider=lambda: "tok",
                             mint=lambda authority, tok: "dsh-auth-x=1; Path=/; HttpOnly")
        relay.start()
        self.addCleanup(relay.stop)
        status, headers, _body = self._get(relay.url)
        self.assertEqual(status, 302)
        self.assertEqual(headers.get("Set-Cookie"), "dsh-auth-x=1; Path=/; HttpOnly")
        self.assertEqual(headers.get("Location"), "http://127.0.0.1:3080/")
        self.assertNotIn(":58553", headers.get("Location", ""))
        self.assertNotIn("token=", headers.get("Location", ""))

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


class RelayTargetProviderTests(unittest.TestCase):
    def test_target_provider_redirects_to_reachable_address(self):
        port = free_port()
        relay = bridge.Relay("127.0.0.1", port=port, token_provider=lambda: "tok",
                             target_provider=lambda tok: f"http://phone.test/?token={tok}")
        relay.start()
        self.addCleanup(relay.stop)
        opener = urllib.request.build_opener(_NoRedirect())
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            opener.open(relay.url, timeout=5)
        self.assertEqual(ctx.exception.code, 302)
        self.assertEqual(ctx.exception.headers.get("Location"), "http://phone.test/?token=tok")


class ConsoleRouteTests(unittest.TestCase):
    """/console 是手机端唯一的操作面：状态只读、动作要码、token 一个字都不能漏。"""

    def _start(self, state=None, handler=None, token="tok-secret"):
        port = free_port()
        relay = bridge.Relay("127.0.0.1", port=port, dsh_port=3080,
                             token_provider=lambda: token, mint=lambda authority, tok: None,
                             state_provider=state, action_handler=handler)
        relay.start()
        self.addCleanup(relay.stop)
        return relay

    def _get(self, url):
        with urllib.request.urlopen(url, timeout=3) as response:
            return response.status, dict(response.headers), response.read()

    def _post(self, url, body, headers=None):
        request = urllib.request.Request(url, data=body, method="POST",
                                         headers=headers or {"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(request, timeout=3) as response:
                return response.status, response.read()
        except urllib.error.HTTPError as exc:
            try:
                return exc.code, exc.read()
            finally:
                exc.close()

    def test_console_page_is_served(self):
        relay = self._start()
        status, headers, body = self._get(relay.url + "console")
        self.assertEqual(status, 200)
        self.assertIn("text/html", headers.get("Content-Type", ""))
        self.assertEqual(headers.get("Cache-Control"), "no-store")
        self.assertIn("手机", body.decode("utf-8"))

    def test_state_json_carries_the_provider_payload_but_never_the_token(self):
        relay = self._start(state=lambda: {"phase": "running", "pid": 4242})
        status, _headers, body = self._get(relay.url + "console.json")
        self.assertEqual(status, 200)
        payload = json.loads(body.decode("utf-8"))
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["pid"], 4242)
        self.assertNotIn("tok-secret", body.decode("utf-8"))

    def test_state_without_a_provider_is_reported_not_faked(self):
        relay = self._start()
        _status, _headers, body = self._get(relay.url + "console.json")
        payload = json.loads(body.decode("utf-8"))
        self.assertFalse(payload["ok"])
        self.assertIn("message", payload)

    def test_state_provider_failure_does_not_500_the_phone(self):
        def boom():
            raise RuntimeError("窗口还没建好")

        relay = self._start(state=boom)
        status, _headers, body = self._get(relay.url + "console.json")
        self.assertEqual(status, 200)
        payload = json.loads(body.decode("utf-8"))
        self.assertFalse(payload["ok"])
        self.assertIn("窗口还没建好", payload["message"])

    def test_action_passes_the_code_and_intent_to_the_handler(self):
        seen = []

        def handler(code, intent):
            seen.append((code, intent))
            return True, "已开始：重启 DSH"

        relay = self._start(handler=handler)
        status, body = self._post(relay.url + "console/action",
                                  json.dumps({"code": "123456", "intent": "restart"}).encode())
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body.decode("utf-8")),
                         {"ok": True, "message": "已开始：重启 DSH"})
        self.assertEqual(seen, [("123456", "restart")])

    def test_refused_action_comes_back_as_403_with_the_reason(self):
        relay = self._start(handler=lambda code, intent: (False, "动作码不对"))
        status, body = self._post(relay.url + "console/action",
                                  json.dumps({"code": "000000", "intent": "stop"}).encode())
        self.assertEqual(status, 403)
        self.assertFalse(json.loads(body.decode("utf-8"))["ok"])

    def test_handler_exception_is_a_refusal_not_a_crash(self):
        def handler(code, intent):
            raise RuntimeError("端口关不掉")

        relay = self._start(handler=handler)
        status, body = self._post(relay.url + "console/action",
                                  json.dumps({"code": "123456", "intent": "stop"}).encode())
        self.assertEqual(status, 403)
        self.assertIn("端口关不掉", json.loads(body.decode("utf-8"))["message"])

    def test_action_without_a_handler_is_not_implemented(self):
        relay = self._start()
        status, _body = self._post(relay.url + "console/action", b"{}")
        self.assertEqual(status, 501)

    def test_post_to_any_other_path_is_method_not_allowed(self):
        relay = self._start(handler=lambda code, intent: (True, "x"))
        status, _body = self._post(relay.url + "other", b"{}")
        self.assertEqual(status, 405)

    def test_malformed_body_is_a_bad_request(self):
        relay = self._start(handler=lambda code, intent: (True, "x"))
        status, _body = self._post(relay.url + "console/action", b"not json")
        self.assertEqual(status, 400)


if __name__ == "__main__":
    unittest.main()
