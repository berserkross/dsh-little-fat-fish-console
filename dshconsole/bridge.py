"""免 token 直连：在 tailnet 地址上开一个只做「跳一次」的小门。

为什么不做反向代理：DSH 的网页有自己的 cookie 会话和流式推送，把每条请求都代理一遍
既容易在 SSE/WebSocket 上翻车，也等于把 token 抄进每一层。这里只做一件事 ——
任何一个请求进来，都 302 到「当前 token 的 DSH 地址」，由 DSH 自己种 cookie。
之后手机直接开 http://<tailnet-ip>:<dsh 端口>/ 就一直有效，直到 DSH 重启换 token。

安全边界：监听地址由调用方给（控制台只绑 Tailscale 那个 IP），所以这条路只对
tailnet 成员开放；它在效果上等于「把 token 贴在门上」，因此必须是一个显式开关。
"""
from __future__ import annotations

import http.client
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Callable

RELAY_PORT = 3081
CONSOLE_PATH = "/console"
CONSOLE_JSON_PATH = "/console.json"
ACTION_PATH = "/console/action"
MAX_BODY = 4096            # 动作请求只该是一小段 JSON，大的就是打错了
CONSOLE_PAGE = """<!doctype html><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>小肥鱼控制台 · 手机</title>
<style>
:root{color-scheme:dark}
body{margin:0;padding:18px;background:#0b1020;color:#e8ecf8;
     font:15px/1.5 system-ui,-apple-system,"Segoe UI","Microsoft YaHei",sans-serif}
h1{font-size:16px;margin:0 0 14px;font-weight:600;color:#b9c3da}
.card{background:#141a2e;border:1px solid #232b45;border-radius:14px;padding:14px 16px;margin-bottom:12px}
.big{font-size:26px;font-weight:700;margin-bottom:6px}
.row{display:flex;justify-content:space-between;gap:12px;padding:3px 0;color:#9aa4bd}
.row b{color:#e8ecf8;font-weight:600;font-variant-numeric:tabular-nums}
.mono{font-family:ui-monospace,Consolas,monospace}
input{width:100%;box-sizing:border-box;margin-top:12px;padding:12px;border-radius:10px;
      border:1px solid #2b3452;background:#0f1526;color:#e8ecf8;
      font:17px ui-monospace,Consolas,monospace;letter-spacing:7px;text-align:center}
button{flex:1;min-width:92px;padding:12px 10px;border-radius:10px;border:1px solid #2b3452;
       background:#1b2440;color:#e8ecf8;font-size:15px}
button:active{background:#26325a}
.actions{display:flex;gap:8px;margin-top:10px}
.hint{color:#7d879e;font-size:12.5px;margin-top:10px}
.err{color:#f2a65a}.ok{color:#5fd18d}
</style>
<h1>小肥鱼控制台 · 手机</h1>
<div class="card"><div class="big" id="phase">…</div><div id="facts"></div></div>
<div class="card">
  <div class="row"><span>动作码</span><b id="code">未签发</b></div>
  <input id="otp" inputmode="numeric" autocomplete="one-time-code" maxlength="6" placeholder="6 位动作码">
  <div class="actions">
    <button data-intent="start">启动</button>
    <button data-intent="restart">重启</button>
    <button data-intent="stop">关闭</button>
    <button data-intent="interrupt">中断会话</button>
  </div>
  <div class="hint" id="msg">动作要先在电脑上点一下底栏的「手机动作码」：60 秒有效，用一次作废。</div>
</div>
<script>
var $ = function (id) { return document.getElementById(id); };
function row(name, value) {
  var line = document.createElement('div');
  line.className = 'row';
  var k = document.createElement('span'); k.textContent = name;
  var v = document.createElement('b'); v.textContent = (value === null || value === undefined || value === '') ? '—' : String(value);
  line.appendChild(k); line.appendChild(v);
  return line;
}
function yes(flag) { return flag === true ? '是' : (flag === false ? '否' : '未知'); }
function draw(d) {
  $('phase').textContent = d.label || '未知';
  var facts = $('facts'); facts.innerHTML = '';
  facts.appendChild(row('Web 端口', d.port));
  facts.appendChild(row('进程 PID', d.pid));
  facts.appendChild(row('端口在监听', yes(d.port_open)));
  facts.appendChild(row('应网页请求', yes(d.serving)));
  facts.appendChild(row('手机访问', yes(d.phone_open)));
  facts.appendChild(row('Tailscale', d.ts_ip));
  facts.appendChild(row('免 token 直连', d.relay ? '已开' : '关'));
  $('code').textContent = d.code_remaining > 0 ? d.code_remaining + ' 秒后过期' : '未签发';
}
async function tick() {
  try {
    var res = await fetch('/console.json', { cache: 'no-store' });
    var d = await res.json();
    if (!d.ok) { $('phase').textContent = d.message || '控制台读不到状态'; return; }
    draw(d);
  } catch (e) {
    $('phase').textContent = '连不上控制台';
  }
}
Array.prototype.forEach.call(document.querySelectorAll('button[data-intent]'), function (btn) {
  btn.onclick = async function () {
    var msg = $('msg');
    msg.className = 'hint';
    msg.textContent = '正在请求…';
    try {
      var res = await fetch('/console/action', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ code: $('otp').value.trim(), intent: btn.dataset.intent })
      });
      var d = await res.json();
      msg.textContent = d.message || '';
      msg.className = d.ok ? 'ok' : 'err';
      if (d.ok) { $('otp').value = ''; }
    } catch (e) {
      msg.textContent = '请求没送到：' + e;
      msg.className = 'err';
    }
    tick();
  };
});
tick();
setInterval(tick, 3000);
</script>"""

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


