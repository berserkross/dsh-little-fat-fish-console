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


if __name__ == "__main__":
    unittest.main()
