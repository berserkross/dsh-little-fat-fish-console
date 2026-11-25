"""dshconsole.sessions 的单元测试：RPC 形状、只挑 running、逐条中断。"""
from __future__ import annotations

import io
import json
import unittest
import urllib.error

from dshconsole import sessions


class _Response:
    def __init__(self, payload: bytes):
        self._payload = payload

    def read(self) -> bytes:
        return self._payload

    def close(self) -> None:
        pass

    def __enter__(self) -> "_Response":
        return self

    def __exit__(self, *exc) -> bool:
        return False


class _Opener:
    """按 URL 子串回话；值是 bytes / 可调用对象 / 异常。"""

    def __init__(self, routes: dict):
        self.routes = routes
        self.seen: list[tuple[str, bytes]] = []

    def open(self, request, timeout=None):
        url = request.full_url
        body = request.data or b""
        self.seen.append((url, body))
        for key, value in self.routes.items():
            if key in url:
                if isinstance(value, Exception):
                    raise value
                if callable(value):
                    return _Response(value(url, body))
                return _Response(value)
        # 先关掉自带的 fp 再抛：HTTPError 回收时若还开着会留下 ResourceWarning
        exc = urllib.error.HTTPError(url, 404, "not found", {}, io.BytesIO(b""))
        exc.close()
        raise exc


def _items(*rows: dict) -> bytes:
    return json.dumps({"result": {"ok": True, "value": {"items": list(rows)}}}).encode("utf-8")


def _ok() -> bytes:
    return json.dumps({"result": {"ok": True, "value": {}}}).encode("utf-8")


def _boom_or_ok(url: str, body: bytes) -> bytes:
    """会话号里带 bad 的那条当作连不上，其余成功。"""
    if b"bad" in body:
        raise urllib.error.URLError("boom")
    return _ok()


AUTH = {"token=": b""}


class RunningTests(unittest.TestCase):
    def test_only_running_sessions_are_kept_and_sorted_by_time(self):
        opener = _Opener({**AUTH, "/api/session/list": _items(
            {"sessionId": "late", "running": True, "updatedAt": 30,
             "projections": {"values": {"title": "晚的"}}},
            {"sessionId": "idle", "running": False, "updatedAt": 10},
            {"sessionId": "early", "running": True, "updatedAt": 20,
             "projections": {"values": {"title": ""}}},
        )})
        rows = sessions.running(3080, "tok", opener=opener)
        self.assertEqual([row.session_id for row in rows], ["early", "late"])
        self.assertEqual(rows[0].title, "（没有标题）")
        self.assertEqual(rows[1].title, "晚的")

    def test_list_call_uses_the_exact_rpc_shape(self):
        opener = _Opener({**AUTH, "/api/session/list": _items()})
        sessions.running(3080, "tok", opener=opener)
        url, body = opener.seen[-1]
        self.assertEqual(url, "http://127.0.0.1:3080/api/session/list")
        sent = json.loads(body.decode("utf-8"))
        self.assertEqual(sent["type"], "client-request")
        self.assertEqual(sent["method"], "session/list")
        self.assertEqual(set(sent["payload"]), {"args"})
        self.assertIn("_request", sent["payload"]["args"])

    def test_token_is_exchanged_for_a_cookie_first(self):
        opener = _Opener({**AUTH, "/api/session/list": _items()})
        sessions.running(3080, "tok", opener=opener)
        self.assertIn("token=tok", opener.seen[0][0])
        self.assertEqual(len(opener.seen), 2)          # 换 cookie 一次，列会话一次

    def test_missing_token_says_what_to_do(self):
        with self.assertRaises(sessions.SessionsError) as caught:
            sessions.running(3080, "", opener=_Opener({}))
        self.assertIn("token", str(caught.exception))

    def test_unknown_endpoint_is_reported_as_an_old_dsh(self):
        with self.assertRaises(sessions.SessionsError) as caught:
            sessions.running(3080, "tok", opener=_Opener(AUTH))
        self.assertIn("不认识", str(caught.exception))

    def test_refusal_carries_the_dsh_message(self):
        refused = json.dumps({"result": {"ok": False, "error": {"message": "拒绝：没有权限"}}}).encode()
        with self.assertRaises(sessions.SessionsError) as caught:
            sessions.running(3080, "tok", opener=_Opener({**AUTH, "/api/session/list": refused}))
        self.assertIn("没有权限", str(caught.exception))


class CancelTests(unittest.TestCase):
    def test_cancel_sends_the_session_id_under_request(self):
        opener = _Opener({**AUTH, "/api/session/cancel": _ok()})
        sessions.cancel(3080, "tok", ["session-abc"], opener=opener)
        _url, body = opener.seen[-1]
        sent = json.loads(body.decode("utf-8"))
        self.assertEqual(sent["payload"]["args"], {"request": {"sessionId": "session-abc"}})

    def test_one_failure_does_not_stop_the_rest(self):
        opener = _Opener({
            **AUTH,
            "/api/session/cancel": _boom_or_ok,
        })
        results = sessions.cancel(3080, "tok", ["bad-1", "ok-1"], opener=opener)
        self.assertEqual(results[0][0], "bad-1")
        self.assertTrue(results[0][1].startswith("失败："))
        self.assertIn("连不上", results[0][1])
        self.assertEqual(results[1], ("ok-1", "已中断"))


if __name__ == "__main__":
    unittest.main()
