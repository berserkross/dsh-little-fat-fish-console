"""访问地址候选：来源标注、去重、IPv6 方括号、端口校验（C4）。"""
import unittest

from dshconsole import addresses


class BuildTests(unittest.TestCase):
    def test_local_always_comes_first(self):
        found = addresses.build(None, None, None)
        self.assertEqual([item.host for item in found], [addresses.LOCAL_HOST])
        self.assertEqual(found[0].label, "本机")

    def test_tailscale_and_every_lan_address_are_listed_with_their_source(self):
        found = addresses.build("100.124.206.105", None,
                                [("10.23.115.16", "以太网"), ("10.30.107.211", "WLAN")])
        self.assertEqual([item.label for item in found], ["本机", "Tailscale", "以太网", "WLAN"])
        self.assertEqual([item.kind for item in found], ["local", "tailscale", "lan", "lan"])

    def test_duplicates_are_dropped(self):
        found = addresses.build("10.23.115.16", ["10.23.115.16"], [("10.23.115.16", "以太网")])
        self.assertEqual([item.host for item in found], ["127.0.0.1", "10.23.115.16"])
        self.assertEqual(found[1].label, "Tailscale")     # 先来的来源赢

    def test_lan_ips_without_sources_get_a_generic_label(self):
        found = addresses.build(None, ["192.168.1.5"], None)
        self.assertEqual(found[1].label, addresses.FALLBACK_LABEL)

    def test_ipv6_is_bracketed(self):
        addr = addresses.Address("fd7a:115c::1", "Tailscale", "tailscale")
        self.assertEqual(addr.bracketed, "[fd7a:115c::1]")
        self.assertEqual(addr.url(3080), "http://[fd7a:115c::1]:3080/")
        self.assertTrue(addr.display(3080).endswith("（Tailscale）"))


class MenuTests(unittest.TestCase):
    def test_menu_rows_pair_display_text_with_an_address(self):
        rows = addresses.menu("100.1.2.3", ["10.0.0.9"], [("10.0.0.9", "以太网")], port=3099)
        self.assertEqual(len(rows), 3)
        self.assertIn("http://10.0.0.9:3099/", rows[2][0])
        self.assertEqual(rows[2][1].kind, "lan")

    def test_unknown_rows_explain_the_reason_instead_of_going_silent(self):
        rows = addresses.menu(None, None, None,
                              ts_error="tailscale.exe 不在",
                              lan_error="网卡查询超时")
        self.assertEqual(len(rows), 3)
        self.assertIsNone(rows[1][1])
        self.assertEqual(rows[1][0], "Tailscale：未知（tailscale.exe 不在）")
        self.assertEqual(rows[2][0], "局域网：未知（网卡查询超时）")

    def test_unknown_without_a_reason_still_says_something(self):
        self.assertEqual(addresses.unknown(None), "未知（原因不明）")


class PortTests(unittest.TestCase):
    def test_accepts_the_valid_range(self):
        self.assertEqual(addresses.validate_port("1"), 1)
        self.assertEqual(addresses.validate_port(3080), 3080)
        self.assertEqual(addresses.validate_port(" 65535 "), 65535)

    def test_rejects_empty_non_numeric_and_out_of_range(self):
        for bad, message in [("", "端口不能为空"), ("abc", "端口要填数字：abc"),
                             ("0", "端口要在 1-65535 之间：0"),
                             ("70000", "端口要在 1-65535 之间：70000")]:
            with self.assertRaises(ValueError) as caught:
                addresses.validate_port(bad)
            self.assertEqual(str(caught.exception), message)


class LoopbackTests(unittest.TestCase):
    def test_loopback_family_is_recognised(self):
        for host in ("127.0.0.1", "127.5.6.7", "localhost", "LOCALHOST", "::1", "[::1]",
                     "0.0.0.0", "", None):
            self.assertTrue(addresses.is_loopback(host), host)

    def test_private_and_tailscale_hosts_are_not_loopback(self):
        for host in ("100.124.206.105", "10.23.115.16", "192.168.1.5",
                     "fd7a:115c:a1e0::5501:cee3", "valkiriya.tail679d87.ts.net"):
            self.assertFalse(addresses.is_loopback(host), host)


class UrlTests(unittest.TestCase):
    def test_default_port_is_omitted_and_ipv6_is_bracketed(self):
        self.assertEqual(addresses.url_for("10.0.0.9", port=80), "http://10.0.0.9/")
        self.assertEqual(addresses.url_for("10.0.0.9", port=3080), "http://10.0.0.9:3080/")
        self.assertEqual(addresses.url_for("fd7a:115c::1", port=3080),
                         "http://[fd7a:115c::1]:3080/")
        self.assertEqual(addresses.url_for("a.ts.net", scheme="https"), "https://a.ts.net/")

    def test_token_is_appended_with_the_right_separator(self):
        self.assertEqual(addresses.url_for("10.0.0.9", port=80, token="abc"),
                         "http://10.0.0.9/?token=abc")
        self.assertEqual(addresses.url_for("10.0.0.9", port=3080, path="/?x=1", token="abc"),
                         "http://10.0.0.9:3080/?x=1&token=abc")
        self.assertEqual(addresses.url_for("10.0.0.9", port=80), "http://10.0.0.9/")


