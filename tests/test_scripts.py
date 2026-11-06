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


if __name__ == "__main__":
    unittest.main()