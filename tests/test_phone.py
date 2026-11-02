"""手机访问策略：serve 优先、自动回退、回环永不进二维码。全部注入事实，不碰真机。"""
import unittest
from collections import namedtuple

from dshconsole import addresses, phone, tailscale

Result = namedtuple("Result", "returncode stdout stderr")


class FakeSpawn:
    """按 argv 尾部匹配返回假输出（最长 needle 优先）；记录每次调用。"""

    def __init__(self, routes, default=(1, "")):
        self.routes = routes
        self.default = default
        self.calls = []

    def __call__(self, argv, **kwargs):
        self.calls.append(list(argv))
        key = " ".join(str(part) for part in argv[1:])
        for needle in sorted(self.routes, key=len, reverse=True):
            if needle in key:
                code, out = self.routes[needle]
                return Result(code, str(out).encode("utf-8"), b"")
        code, out = self.default
        return Result(code, str(out).encode("utf-8"), b"")

    def args_of(self, needle):
        return [argv for argv in self.calls if needle in " ".join(argv)]


# 真机抄下来的两份输出，detect_plan 的用例靠它们走真实解析路径。
LIVE_STATUS = '{"BackendState": "Running", "MagicDNSSuffix": "tail679d87.ts.net",' \
              ' "CurrentTailnet": {"Name": "berserkross.github", "MagicDNSEnabled": true},' \
              ' "Self": {"DNSName": "valkiriya.tail679d87.ts.net.",' \
              ' "TailscaleIPs": ["100.124.206.105", "fd7a:115c:a1e0::5501:cee3"]},' \
              ' "CertDomains": []}'
LIVE_SERVE = ('{"TCP": {"80": {"HTTP": true}}, "Web": {"valkiriya.tail679d87.ts.net:80": '
              '{"Handlers": {"/": {"Proxy": "http://127.0.0.1:3080"}}}}}')

DNS = "valkiriya.tail679d87.ts.net"
IPV4 = "100.124.206.105"
IPV6 = "fd7a:115c:a1e0::5501:cee3"
TOKEN = "tok123"


def facts(cert=(), state="Running", dns=DNS, ips=(IPV4, IPV6), magicdns=True):
    return tailscale.Facts(backend_state=state, dns_name=dns, tailscale_ips=tuple(ips),
                           magic_dns_enabled=magicdns, magic_dns_suffix="tail679d87.ts.net",
                           cert_domains=tuple(cert))


def detection(**kwargs):
    return tailscale.Detection(cli="C:\\fake\\tailscale.exe", facts=facts(**kwargs))


class ServeFirstTests(unittest.TestCase):
    def test_https_serve_wins_when_certificates_are_ready(self):
        got = phone.plan(3080, token=TOKEN, detection=detection(cert=(DNS,)))
        self.assertEqual(got.mode, phone.MODE_SERVE)
        self.assertEqual(got.scheme, addresses.SCHEME_HTTPS)
        self.assertEqual(got.qr_url, f"https://{DNS}/?token={TOKEN}")
        self.assertEqual(got.failures, ())
        self.assertEqual(got.next_step, phone.NEXT_READY)

    def test_https_blocked_degrades_to_http_serve_instead_of_failing(self):
        got = phone.plan(3080, token=TOKEN, detection=detection(cert=()))
        self.assertEqual(got.mode, phone.MODE_SERVE)          # 仍然是 serve，只是换协议
        self.assertEqual(got.scheme, addresses.SCHEME_HTTP)
        self.assertEqual(got.qr_url, f"http://{DNS}/?token={TOKEN}")
        self.assertEqual([r.code for r in got.failures], [tailscale.HTTPS_DISABLED])
        self.assertEqual(got.next_step, phone.NEXT_HTTPS)
        self.assertTrue(got.degraded)

    def test_serve_candidate_outranks_the_tailscale_ips(self):
        got = phone.plan(3080, token=TOKEN, detection=detection(cert=(DNS,)))
        self.assertEqual([c.tier for c in got.candidates],
                         [addresses.TIER_SERVE, addresses.TIER_TAILSCALE, addresses.TIER_TAILSCALE])
        self.assertEqual(got.candidates[1].host, IPV4)
        self.assertEqual(got.candidates[2].host, IPV6)
        self.assertEqual(got.candidates[2].url, f"http://[{IPV6}]:3080/?token={TOKEN}")

    def test_trusted_hosts_are_spelled_out_for_the_dsh_process(self):
        got = phone.plan(3080, token=TOKEN, detection=detection(cert=(DNS,)))
        self.assertIn(f"{DNS}:443", got.trusted_hosts)
        self.assertIn(f"{IPV4}:3080", got.trusted_hosts)
        # IPv6 必须带方括号，否则 dsh 收到的 Host 头与 trust 列表对不上
        self.assertIn("[fd7a:115c:a1e0::5501:cee3]:3080", got.trusted_hosts)


