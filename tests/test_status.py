"""状态模型：假探测结果驱动 probe_status，覆盖四阶段与「未知」原因。"""
from __future__ import annotations

import unittest
from types import SimpleNamespace

from dshconsole import probe, status
from dshconsole.status import Phase

BIN_JS = "C:/Users/Ibash/Documents/Codex/apps/deepseek-harness/node_modules/@deepseek-ai/dsh/lib/bin.js"
OTHER_BIN_JS = ("C:/Users/Ibash/AppData/Local/npm-cache/_npx/1e7f6d9597241db0"
                "/node_modules/../@deepseek-ai/dsh/lib/bin.js")
TS_EXE = "C:/Program Files/Tailscale/tailscale.exe"
LOCAL_TARGETS = [("127.0.0.1", 3080)]
FOREIGN_TARGETS = [("10.0.0.9", 3080)]


def cfg():
    return SimpleNamespace(port=3080, bin_js=BIN_JS, tailscale=TS_EXE)


def fixed(value):
    return lambda *args, **kwargs: value


def run_probe(processes=([], None), listening=False, targets=([], None),
              firewall=(True, None), tailscale=("100.124.206.105", None),
              lan=(["10.23.115.16"], None), others=([], None)) -> status.Status:
    return status.probe_status(
        cfg(),
        processes=fixed(processes),
        port_open=fixed(listening),
        portproxy=fixed(targets),
        firewall=fixed(firewall),
        tailscale=fixed(tailscale),
        lan=fixed(lan),
        others=fixed(others),
    )


class ResidueTests(unittest.TestCase):
    """端口转发残留：转发规则在、本机 DSH 进程不在 → residue=True（假活可见）。"""

    def test_rules_without_pids_is_residue(self):
        state = run_probe(processes=([], None), listening=False,
                          targets=(LOCAL_TARGETS, None))
        self.assertIs(state.residue, True)

    def test_rules_with_dsh_running_is_not_residue(self):
        state = run_probe(processes=([123], None), listening=True,
                          targets=(LOCAL_TARGETS, None))
        self.assertIs(state.residue, False)

    def test_no_rules_is_not_residue(self):
        state = run_probe(processes=([], None), targets=([], None))
        self.assertIs(state.residue, False)

    def test_unknown_probe_is_unknown_residue(self):
        state = run_probe(processes=(None, "err"), targets=(None, "err"))
        self.assertIsNone(state.residue)


class PhaseTests(unittest.TestCase):
    def test_running_needs_port_and_own_pid(self):
        state = run_probe(processes=([111], None), listening=True, targets=(LOCAL_TARGETS, None))
        self.assertIs(state.phase, Phase.RUNNING)
        self.assertEqual(state.pids, [111])
        self.assertIs(state.port_open, True)
        self.assertIs(state.phone_open, True)
        self.assertEqual(state.notes, [])

    def test_degraded_when_port_open_but_no_own_pid(self):
        state = run_probe(processes=([], None), listening=True,
                          others=([(9856, OTHER_BIN_JS)], None))
        self.assertIs(state.phase, Phase.DEGRADED)
        self.assertIs(state.port_open, True)
        self.assertEqual(state.pids, [])
        self.assertTrue(state.notes)
        self.assertIn("3080", state.notes[0])
        self.assertIn("别的程序", state.notes[0])
        self.assertIn("9856", state.notes[1])

    def test_stopped_when_no_port_and_no_pid(self):
        state = run_probe(processes=([], None), listening=False)
        self.assertIs(state.phase, Phase.STOPPED)
        self.assertEqual(state.notes, [])
        self.assertIs(state.phone_open, False)

    def test_starting_when_pid_without_port(self):
        state = run_probe(processes=([42], None), listening=False)
        self.assertIs(state.phase, Phase.STARTING)
        self.assertIn("42", state.notes[0])

    def test_unknown_when_process_probe_fails(self):
        state = run_probe(processes=(None, "超时：30 秒内没有返回"), listening=False)
        self.assertIs(state.phase, Phase.UNKNOWN)
        self.assertIsNone(state.pids)
        self.assertTrue(state.notes)
        self.assertTrue(state.notes[0].startswith("未知：进程列表查不到"), state.notes[0])
        self.assertIn("超时", state.notes[0])

    def test_unknown_when_port_probe_has_no_answer(self):
        state = run_probe(processes=([], None), listening=None)
        self.assertIs(state.phase, Phase.UNKNOWN)
        self.assertTrue(any("端口 3080" in note for note in state.notes), state.notes)

    def test_unknown_is_labelled_unknown_not_stopped(self):
        self.assertEqual(Phase.UNKNOWN.label, "未知")
        self.assertEqual(Phase.STOPPED.label, "未运行")
        self.assertNotEqual(Phase.UNKNOWN.label, Phase.STOPPED.label)


class PhoneTests(unittest.TestCase):
    def test_unknown_when_portproxy_fails(self):
        state = run_probe(targets=(None, "端口转发查询失败：超时"), listening=False)
        self.assertIsNone(state.phone_open)
        self.assertTrue(any("端口转发查不到" in note for note in state.notes), state.notes)

    def test_unknown_when_firewall_fails(self):
        state = run_probe(targets=(LOCAL_TARGETS, None),
                          firewall=(None, "防火墙规则查询失败：超时"))
        self.assertIsNone(state.phone_open)
        self.assertTrue(any("防火墙规则查不到" in note for note in state.notes), state.notes)

    def test_off_when_target_points_elsewhere(self):
        state = run_probe(targets=(FOREIGN_TARGETS, None))
        self.assertIs(state.phone_open, False)
        self.assertTrue(any("不是本机" in note for note in state.notes), state.notes)

    def test_off_and_explained_when_firewall_rule_missing(self):
        state = run_probe(targets=(LOCAL_TARGETS, None), firewall=(False, None))
        self.assertIs(state.phone_open, False)
        rule = probe.FIREWALL_RULE.format(port=3080)
        self.assertTrue(any(rule in note for note in state.notes), state.notes)

    def test_probe_phone_returns_notes_and_targets(self):
        phone, targets, notes = status.probe_phone(
            cfg(), portproxy=fixed((LOCAL_TARGETS, None)), firewall=fixed((True, None)))
        self.assertIs(phone, True)
        self.assertEqual(targets, LOCAL_TARGETS)
        self.assertEqual(notes, [])


class LanAndTailscaleTests(unittest.TestCase):
    def test_unknown_lan_is_explained(self):
        state = run_probe(lan=(None, "局域网地址查询失败：超时"))
        self.assertIsNone(state.lan_ips)
        self.assertTrue(any("未知：局域网地址" in note for note in state.notes), state.notes)

    def test_unknown_tailscale_is_explained(self):
        state = run_probe(tailscale=(None, "tailscale 没有返回可用的 IPv4 地址"))
        self.assertIsNone(state.ts_ip)
        self.assertTrue(any("未知：Tailscale 地址" in note for note in state.notes), state.notes)


if __name__ == "__main__":
    unittest.main()
