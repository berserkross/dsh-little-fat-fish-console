"""探测层解析与注入测试：喂假 stdout / 假 runner，不依赖本机 PowerShell。"""
from __future__ import annotations

import json
import socket
import unittest

from dshconsole import probe
from dshconsole.psrun import PsResult

BS = "\\"
HARNESS = "C:/Users/Ibash/Documents/Codex/apps/deepseek-harness"
MINE_BIN_JS = HARNESS + "/node_modules/@deepseek-ai/dsh/lib/bin.js"
NPX_ROOT = "C:/Users/Ibash/AppData/Local/npm-cache/_npx/1e7f6d9597241db0"
NPX_BIN_JS_FLAT = NPX_ROOT + "/node_modules/@deepseek-ai/dsh/lib/bin.js"
NPX_BIN_JS_DOTTED = NPX_ROOT + "/node_modules/.bin/../@deepseek-ai/dsh/lib/bin.js"
OTHER_BIN_JS = "C:/work/other-app/node_modules/@deepseek-ai/dsh/lib/bin.js"

# 本机真实输出形态：两行表头 + 分隔线 + 数据行
TABLE = ("Listen on ipv4:             Connect to ipv4:\r\n"
         "\r\n"
         "Address         Port        Address         Port\r\n"
         "--------------- ----------  --------------- ----------\r\n"
         "100.124.206.105 3080        127.0.0.1       3080\r\n")


def win(path: str) -> str:
    return path.replace("/", BS)


def ok(stdout: str = "", stderr: str = "") -> PsResult:
    return PsResult(True, 0, stdout, stderr, None)


def failed(message: str = "超时：15 秒内没有返回") -> PsResult:
    return PsResult(False, None, "", "", message)


def runner_returning(result: PsResult, seen: list | None = None):
    def run(command, timeout=30):
        if seen is not None:
            seen.append(command)
        return result
    return run


def process_json(entries) -> str:
    return json.dumps([{"ProcessId": pid, "CommandLine": cmd} for pid, cmd in entries])


class PortproxyTableTests(unittest.TestCase):
    def test_real_table(self):
        self.assertEqual(probe.parse_portproxy_table(TABLE),
                         [("100.124.206.105", 3080, "127.0.0.1", 3080)])

    def test_empty_output(self):
        self.assertEqual(probe.parse_portproxy_table(""), [])
        self.assertEqual(probe.parse_portproxy_table(None), [])

    def test_header_only(self):
        header = TABLE.split("---------------")[0]
        self.assertEqual(probe.parse_portproxy_table(header), [])

    def test_multiple_rows(self):
        text = TABLE + "0.0.0.0 4000 127.0.0.1 4001\r\n"
        rows = probe.parse_portproxy_table(text)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[1], ("0.0.0.0", 4000, "127.0.0.1", 4001))

    def test_ipv6_row_is_ignored(self):
        text = TABLE + "::1 3080 ::1 3080\r\n"
        self.assertEqual(len(probe.parse_portproxy_table(text)), 1)

    def test_short_and_non_numeric_rows_are_ignored(self):
        text = TABLE + "127.0.0.1 3080\r\n" + "127.0.0.1 abc 127.0.0.1 3080\r\n"
        self.assertEqual(len(probe.parse_portproxy_table(text)), 1)


class PortproxyTargetTests(unittest.TestCase):
    def test_targets_for_port(self):
        self.assertEqual(probe.portproxy_targets(3080, runner=runner_returning(ok(TABLE))),
                         ([("127.0.0.1", 3080)], None))

    def test_port_without_rule_is_empty_list_not_none(self):
        targets, err = probe.portproxy_targets(4000, runner=runner_returning(ok(TABLE)))
        self.assertEqual(targets, [])
        self.assertIsNone(err)

    def test_query_failure_is_unknown(self):
        targets, err = probe.portproxy_targets(3080, runner=runner_returning(failed()))
        self.assertIsNone(targets)
        self.assertIn("端口转发查询失败", err or "")
        self.assertIn("超时", err or "")

    def test_command_asks_netsh_for_v4tov4(self):
        seen: list = []
        probe.portproxy_targets(3080, runner=runner_returning(ok(TABLE), seen))
        self.assertEqual(seen, ["netsh interface portproxy show v4tov4"])


class FirewallTests(unittest.TestCase):
    def test_parse_results(self):
        self.assertIs(probe.parse_firewall_result("FOUND"), True)
        self.assertIs(probe.parse_firewall_result("  MISSING \r\n"), False)
        self.assertIsNone(probe.parse_firewall_result("ERROR access denied"))
        self.assertIsNone(probe.parse_firewall_result(""))

    def test_found(self):
        self.assertEqual(probe.firewall_rule(3080, runner=runner_returning(ok("FOUND"))), (True, None))

    def test_missing(self):
        self.assertEqual(probe.firewall_rule(3080, runner=runner_returning(ok("MISSING"))), (False, None))

    def test_error_text_is_unknown_with_reason(self):
        found, err = probe.firewall_rule(3080, runner=runner_returning(ok("ERROR access denied")))
        self.assertIsNone(found)
        self.assertIn("access denied", err or "")

    def test_query_failure_is_unknown(self):
        found, err = probe.firewall_rule(3080, runner=runner_returning(failed()))
        self.assertIsNone(found)
        self.assertIn("防火墙规则查询失败", err or "")

    def test_command_carries_rule_name(self):
        command = probe.firewall_command(3080)
        self.assertIn(probe.FIREWALL_RULE.format(port=3080), command)