class FallbackTests(unittest.TestCase):
    def test_no_login_falls_back_to_portproxy_candidates(self):
        got = phone.plan(3080, token=TOKEN, detection=detection(state="NeedsLogin"))
        self.assertEqual(got.mode, phone.MODE_PROXY)
        self.assertIsNone(got.serve_host)
        self.assertEqual(got.qr_url, f"http://{IPV4}:3080/?token={TOKEN}")
        self.assertEqual([r.code for r in got.failures], [tailscale.NOT_LOGGED_IN])
        self.assertIn("tailnet", got.next_step)
        self.assertEqual(got.candidates[0].tier, addresses.TIER_TAILSCALE)

    def test_magicdns_off_falls_back_to_portproxy(self):
        got = phone.plan(3080, token=TOKEN, detection=detection(magicdns=False))
        self.assertEqual(got.mode, phone.MODE_PROXY)
        self.assertEqual([r.code for r in got.failures], [tailscale.NO_MAGICDNS])

    def test_missing_cli_leaves_no_candidates_at_all(self):
        missing = tailscale.Detection(error=tailscale.Reason(tailscale.CLI_MISSING, "没装"))
        got = phone.plan(3080, token=TOKEN, detection=missing)
        self.assertEqual(got.mode, phone.MODE_NONE)
        self.assertEqual(got.candidates, ())
        self.assertIsNone(got.qr_url)                 # 宁可不画二维码，也不编码回环地址
        self.assertEqual([r.code for r in got.failures], [tailscale.CLI_MISSING])
        self.assertTrue(got.next_step)

    def test_caller_supplied_lan_addresses_join_the_fallback(self):
        lan = [addresses.Address("10.23.115.16", "以太网", "lan")]
        got = phone.plan(3080, token=TOKEN, detection=detection(state="Stopped"),
                         addresses_list=lan)
        self.assertEqual([c.host for c in got.candidates], ["10.23.115.16"])
        self.assertEqual(got.mode, phone.MODE_PROXY)


class LoopbackNeverLeaksTests(unittest.TestCase):
    def test_loopback_in_the_supplied_pool_is_dropped(self):
        pool = [addresses.Address("127.0.0.1", "本机", "local"),
                addresses.Address(IPV4, "Tailscale", "tailscale"),
                addresses.Address("localhost", "本机", "local")]
        got = phone.plan(3080, token=TOKEN, detection=detection(state="Stopped"),
                         addresses_list=pool)
        self.assertEqual([c.host for c in got.candidates], [IPV4])
        self.assertNotIn("127.0.0.1", " ".join(c.url for c in got.candidates))

    def test_a_loopback_only_pool_yields_none_mode(self):
        pool = [addresses.Address("127.0.0.1", "本机", "local")]
        got = phone.plan(3080, detection=detection(state="Stopped", ips=()),
                         addresses_list=pool)
        self.assertEqual(got.mode, phone.MODE_NONE)
        self.assertIsNone(got.primary)


class DetectPlanTests(unittest.TestCase):
    """detect_plan 只碰 serve 层：给足假 CLI，断言它到底发了几条命令。"""

    def setUp(self):
        self.FakeSpawn = FakeSpawn
        self.live_status = LIVE_STATUS
        self.live_serve = LIVE_SERVE
        self.which = lambda name: "C:\\fake\\tailscale.exe"

    def test_existing_serve_is_not_restarted(self):
        spawn = self.FakeSpawn({"status --json": (0, self.live_status),
                                "serve status --json": (0, self.live_serve)})
        got = phone.detect_plan(3080, token=TOKEN, spawn=spawn, which=self.which)
        self.assertEqual(got.mode, phone.MODE_SERVE)
        self.assertEqual(spawn.args_of("serve --bg"), [])

    def test_missing_serve_config_is_enabled_once(self):
        spawn = self.FakeSpawn({"status --json": (0, self.live_status),
                                "serve status --json": (0, "No serve config"),
                                "serve --bg": (0, "Serve started")})
        got = phone.detect_plan(3080, token=TOKEN, spawn=spawn, which=self.which)
        self.assertEqual(got.mode, phone.MODE_SERVE)
        self.assertEqual(len(spawn.args_of("serve --bg")), 1)
        self.assertIn("--http=80", " ".join(spawn.args_of("serve --bg")[0]))

    def test_serve_failure_falls_back_instead_of_raising(self):
        spawn = self.FakeSpawn({"status --json": (0, self.live_status),
                                "serve status --json": (0, "No serve config"),
                                "serve --bg": (1, "Error: serve not enabled")})
        got = phone.detect_plan(3080, token=TOKEN, spawn=spawn, which=self.which)
        self.assertEqual(got.mode, phone.MODE_PROXY)
        self.assertTrue(got.qr_url and IPV4 in got.qr_url)

    def test_no_cli_is_a_plan_not_an_exception(self):
        spawn = self.FakeSpawn({})
        got = phone.detect_plan(3080, spawn=spawn, which=lambda name: None,
                                probe=lambda path: False)
        self.assertEqual(got.mode, phone.MODE_NONE)
        self.assertEqual(spawn.calls, [])


class ChecklistTests(unittest.TestCase):
    def test_serve_mode_mentions_the_domain_and_tailnet(self):
        rows = phone.phone_checklist(phone.plan(3080, detection=detection(cert=(DNS,))))
        text = " ".join(rows)
        self.assertIn(DNS, text)
        self.assertIn("tailnet", text)

    def test_proxy_mode_mentions_firewall_and_portproxy(self):
        rows = phone.phone_checklist(
            phone.plan(3080, detection=detection(state="NeedsLogin")))
        text = " ".join(rows)
        self.assertIn("防火墙", text)
        self.assertIn("portproxy", text)

    def test_none_mode_says_there_is_nothing_to_scan(self):
        missing = tailscale.Detection(error=tailscale.Reason(tailscale.CLI_MISSING, "没装"))
        rows = phone.phone_checklist(phone.plan(3080, detection=missing))
        self.assertIn("没有任何手机可达地址", " ".join(rows))


if __name__ == "__main__":
    unittest.main()