class MobileCandidateTests(unittest.TestCase):
    def _pool(self):
        return [addresses.Address("127.0.0.1", "本机", "local"),
                addresses.Address("100.124.206.105", "Tailscale", "tailscale"),
                addresses.Address("10.23.115.16", "以太网", "lan")]

    def test_loopback_never_reaches_the_phone_list(self):
        hosts = [c.host for c in addresses.mobile_candidates(self._pool())]
        self.assertNotIn("127.0.0.1", hosts)
        self.assertEqual(hosts, ["100.124.206.105", "10.23.115.16"])

    def test_loopback_can_be_kept_explicitly_but_sinks_to_the_bottom(self):
        rows = addresses.mobile_candidates(self._pool(), include_loopback=True)
        self.assertEqual([c.tier for c in rows],
                         [addresses.TIER_TAILSCALE, addresses.TIER_LAN, addresses.TIER_LOOPBACK])
        self.assertFalse(rows[-1].phone_reachable)

    def test_serve_domain_outranks_everything(self):
        rows = addresses.mobile_candidates(self._pool(), serve_host="valkiriya.tail679d87.ts.net")
        self.assertEqual(rows[0].tier, addresses.TIER_SERVE)
        self.assertEqual(rows[0].url, "http://valkiriya.tail679d87.ts.net/")

    def test_serve_https_drops_the_default_port(self):
        rows = addresses.mobile_candidates([], serve_host="a.ts.net", serve_scheme="https")
        self.assertEqual(rows[0].url, "https://a.ts.net/")
        self.assertEqual(rows[0].port, 443)
        rows = addresses.mobile_candidates([], serve_host="a.ts.net", serve_port=8443)
        self.assertEqual(rows[0].url, "http://a.ts.net:8443/")

    def test_token_travels_into_every_candidate(self):
        rows = addresses.mobile_candidates(self._pool(), token="tok", serve_host="a.ts.net")
        self.assertTrue(all("token=tok" in c.url for c in rows))

    def test_plain_strings_are_accepted_and_classified_as_lan(self):
        rows = addresses.mobile_candidates(["192.168.1.5", "127.0.0.1"])
        self.assertEqual([c.host for c in rows], ["192.168.1.5"])
        self.assertEqual(rows[0].tier, addresses.TIER_LAN)

    def test_duplicate_urls_collapse(self):
        rows = addresses.mobile_candidates(
            ["10.0.0.9", addresses.Address("10.0.0.9", "以太网", "lan")], port=3080)
        self.assertEqual(len(rows), 1)

    def test_without_tailscale_only_the_lan_survives(self):
        rows = addresses.mobile_candidates([addresses.Address("10.23.115.16", "以太网", "lan")])
        self.assertEqual([c.tier for c in rows], [addresses.TIER_LAN])

    def test_a_loopback_only_pool_yields_no_candidates_and_no_primary(self):
        rows = addresses.mobile_candidates([addresses.Address("127.0.0.1", "本机", "local")])
        self.assertEqual(rows, [])
        self.assertIsNone(addresses.primary_mobile(["localhost"]))

    def test_primary_is_the_first_row(self):
        first = addresses.primary_mobile(self._pool(), serve_host="a.ts.net")
        self.assertEqual(first.tier, addresses.TIER_SERVE)

    def test_unusable_candidate_explains_itself(self):
        cand = addresses.Candidate("10.0.0.9", addresses.TIER_LAN, "局域网",
                                   "http://10.0.0.9/", usable=False, reason="端口转发未建立")
        self.assertFalse(cand.phone_reachable)
        self.assertEqual(cand.display(), "局域网：暂不可用（端口转发未建立）")
        self.assertTrue(addresses.Candidate("10.0.0.9", addresses.TIER_LAN, "局域网",
                                            "http://10.0.0.9/").display().endswith("（局域网）"))


class HostPortTests(unittest.TestCase):
    def test_ipv4_is_plain(self):
        self.assertEqual(addresses.host_port("100.124.206.105", 3080), "100.124.206.105:3080")

    def test_ipv6_gets_brackets_so_the_host_header_matches(self):
        self.assertEqual(addresses.host_port("fd7a:115c:a1e0::5501:cee3", 3080),
                         "[fd7a:115c:a1e0::5501:cee3]:3080")
        self.assertEqual(addresses.host_port("[::1]", 80), "[::1]:80")


if __name__ == "__main__":
    unittest.main()
