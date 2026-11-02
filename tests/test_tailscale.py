"""Tailscale 事实层：真机抄下来的 JSON + 假 CLI，覆盖 正常/未登录/未开证书/无 CLI。"""
import unittest
from collections import namedtuple

from dshconsole import tailscale

# 以下两段都是从这台机器上真机抄下来的（只删掉了与本模块无关的键）。
LIVE_STATUS = """
{
  "Version": "1.104.2-tc3430f0d2-g598b63867",
  "BackendState": "Running",
  "MagicDNSSuffix": "tail679d87.ts.net",
  "CurrentTailnet": { "Name": "berserkross.github", "MagicDNSEnabled": true },
  "Self": {
    "DNSName": "valkiriya.tail679d87.ts.net.",
    "Online": true,
    "TailscaleIPs": ["100.124.206.105", "fd7a:115c:a1e0::5501:cee3"]
  },
  "CertDomains": []
}
"""

LIVE_SERVE = """
{
  "TCP": { "80": { "HTTP": true } },
  "Web": {
    "valkiriya.tail679d87.ts.net:80": {
      "Handlers": { "/": { "Proxy": "http://127.0.0.1:3080" } }
    }
  }
}
"""

NO_SERVE = "No serve config\n"

Result = namedtuple("Result", "returncode stdout stderr")


class FakeSpawn:
    """按 argv 尾部匹配返回假输出；记录每次调用，便于断言「没干什么」。"""

    def __init__(self, routes, default=(1, "")):
        self.routes = routes
        self.default = default
        self.calls = []

    def __call__(self, argv, **kwargs):
        self.calls.append(list(argv))
        key = " ".join(str(part) for part in argv[1:])
        # 最长的 needle 优先："serve status --json" 不能被 "status --json" 抢走
        for needle in sorted(self.routes, key=len, reverse=True):
            if needle in key:
                code, out = self.routes[needle]
                return Result(code, str(out).encode("utf-8"), b"")
        code, out = self.default
        return Result(code, str(out).encode("utf-8"), b"")

    def args_of(self, needle):
        return [argv for argv in self.calls if needle in " ".join(argv)]


class ParseStatusTests(unittest.TestCase):
    def test_reads_the_fields_the_policy_needs(self):
        facts = tailscale.parse_status(LIVE_STATUS)
        self.assertEqual(facts.backend_state, "Running")
        self.assertEqual(facts.dns_name, "valkiriya.tail679d87.ts.net")   # 结尾的点被剥掉
        self.assertEqual(facts.tailscale_ips, ("100.124.206.105", "fd7a:115c:a1e0::5501:cee3"))
        self.assertTrue(facts.magic_dns_enabled)
        self.assertEqual(facts.magic_dns_suffix, "tail679d87.ts.net")
        self.assertEqual(facts.cert_domains, ())
        self.assertTrue(facts.running)
        self.assertEqual(facts.ipv4(), "100.124.206.105")

    def test_missing_sections_do_not_explode(self):
        facts = tailscale.parse_status('{"BackendState": "NoState"}')
        self.assertFalse(facts.running)
        self.assertEqual(facts.dns_name, "")
        self.assertIsNone(facts.ipv4())

    def test_logged_out_node_still_parses(self):
        facts = tailscale.parse_status(
            '{"BackendState": "Stopped", "Self": {"DNSName": "box.ts.net."}}')
        self.assertEqual(facts.backend_state, "Stopped")
        self.assertFalse(facts.running)

    def test_garbage_and_empty_yield_none(self):
        for raw in (None, "", "   ", "not json", "{}x", "<html>"):
            self.assertIsNone(tailscale.parse_status(raw), raw)

    def test_json_behind_log_noise_is_still_found(self):
        raw = "warning: something\n" + LIVE_STATUS + "\ntrailing noise"
        self.assertEqual(tailscale.parse_status(raw).dns_name, "valkiriya.tail679d87.ts.net")


class HttpsReasonTests(unittest.TestCase):
    def test_empty_cert_domains_means_https_is_unavailable(self):
        reason = tailscale.https_reason(tailscale.parse_status(LIVE_STATUS))
        self.assertEqual(reason.code, tailscale.HTTPS_DISABLED)
        self.assertIn("CertDomains", reason.text)

    def test_matching_cert_domain_means_https_is_ready(self):
        raw = LIVE_STATUS.replace('"CertDomains": []',
                                  '"CertDomains": ["valkiriya.tail679d87.ts.net"]')
        self.assertIsNone(tailscale.https_reason(tailscale.parse_status(raw)))

    def test_a_different_cert_domain_is_not_enough(self):
        raw = LIVE_STATUS.replace('"CertDomains": []', '"CertDomains": ["other.ts.net"]')
        self.assertEqual(tailscale.https_reason(tailscale.parse_status(raw)).code,
                         tailscale.HTTPS_DISABLED)

    def test_no_facts_means_no_cli(self):
        self.assertEqual(tailscale.https_reason(None).code, tailscale.CLI_MISSING)


