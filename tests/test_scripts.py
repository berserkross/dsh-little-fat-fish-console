"""随包发布的 PowerShell 脚本的编码与关键参数守卫。

这类文件由 GUI 用 Windows PowerShell 5.1 执行：无 BOM 的 UTF-8 会被按 ANSI 解码，
中文注释把引号吃掉后脚本直接语法错误。改文件时把 BOM 弄丢是很安静的事故，
所以这里钉一条断言。
"""

import pathlib
import unittest

SCRIPT = pathlib.Path(__file__).resolve().parent.parent / "dshconsole" / "data" / "switch-dsh-web.ps1"


class SwitchScriptTests(unittest.TestCase):
    def setUp(self):
        self.raw = SCRIPT.read_bytes()

    def test_ships_with_utf8_bom(self):
        self.assertTrue(self.raw.startswith(b"\xef\xbb\xbf"),
                        "switch-dsh-web.ps1 丢了 UTF-8 BOM，Windows PowerShell 5.1 会按 ANSI 解码中文")

    def test_text_is_utf8_and_mentions_the_serve_path(self):
        text = self.raw.decode("utf-8-sig")
        self.assertIn("-ServeHost", text)
        self.assertIn("-Profile Any", text)
        self.assertIn("Set-NetFirewallRule", text)

    def test_no_private_only_firewall_profile_left(self):
        text = self.raw.decode("utf-8-sig")
        self.assertNotIn("-Profile Private,Domain", text)

    def test_uac_cancel_exits_nonzero(self):
        # 用户取消 UAC 时外层脚本必须以非零码退出，GUI 才能如实报"清理失败"（P1 修复的另一半）
        text = self.raw.decode("utf-8-sig").replace("\r\n", "\n")
        self.assertIn("已取消 UAC 授权，未做任何更改。'\n        exit 1", text)


class LaunchScriptTests(unittest.TestCase):
    """随包 launch-dsh.ps1：BOM、本机 bin.js 判定、启动串行化闸、独立双击回退。"""

    def setUp(self):
        path = pathlib.Path(__file__).resolve().parent.parent / "dshconsole" / "data" / "launch-dsh.ps1"
        self.raw = path.read_bytes()

    def test_launch_ships_with_utf8_bom(self):
        self.assertTrue(self.raw.startswith(b"\xef\xbb\xbf"),
                        "launch-dsh.ps1 丢了 UTF-8 BOM，Windows PowerShell 5.1 会按 ANSI 解码中文")

    def test_launch_uses_exact_bin_js_rule_and_start_gate(self):
        text = self.raw.decode("utf-8-sig").replace("\r\n", "\n")
        self.assertIn("[regex]::Escape($bin)", text)          # 与 GUI probe.classify 同规则：只认本机这份 bin.js
        self.assertIn("Local\\DshConsole.DshStart", text)     # 启动串行化命名互斥体
        self.assertIn("[switch]$NoOpen", text)

    def test_launch_fallback_knows_this_machines_layout(self):
        text = self.raw.decode("utf-8-sig").replace("\r\n", "\n")
        self.assertIn("Documents\\Codex\\apps\\deepseek-harness", text)

    def test_switch_start_dsh_goes_through_the_gate(self):
        raw = (pathlib.Path(__file__).resolve().parent.parent / "dshconsole" / "data"
               / "switch-dsh-web.ps1").read_bytes()
        body = raw.decode("utf-8-sig").replace("\r\n", "\n")
        self.assertIn("Local\\DshConsole.DshStart", body)


if __name__ == "__main__":
    unittest.main()