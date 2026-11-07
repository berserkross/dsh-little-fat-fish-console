"""psrun 分支覆盖：全部注入假 spawn，绝不真跑 powershell。"""
from __future__ import annotations

import os
import subprocess
import unittest
from pathlib import Path

from dshconsole import psrun


class FakeSpawn:
    """替身 subprocess.run：记录参数，返回给定结果或抛出给定异常。"""

    def __init__(self, returncode: int = 0, stdout: str = "", stderr: str = "", raises=None):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr
        self.raises = raises
        self.calls: list[tuple[list[str], dict]] = []

    def __call__(self, argv, **kwargs):
        self.calls.append((list(argv), kwargs))
        if self.raises is not None:
            raise self.raises
        return subprocess.CompletedProcess(argv, self.returncode, self.stdout, self.stderr)


class ExecuteTests(unittest.TestCase):
    def test_success_is_ok_with_code_and_stdout(self):
        fake = FakeSpawn(stdout="hello")
        result = psrun.execute(["ps", "-c", "x"], 5, spawn=fake)
        self.assertTrue(result.ok)
        self.assertEqual(result.code, 0)
        self.assertEqual(result.stdout, "hello")
        self.assertIsNone(result.error)
        self.assertEqual(result.why(), "")
        self.assertEqual(result.text, "hello")

    def test_nonzero_exit_is_failed_with_stderr_detail(self):
        result = psrun.execute(["ps"], 5, spawn=FakeSpawn(1, "", "boom" + chr(10)))
        self.assertFalse(result.ok)
        self.assertEqual(result.code, 1)
        self.assertIsNone(result.error)
        self.assertIn("退出码 1", result.why())
        self.assertIn("boom", result.why())

    def test_text_keeps_both_streams(self):
        result = psrun.execute(["ps"], 5, spawn=FakeSpawn(0, "out", "err"))
        self.assertEqual(result.text, "outerr")

    def test_timeout_is_reported_not_raised(self):
        fake = FakeSpawn(raises=subprocess.TimeoutExpired(cmd=["ps"], timeout=30))
        result = psrun.execute(["ps"], 30, spawn=fake)
        self.assertFalse(result.ok)
        self.assertIsNone(result.code)
        self.assertTrue(result.error.startswith("超时：30 秒内没有返回"), result.error)
        self.assertEqual(result.why(), result.error)

    def test_missing_powershell_is_reported(self):
        result = psrun.execute(["ps"], 5, spawn=FakeSpawn(raises=FileNotFoundError()))
        self.assertFalse(result.ok)
        self.assertIsNone(result.code)
        self.assertIn("找不到", result.error or "")

    def test_oserror_is_reported(self):
        result = psrun.execute(["ps"], 5, spawn=FakeSpawn(raises=OSError("denied")))
        self.assertFalse(result.ok)
        self.assertIn("denied", result.error or "")

    def test_no_window_and_devnull_stdin_are_always_set(self):
        fake = FakeSpawn()
        psrun.execute(["ps"], 5, spawn=fake)
        _argv, kwargs = fake.calls[0]
        self.assertEqual(kwargs["stdin"], subprocess.DEVNULL)
        self.assertEqual(kwargs["errors"], "replace")
        expected = psrun.CREATE_NO_WINDOW if os.name == "nt" else 0
        self.assertEqual(kwargs["creationflags"], expected)


class WrapperTests(unittest.TestCase):
    def test_run_ps_uses_file_and_forwards_args(self):
        fake = FakeSpawn()
        psrun.run_ps(Path("launch.ps1"), "-NoPause", timeout=7, spawn=fake)
        argv, kwargs = fake.calls[0]
        self.assertIn("-File", argv)
        self.assertEqual(argv[argv.index("-File") + 1], "launch.ps1")
        self.assertEqual(argv[-1], "-NoPause")
        self.assertEqual(kwargs["timeout"], 7)

    def test_run_ps_cmd_prefixes_utf8_preamble(self):
        fake = FakeSpawn()
        psrun.run_ps_cmd("Get-Date", timeout=3, spawn=fake)
        argv, kwargs = fake.calls[0]
        self.assertIn("-Command", argv)
        command = argv[argv.index("-Command") + 1]
        self.assertTrue(command.startswith(psrun.UTF8_PREAMBLE))
        self.assertTrue(command.endswith("Get-Date"))
        self.assertEqual(kwargs["timeout"], 3)


class RealExecutionTests(unittest.TestCase):
    """真实 PowerShell 的冒烟（全库唯一真跑 ps 的用例）：
    Start-Process 拉起的孙进程继承捕获管道 → EOF 不来 → communicate 挂死。
    阶段 3 验收现场（faulthandler 栈转储）抓在这个点；修复后输出走临时文件。"""

    @unittest.skipUnless(os.name == "nt", "只在 Windows 上验证真实 PowerShell 行为")
    def test_command_spawning_long_lived_grandchild_returns_promptly(self):
        import tempfile
        import time
        out_log = Path(tempfile.mkdtemp(prefix="dsh-psrun-test-")) / "out.log"
        err_log = out_log.with_name("err.log")
        start = time.monotonic()
        # 镜像 _start_direct 的命令形状：Start-Process 拉起一个会活几秒的进程并重定向日志。
        result = psrun.run_ps_cmd(
            "Start-Process -FilePath 'ping.exe' -ArgumentList '-n','5','127.0.0.1' "
            f"-WindowStyle Hidden -RedirectStandardOutput '{out_log}' "
            f"-RedirectStandardError '{err_log}'",
            timeout=2)
        elapsed = time.monotonic() - start
        self.assertLess(elapsed, 3.0, f"命令应在服务进程退出后立即返回，实际 {elapsed:.1f}s")
        self.assertTrue(result.ok, result.error or result.text)


if __name__ == "__main__":
    unittest.main()
