"""随包 ps1 与 Python 侧传的参数必须对得上：对不上时 PowerShell 只报绑定失败、什么都不做。

之前就踩过一次：_start() 传了 -ServeHost，而 launch-dsh.ps1 没声明它 —— 表现是「重启只关闭、不启动」，
因为脚本在参数绑定阶段就退出了，stdout 还是空的。这里不抄死参数名，直接从 _ps_args() 的真输出对账：
GUI 传什么，脚本就必须声明什么。
"""
import re
import tempfile
import time
import unittest
from pathlib import Path

import dsh_gui
from dshconsole import resources


def declared_params(path: Path) -> set[str]:
    """从 param( ... ) 块里抠出参数名（够用就行，不引入 PowerShell 解析器）。"""
    text = path.read_text(encoding="utf-8-sig")
    block = re.search(r"param\s*\((.*?)\n\)", text, re.S)
    if not block:
        return set()
    return set(re.findall(r"\$([A-Za-z_][A-Za-z0-9_]*)", block.group(1)))


class ScriptParamTests(unittest.TestCase):
    def test_launch_script_declares_every_flag_the_gui_passes(self):
        params = declared_params(resources.launch_ps1())
        flags = {arg.lstrip("-") for arg in dsh_gui._ps_args(include_chrome=True)
                 if arg.startswith("-")}
        self.assertTrue(flags, "GUI 一个参数都没传？")
        for name in sorted(flags):
            self.assertIn(name, params, f"launch-dsh.ps1 少了 -{name}")

    def test_switch_script_declares_every_flag_the_gui_passes(self):
        params = declared_params(resources.switch_ps1())
        for name in ("Harness", "NodeExe", "BinJs", "DshHome", "Port", "ServeHost"):
            self.assertIn(name, params, f"switch-dsh-web.ps1 少了 -{name}")

    def test_direct_start_carries_port_trusted_hosts_and_token_logs(self):
        cmd = dsh_gui.build_direct_start_command(
            "C:/node/node.exe", "C:/h/bin.js", "C:/h",
            ["--trusted-host", "127.0.0.1:3080", "--trusted-host", "valkiriya.tail679d87.ts.net"],
            "C:/logs/dsh-web.stdout.log", "C:/logs/dsh-web.stderr.log", "C:/h/.dsh")
        for piece in ("Start-Process", "'web'", "'--no-open'", "'--port', '3080'",
                      "--trusted-host", "valkiriya.tail679d87.ts.net",
                      "dsh-web.stdout.log", "dsh-web.stderr.log", "-WindowStyle Hidden",
                      "$env:DSH_HOME='C:/h/.dsh'"):
            self.assertIn(piece, cmd)
        # 清日志留在 Python 侧做：塞进 Set-Content 会静默失败，旧 token 留在文件里就必然 401。
        self.assertNotIn("Set-Content", cmd)

    def test_truncate_logs_reports_what_it_could_not_clear(self):
        with tempfile.TemporaryDirectory() as tmp:
            good = Path(tmp, "a.log")
            good.write_text("dsh web: http://127.0.0.1:3080/?token=OLD", encoding="utf-8")
            bad = Path(tmp, "missing", "b.log")      # 父目录不存在 → 必然清不掉
            failed = dsh_gui.truncate_logs(str(good), str(bad), "")
            self.assertEqual(good.read_text(encoding="utf-8"), "")
            self.assertEqual(failed, [str(bad)])

    def test_token_is_fresh_compares_log_mtime_with_start_epoch(self):
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp, "dsh-web.stdout.log")
            log.write_text("x", encoding="utf-8")
            app = object.__new__(dsh_gui.ConsoleApp)
            saved = dsh_gui.TOKEN_LOG
            dsh_gui.TOKEN_LOG = log
            try:
                app._start_epoch = time.time() - 60      # 日志比这次启动新
                self.assertTrue(app._token_is_fresh())
                app._start_epoch = time.time() + 60      # 日志比这次启动旧
                self.assertFalse(app._token_is_fresh())
            finally:
                dsh_gui.TOKEN_LOG = saved

    def test_bundled_scripts_exist(self):
        for path in (resources.launch_ps1(), resources.switch_ps1()):
            self.assertTrue(path.is_file(), path)


if __name__ == "__main__":
    unittest.main()