class PathTests(unittest.TestCase):
    def test_normalize_ignores_case_slashes_and_dot_segments(self):
        self.assertEqual(probe.normalize_path(win(NPX_BIN_JS_FLAT).upper()),
                         probe.normalize_path(NPX_BIN_JS_DOTTED))

    def test_display_path_keeps_case(self):
        self.assertEqual(probe.display_path(NPX_BIN_JS_DOTTED), win(NPX_BIN_JS_FLAT))

    def test_is_dsh_bin_js_accepts_npx_shaped_path(self):
        self.assertTrue(probe.is_dsh_bin_js(NPX_BIN_JS_DOTTED))
        self.assertFalse(probe.is_dsh_bin_js("C:/work/other-app/lib/other.js"))

    def test_command_line_paths_reads_quoted_arguments(self):
        command_line = ('"D:/Program Files/nodejs/node.exe" "' + win(MINE_BIN_JS)
                        + '" web --no-open')
        self.assertEqual(probe.command_line_paths(command_line), [win(MINE_BIN_JS)])


class ProcessTests(unittest.TestCase):
    def test_parse_single_object(self):
        text = json.dumps({"ProcessId": 42, "CommandLine": "node x.js"})
        self.assertEqual(probe.parse_process_list(text), [(42, "node x.js")])

    def test_parse_garbage_is_none(self):
        self.assertIsNone(probe.parse_process_list("not json"))
        self.assertIsNone(probe.parse_process_list(""))

    def test_dsh_processes_matches_only_configured_bin_js(self):
        payload = process_json([
            (111, '"D:/Program Files/nodejs/node.exe" "' + win(MINE_BIN_JS) + '" web --no-open'),
            (222, '"D:/Program Files/nodejs/node.exe" "' + win(OTHER_BIN_JS) + '" web'),
        ])
        self.assertEqual(probe.dsh_processes(MINE_BIN_JS, runner=runner_returning(ok(payload))),
                         ([111], None))

    def test_other_projects_bin_js_is_never_killed(self):
        """误杀回归：形态一样但不属于本机 bin.js 的 node 进程不算 DSH。"""
        command_line = '"D:/Program Files/nodejs/node.exe" "' + win(OTHER_BIN_JS) + '" web'
        payload = process_json([(222, command_line)])
        pids, err = probe.dsh_processes(MINE_BIN_JS, runner=runner_returning(ok(payload)))
        self.assertEqual(pids, [])
        self.assertIsNone(err)

    def test_npx_shaped_command_line_matches_after_normalization(self):
        command_line = '"node"   "' + win(NPX_BIN_JS_DOTTED) + '" web'
        payload = process_json([(9856, command_line)])
        self.assertEqual(probe.dsh_processes(NPX_BIN_JS_FLAT, runner=runner_returning(ok(payload))),
                         ([9856], None))

    def test_other_dsh_processes_names_the_port_owner(self):
        payload = process_json([(9856, '"node" "' + win(NPX_BIN_JS_DOTTED) + '" web')])
        others, err = probe.other_dsh_processes(MINE_BIN_JS, runner=runner_returning(ok(payload)))
        self.assertEqual(others, [(9856, win(NPX_BIN_JS_DOTTED))])
        self.assertIsNone(err)

    def test_missing_bin_js_is_unknown(self):
        pids, err = probe.dsh_processes(None, runner=runner_returning(ok("[]")))
        self.assertIsNone(pids)
        self.assertIn("bin.js", err or "")

    def test_query_failure_is_unknown(self):
        pids, err = probe.node_processes(runner=runner_returning(failed("超时：30 秒内没有返回")))
        self.assertIsNone(pids)
        self.assertIn("node 进程查询失败", err or "")


class LanAndTailscaleTests(unittest.TestCase):
    def test_parse_lan_ips_filters_and_dedups(self):
        text = "10.23.115.16\r\n10.30.107.211\r\n127.0.0.1\r\n169.254.1.1\r\n10.23.115.16\r\n"
        self.assertEqual(probe.parse_lan_ips(text), ["10.23.115.16", "10.30.107.211"])

    def test_lan_query_failure_is_unknown(self):
        ips, err = probe.lan_ips(runner=runner_returning(failed()))
        self.assertIsNone(ips)
        self.assertIn("局域网地址查询失败", err or "")

    def test_tailscale_without_exe_explains_itself(self):
        ip, err = probe.tailscale_ip(None)
        self.assertIsNone(ip)
        self.assertIn("tailscale", err or "")

    def test_tailscale_skips_loopback(self):
        self.assertEqual(probe.tailscale_ip("ts.exe", runner=runner_returning(ok("127.0.0.1\n100.124.206.105\n"))),
                         ("100.124.206.105", None))
        ip, err = probe.tailscale_ip("ts.exe", runner=runner_returning(ok("127.0.0.1\n")))
        self.assertIsNone(ip)
        self.assertIn("没有返回可用的 IPv4", err or "")


class PortOpenTests(unittest.TestCase):
    def test_open_and_closed_port(self):
        server = socket.socket()
        server.bind(("127.0.0.1", 0))
        server.listen(1)
        port = server.getsockname()[1]
        try:
            self.assertTrue(probe.port_open(port, timeout=1.0))
        finally:
            server.close()
        self.assertFalse(probe.port_open(port, timeout=0.2))


if __name__ == "__main__":
    unittest.main()
