"""读 DSH 的会话列表、中断正在跑的会话。

DSH 没有 REST 会话接口，也没有对应 CLI：会话能力挂在 /api 上的一层 RPC 后面。
调用形状（实测）：

    POST http://127.0.0.1:<port>/api/<endpoint>
    {"type": "client-request", "rpcId": "...", "method": "<endpoint>",
     "payload": {"args": {...}}}

鉴权靠 cookie：先 `GET /?token=<token>`，响应里的 dsh-auth cookie 带进后续请求。
用到的两个 endpoint：

    session/list   args {"_request": {}}                  -> items[].{sessionId,running,updatedAt,projections}
    session/cancel args {"request": {"sessionId": "..."}} -> 中断该会话当前这一轮
"""
from __future__ import annotations

import http.cookiejar
import json
import urllib.error
import urllib.request
from dataclasses import dataclass

RPC_TIMEOUT = 6.0
LIST_ENDPOINT = "session/list"
CANCEL_ENDPOINT = "session/cancel"


class SessionsError(RuntimeError):
    """连不上、协议不认、或者 DSH 明确拒绝。"""


@dataclass(frozen=True)
class Running:
    """一条正在跑的会话：只留界面上要显示的三样。"""

    session_id: str
    title: str
    updated_at: int


class Client:
    def __init__(self, port: int, token: str, timeout: float = RPC_TIMEOUT, opener=None):
        self._port = int(port)
        self._token = str(token or "")
        self._timeout = float(timeout)
        self._opener = opener or urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
        self._authed = False

    @property
    def base(self) -> str:
        return f"http://127.0.0.1:{self._port}"

    def _auth(self) -> None:
        """token 换 cookie。302 之后 cookie 已经进 jar，重定向本身不必跟。"""
        if self._authed:
            return
        if not self._token:
            raise SessionsError("还没有 token，读不到会话列表（先刷新状态拿到 token）")
        request = urllib.request.Request(f"{self.base}/?token={self._token}")
        try:
            self._opener.open(request, timeout=self._timeout).close()
        except urllib.error.HTTPError:
            pass
        except (urllib.error.URLError, OSError) as exc:
            raise SessionsError(f"连不上 {self.base}：{exc}") from exc
        self._authed = True

    def _rpc(self, endpoint: str, args: dict) -> dict:
        self._auth()
        body = json.dumps({"type": "client-request", "rpcId": "console",
                           "method": endpoint, "payload": {"args": args}}).encode("utf-8")
        request = urllib.request.Request(f"{self.base}/api/{endpoint}", data=body,
                                         headers={"Content-Type": "application/json"},
                                         method="POST")
        try:
            with self._opener.open(request, timeout=self._timeout) as response:
                raw = response.read()
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                raise SessionsError(f"这份 DSH 不认识 {endpoint}（会话接口不可用）") from exc
            raise SessionsError(f"{endpoint} 返回 HTTP {exc.code}") from exc
        except (urllib.error.URLError, OSError) as exc:
            raise SessionsError(f"连不上 {self.base}：{exc}") from exc
        try:
            payload = json.loads(raw.decode("utf-8", "replace"))
        except ValueError as exc:
            raise SessionsError(f"{endpoint} 回来的内容不是 JSON") from exc
        result = payload.get("result") if isinstance(payload, dict) else None
        if not isinstance(result, dict) or not result.get("ok"):
            error = (result or {}).get("error") or {}
            raise SessionsError(str(error.get("message") or f"{endpoint} 被 DSH 拒绝"))
        return result.get("value") or {}

    def running(self) -> list[Running]:
        """只挑 running=true 的会话：列表里躺着的历史会话没有中断的意义。"""
        value = self._rpc(LIST_ENDPOINT, {"_request": {}})
        rows: list[Running] = []
        for item in value.get("items") or []:
            if not isinstance(item, dict) or not item.get("running"):
                continue
            projections = item.get("projections") or {}
            values = projections.get("values") if isinstance(projections, dict) else None
            title = values.get("title") if isinstance(values, dict) else None
            rows.append(Running(session_id=str(item.get("sessionId") or ""),
                                title=str(title or "（没有标题）"),
                                updated_at=int(item.get("updatedAt") or 0)))
        rows.sort(key=lambda row: row.updated_at)
        return rows

    def cancel(self, session_id: str) -> None:
        self._rpc(CANCEL_ENDPOINT, {"request": {"sessionId": str(session_id)}})


def _client(port: int, token: str, **kwargs) -> Client:
    return Client(port, token, **kwargs)


def running(port: int, token: str, **kwargs) -> list[Running]:
    return _client(port, token, **kwargs).running()


def cancel(port: int, token: str, session_ids, **kwargs) -> list[tuple[str, str]]:
    """逐个中断，返回 (会话号, 结果说明)；一个失败不影响其余。"""
    client = _client(port, token, **kwargs)
    results: list[tuple[str, str]] = []
    for session_id in session_ids:
        try:
            client.cancel(session_id)
        except SessionsError as exc:
            results.append((str(session_id), f"失败：{exc}"))
        else:
            results.append((str(session_id), "已中断"))
    return results
