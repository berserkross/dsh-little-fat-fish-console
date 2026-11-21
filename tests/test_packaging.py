"""打包形态的护栏：onedir 不许悄悄退回 onefile。

为什么要有这层：onefile 每次启动都要把整包解到 %TEMP%\\_MEIxxxx，本机（腾讯电脑管家在岗）
2026-11-22 起那一步稳定失败，PyInstaller 引导层弹「Could not create temporary directory!」，
双击毫无反应且不写任何日志 —— 这种失效只有真双击才会暴露，单元测试碰不到，所以盯 spec 文本。
"""

import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent


class SpecShapeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.spec = (ROOT / "DSHConsole.spec").read_text(encoding="utf-8")

    def test_exe_excludes_binaries(self):
        self.assertIn("exclude_binaries=True", self.spec,
                      "EXE 少了 exclude_binaries=True 就成了 onefile，会把 _MEI 解包失败带回来")

    def test_collect_step_exists(self):
        self.assertIn("COLLECT(", self.spec, "onedir 必须有 COLLECT 步骤")

    def test_no_runtime_tmpdir(self):
        self.assertNotIn("runtime_tmpdir=", self.spec.replace("runtime_tmpdir=None", ""),
                         "指定 runtime_tmpdir 等于换了个落点继续写临时目录，问题没解决")

    def test_version_resource_still_wired(self):
        self.assertIn("version='version_info.txt'", self.spec)


class ArtifactPathTests(unittest.TestCase):
    def test_ci_checks_the_onedir_exe(self):
        ci = (ROOT / ".github" / "workflows" / "check.yml").read_text(encoding="utf-8")
        self.assertIn("dist\\DSHConsole\\DSHConsole.exe", ci)

    def test_build_doc_points_at_onedir(self):
        doc = (ROOT / "docs" / "build-and-signing.md").read_text(encoding="utf-8")
        self.assertIn("onedir", doc)


if __name__ == "__main__":
    unittest.main()