class HttpReasonTests(unittest.TestCase):
    def test_a_running_magicdns_node_can_serve_over_http(self):
        self.assertIsNone(tailscale.http_reason(tailscale.parse_status(LIVE_STATUS)))

    def test_not_logged_in_is_named(self):
        raw = '{"BackendState": "NeedsLogin", "Self": {"DNSName": "box.ts.net."}}'
        self.assertEqual(tailscale.http_reason(tailscale.parse_status(raw)).code,
                         tailscale.NOT_LOGGED_IN)

    def test_daemon_down_is_named(self):
        for state in ("Stopped", "NoState", "Starting", ""):
            raw = '{"BackendState": "%s", "Self": {"DNSName": "box.ts.net."}}' % state
            self.assertEqual(tailscale.http_reason(tailscale.parse_status(raw)).code,
                             tailscale.DAEMON_DOWN, state)

    def test_unknown_backend_state_is_reported_not_guessed(self):
        raw = '{"BackendState": "Weird", "Self": {"DNSName": "box.ts.net."}}'
        reason = tailscale.http_reason(tailscale.parse_status(raw))
        self.assertEqual(reason.code, tailscale.DAEMON_DOWN)
        self.assertIn("Weird", reason.text)

    def test_missing_dns_name_blocks_serve(self):
        raw = '{"BackendState": "Running", "CurrentTailnet": {"MagicDNSEnabled": true}}'
        self.assertEqual(tailscale.http_reason(tailscale.parse_status(raw)).code,
                         tailscale.NO_MAGICDNS)

    def test_magicdns_disabled_blocks_serve(self):
        raw = ('{"BackendState": "Running", "CurrentTailnet": {"MagicDNSEnabled": false},'
               ' "Self": {"DNSName": "box.ts.net."}}')
        self.assertEqual(tailscale.http_reason(tailscale.parse_status(raw)).code,
                         tailscale.NO_MAGICDNS)


class ServeConfigTests(unittest.TestCase):
    def test_real_http_route_is_parsed(self):
        config = tailscale.parse_serve_config(LIVE_SERVE)
        self.assertTrue(config.active)
        route = config.route_for(80)
        self.assertEqual(route.host, "valkiriya.tail679d87.ts.net")
        self.assertFalse(route.https)
        self.assertEqual(route.proxy, "http://127.0.0.1:3080")
        self.assertEqual(route.url(), "http://valkiriya.tail679d87.ts.net")

    def test_https_route_keeps_443_out_of_the_url(self):
        raw = ('{"TCP": {"443": {"HTTPS": true}}, "Web": {"a.ts.net:443": '
               '{"Handlers": {"/": {"Proxy": "http://127.0.0.1:3080"}}}}}')
        route = tailscale.parse_serve_config(raw).route_for(443)
        self.assertTrue(route.https)
        self.assertEqual(route.url(), "https://a.ts.net")

    def test_no_config_shapes_are_all_inactive(self):
        for raw in (NO_SERVE, "{}", "", None, "garbage"):
            self.assertFalse(tailscale.parse_serve_config(raw).active, raw)
        self.assertIsNone(tailscale.parse_serve_config(NO_SERVE).route_for(80))


class ServeArgvTests(unittest.TestCase):
    def test_http_mode_pins_port_80_and_always_says_yes(self):
        argv = tailscale.serve_argv(3080, scheme="http")
        self.assertEqual(argv[1:4], ["serve", "--bg", "--yes"])
        self.assertIn("--http=80", argv)
        self.assertEqual(argv[-1], "3080")

    def test_https_mode_is_the_cli_default(self):
        argv = tailscale.serve_argv(3080, scheme="https")
        self.assertNotIn("--http=80", argv)
        self.assertEqual(argv, ["tailscale.exe", "serve", "--bg", "--yes", "3080"])

    def test_yes_is_mandatory_because_the_cli_blocks_on_a_prompt(self):
        for scheme in ("http", "https"):
            self.assertIn("--yes", tailscale.serve_argv(3080, scheme=scheme))


class DetectTests(unittest.TestCase):
    def _which(self, path="C:\\fake\\tailscale.exe"):
        return lambda name: path

    def test_missing_cli_is_reported_without_running_anything(self):
        spawn = FakeSpawn({})
        found = tailscale.detect(spawn=spawn, which=lambda name: None, probe=lambda path: False)
        self.assertEqual(found.error.code, tailscale.CLI_MISSING)
        self.assertIsNone(found.facts)
        self.assertEqual(spawn.calls, [])

    def test_normal_detection_reads_status_and_serve(self):
        spawn = FakeSpawn({"status --json": (0, LIVE_STATUS),
                           "serve status --json": (0, LIVE_SERVE)})
        found = tailscale.detect(spawn=spawn, which=self._which())
        self.assertTrue(found.usable)
        self.assertEqual(found.facts.dns_name, "valkiriya.tail679d87.ts.net")
        self.assertTrue(found.serve.active)

    def test_unparseable_status_degrades_to_a_reason(self):
        spawn = FakeSpawn({"status --json": (1, "failed to connect")})
        found = tailscale.detect(spawn=spawn, which=self._which())
        self.assertFalse(found.usable)
        self.assertEqual(found.error.code, tailscale.DAEMON_DOWN)

    def test_enable_serve_success_and_failure(self):
        ok = FakeSpawn({"serve --bg": (0, "Serve started")})
        self.assertIsNone(tailscale.enable_serve(3080, spawn=ok, cli="C:\\ts.exe"))
        bad = FakeSpawn({"serve --bg": (1, "Error: not logged in")})
        reason = tailscale.enable_serve(3080, spawn=bad, cli="C:\\ts.exe")
        self.assertEqual(reason.code, tailscale.SERVE_FAILED)
        self.assertIn("not logged in", reason.text)

    def test_enable_serve_without_cli_does_not_spawn(self):
        spawn = FakeSpawn({})
        reason = tailscale.enable_serve(3080, spawn=spawn, cli="")
        self.assertEqual(reason.code, tailscale.CLI_MISSING)
        self.assertEqual(spawn.calls, [])

    def test_reset_serve_calls_reset(self):
        spawn = FakeSpawn({"serve reset": (0, "")})
        self.assertIsNone(tailscale.reset_serve(spawn=spawn, cli="C:\\ts.exe"))
        self.assertEqual(spawn.calls[0][1:], ["serve", "reset"])


if __name__ == "__main__":
    unittest.main()