def target_authority(authority: str, dsh_port: int = 3080) -> str:
    """手机落点用的 authority：换掉端口，主机名与主机形式保持原样。

    手机是开 http://<tailnet-ip>:3081 进来的，cookie 却与 :3080 那个 authority 绑定，
    所以换 cookie 和跳转都必须指向 3080；Host 没带端口（走的 :80 serve）就原样保留。
    """
    host, sep, _port = authority.rpartition(":")
    if not sep or not host:
        return authority
    return f"{host}:{int(dsh_port)}"


def mint_cookie(authority: str, token: str, dsh_port: int = 3080,
                timeout: float = 6.0, client=None) -> str | None:
    """用「手机此刻用的那个 Host」去换一次 cookie，返回 DSH 给的 Set-Cookie 原文。

    为什么要服务端来换：cookie 与 Host authority 绑定（见 dsh-client-connection 的
    requestAudience / authenticate），手机自己带 token 跳转时，中间任何一层改写 Host
    都会让换出来的 cookie 用不了。这里用请求里的 Host 去换，换到的正是手机能用的那块。
    换不到就返回 None，调用方退回「带 token 跳转」那条老路。
    """
    factory = client or (lambda host, port, timeout: http.client.HTTPConnection(host, port, timeout=timeout))
    try:
        conn = factory("127.0.0.1", int(dsh_port), timeout)
        try:
            conn.request("GET", f"/?token={token}", headers={"Host": authority})
            response = conn.getresponse()
            response.read()
            if response.status not in (200, 302, 303, 307):
                return None
            return response.getheader("Set-Cookie")
        finally:
            conn.close()
    except OSError:
        return None


