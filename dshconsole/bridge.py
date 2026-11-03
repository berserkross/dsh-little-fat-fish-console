"""免 token 直连：在 tailnet 地址上开一个只做「跳一次」的小门。

为什么不做反向代理：DSH 的网页有自己的 cookie 会话和流式推送，把每条请求都代理一遍
既容易在 SSE/WebSocket 上翻车，也等于把 token 抄进每一层。这里只做一件事 ——
任何一个请求进来，都 302 到「当前 token 的 DSH 地址」，由 DSH 自己种 cookie。
之后手机直接开 http://<tailnet-ip>:<dsh 端口>/ 就一直有效，直到 DSH 重启换 token。

安全边界：监听地址由调用方给（控制台只绑 Tailscale 那个 IP），所以这条路只对
tailnet 成员开放；它在效果上等于「把 token 贴在门上」，因此必须是一个显式开关。
"""
from __future__ import annotations

import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Callable

RELAY_PORT = 3081
NO_TOKEN_PAGE = """<!doctype html><meta charset="utf-8">
<title>DSH 直连：暂时没有可用的 token</title>
<body style="font-family:system-ui;background:#0b1020;color:#e8ecf8;padding:40px">
<h1 style="font-size:20px">暂时没有可用的 token</h1>
<p>请回到电脑上的「小肥鱼控制台」，点一次「重启 DSH」重新签发 token，再刷新本页。</p>
<p style="color:#8b93a7">（token 每次启动都会换，旧的那把会失效。）</p>
</body>"""


def redirect_url(host: str, dsh_port: int, token: str) -> str:
    """带 token 的落点。path 一律回到根：DSH 认了 token 会自己种 cookie 再跳走。"""
    return f"http://{host}:{int(dsh_port)}/?token={token}"


class _Handler(BaseHTTPRequestHandler):
    server_version = "DshConsoleRelay"

    def do_GET(self):            # noqa: N802 - BaseHTTPRequestHandler 约定
        self._bounce(body=True)

    def do_HEAD(self):           # noqa: N802
        self._bounce(body=False)

    def _bounce(self, body: bool) -> None:
        token = self.server.token_provider()            # type: ignore[attr-defined]
        if not token:
            payload = NO_TOKEN_PAGE.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            if body:
                self.wfile.write(payload)
            return
        location = self.server.target_url(token)        # type: ignore[attr-defined]
        self.send_response(302)
        self.send_header("Location", location)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def log_message(self, *args):   # 静默：这条路每开一次页面就一条日志，别淹没界面
        return


class _Server(ThreadingHTTPServer):
    """默认的 ThreadingHTTPServer 开着 SO_REUSEADDR：Windows 上这会让「端口被占」也绑定成功，
    于是开关看起来开了、手机却连到别人的服务上。这里关掉，占用就老老实实报 OSError。"""

    allow_reuse_address = False


class Relay:
    """一个只在 tailnet 地址上监听、把请求 302 到带 token 地址的小服务。"""

    def __init__(self, host: str, port: int = RELAY_PORT, dsh_port: int = 3080,
                 token_provider: Callable[[], str | None] | None = None,
                 server_factory=None):
        self.host = host
        self.port = int(port)
        self.dsh_port = int(dsh_port)
        self._token_provider = token_provider or (lambda: None)
        self._factory = server_factory or _Server
        self._server = None
        self._thread = None

    @property
    def url(self) -> str:
        return f"http://{self.host}:{self.port}/"

    @property
    def running(self) -> bool:
        return self._server is not None

    def start(self) -> None:
        """起服务；端口被占/地址不可用就把 OSError 抛给调用方（那里要写进日志）。"""
        if self._server is not None:
            return
        httpd = self._factory((self.host, self.port), _Handler)
        httpd.token_provider = self._token_provider        # type: ignore[attr-defined]
        httpd.target_url = lambda tok: redirect_url(self.host, self.dsh_port, tok)  # type: ignore[attr-defined]
        self._server = httpd
        self._thread = threading.Thread(target=httpd.serve_forever, name="dsh-relay", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        server, self._server = self._server, None
        if server is None:
            return
        try:
            server.shutdown()
            server.server_close()
        finally:
            self._thread = None