class _Handler(BaseHTTPRequestHandler):
    server_version = "DshConsoleRelay"

    def do_GET(self):            # noqa: N802 - BaseHTTPRequestHandler 约定
        self._route(body=True)

    def do_HEAD(self):           # noqa: N802
        self._route(body=False)

    def _route(self, body: bool) -> None:
        """三条例外路由（手机控制台），其余一律还是那张「跳一次」的门。"""
        path = self.path.split("?", 1)[0].rstrip("/") or "/"
        if path == CONSOLE_PATH:
            return self._send(CONSOLE_PAGE.encode("utf-8"), "text/html; charset=utf-8", 200, body)
        if path == CONSOLE_JSON_PATH:
            return self._json(self._state_payload(), body=body)
        return self._bounce(body=body)

    def do_POST(self):           # noqa: N802
        body = self._read_body()     # 先读干净再回话，否则客户端收到的是 RST 不是 405/501
        if self.path.split("?", 1)[0].rstrip("/") != ACTION_PATH:
            return self._json({"ok": False, "message": "只支持 POST " + ACTION_PATH}, status=405)
        handler = getattr(self.server, "action_handler", None)   # type: ignore[attr-defined]
        if handler is None:
            return self._json({"ok": False, "message": "这一版控制台没有接动作"}, status=501)
        if body is None:
            return self._json({"ok": False, "message": "请求体大小不对"}, status=400)
        try:
            payload = json.loads(body.decode("utf-8"))
            code = str(payload.get("code") or "")
            intent = str(payload.get("intent") or "")
        except (ValueError, AttributeError):
            return self._json({"ok": False, "message": "请求体不是 JSON"}, status=400)
        try:
            ok, message = handler(code, intent)
        except Exception as exc:     # noqa: BLE001 - 回给手机的是结论，不是栈
            ok, message = False, f"执行失败：{exc}"
        return self._json({"ok": bool(ok), "message": str(message)},
                          status=200 if ok else 403)

    def _read_body(self) -> bytes | None:
        """按 Content-Length 读掉请求体；长度缺失、超限或不是数字都算不合格。"""
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            return None
        if length <= 0 or length > MAX_BODY:
            return None
        return self.rfile.read(length)

    def _state_payload(self) -> dict:
        provider = getattr(self.server, "state_provider", None)   # type: ignore[attr-defined]
        if provider is None:
            return {"ok": False, "message": "这一版控制台没有接状态"}
        try:
            payload = dict(provider() or {})
        except Exception as exc:     # noqa: BLE001
            return {"ok": False, "message": f"取状态失败：{exc}"}
        payload["ok"] = True
        return payload

    def _json(self, payload: dict, status: int = 200, body: bool = True) -> None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self._send(data, "application/json; charset=utf-8", status, body)

    def _send(self, payload: bytes, ctype: str, status: int, body: bool) -> None:
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        if body:
            self.wfile.write(payload)

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
        provider = getattr(self.server, "target_provider", None)
        direct = provider(token) if provider else None
        if direct:
            # 把手机直接送到「它真能打开、且 Host 与 cookie 对得上」的地址去；token 由 DSH 自己换。
            self.send_response(302)
            self.send_header("Location", direct)
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        requested = self.headers.get("Host") or self.server.default_authority   # type: ignore[attr-defined]
        authority = target_authority(requested, self.server.dsh_port)           # type: ignore[attr-defined]
        cookie = self.server.mint(authority, token)     # type: ignore[attr-defined]
        # 换到了 cookie 就把它直接交给手机，地址里不再出现 token：手机之后自己开
        # http://<authority>/ 也进得去（cookie 与这个 Host 绑定，正是它要用的那块）。
        self.send_response(302)
        self.send_header("Location", f"http://{authority}/" if cookie else self.server.target_url(token))
        if cookie:
            self.send_header("Set-Cookie", cookie)
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
                 server_factory=None, mint=None,
                 target_provider: Callable[[str], str | None] | None = None,
                 state_provider: Callable[[], dict] | None = None,
                 action_handler: Callable[[str, str], tuple[bool, str]] | None = None):
        self.host = host
        self.port = int(port)
        self.dsh_port = int(dsh_port)
        self._token_provider = token_provider or (lambda: None)
        self._factory = server_factory or _Server
        # 换 cookie 这一步可以注入：测试不该真去连本机 3080 上的 DSH。
        self._mint = mint or (lambda authority, tok: mint_cookie(authority, tok, self.dsh_port))
        # 手机该被送到哪个地址：serve 的域名、能直连的 IP 都行，由调用方按当前网络算。
        # 给了就用它（地址里带 token，DSH 自己种 cookie），没给才回退到旧的换 cookie 逻辑。
        self._target_provider = target_provider
        # 手机控制台：状态由控制台给（只读），动作要过一次性码（见 portal.ActionGate）。
        self._state_provider = state_provider
        self._action_handler = action_handler
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
        httpd.dsh_port = self.dsh_port                    # type: ignore[attr-defined]
        httpd.default_authority = f"{self.host}:{self.dsh_port}"  # type: ignore[attr-defined]
        httpd.mint = self._mint                          # type: ignore[attr-defined]
        httpd.target_provider = self._target_provider    # type: ignore[attr-defined]
        httpd.state_provider = self._state_provider      # type: ignore[attr-defined]
        httpd.action_handler = self._action_handler      # type: ignore[attr-defined]
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
