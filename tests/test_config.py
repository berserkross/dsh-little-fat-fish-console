"""dshconsole.config 的单元测试：只用标准库，不依赖本机真实安装路径。"""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from dshconsole import config


def make_harness(root: Path, name: str = "fake-harness") -> Path:
    """造一个「长得像 harness」的目录：bin.js 存在即成立。

    返回规范（长名）路径：被测代码的出口一律经过 canonical_path()，用 8.3 短名
    拼出来的期望值在 CI 的 runner 上会永远不相等。
    """
    harness = Path(root).resolve() / name
    bin_js = harness / config.BIN_JS_REL
    bin_js.parent.mkdir(parents=True, exist_ok=True)
    bin_js.write_text("// stub\n", encoding="utf-8")
    return harness


def make_file(root: Path, name: str) -> Path:
    path = Path(root).resolve() / name
    path.write_text("stub", encoding="utf-8")
    return path


class HermeticBase(unittest.TestCase):
    """把真实机器上的探测来源全部摘掉，只留 tempfile 里造的结构。"""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name).resolve()
        self.empty = self.tmp / "empty"
        self.empty.mkdir()
        patchers = [
            mock.patch.object(config, "harness_from_dsh", return_value=None),
            mock.patch.object(config, "harness_from_dsh_home", return_value=None),
            mock.patch.object(config, "common_harness_candidates", return_value=[]),
        ]
        for patcher in patchers:
            patcher.start()
            self.addCleanup(patcher.stop)

    def tearDown(self) -> None:
        self._tmp.cleanup()


class HermeticDetection(HermeticBase):
    """A1 探测顺序、config.json 往返、失效重探、失败返回 None。"""

    # ---- A1：探测顺序 ----
    def test_looks_like_harness_requires_bin_js(self) -> None:
        harness = make_harness(self.tmp)
        self.assertTrue(config.looks_like_harness(harness))
        self.assertFalse(config.looks_like_harness(self.empty))
        self.assertFalse(config.looks_like_harness(self.tmp / "nope"))

    def test_explicit_harness_beats_detection(self) -> None:
        explicit = make_harness(self.tmp, "explicit")
        stored = make_harness(self.tmp, "stored")
        self.assertEqual(config.detect_harness(explicit, stored, self.empty), explicit)
        # 显式目录不存在时退回记录值，而记录值也是 --harness/上次结果
        self.assertEqual(config.detect_harness(self.tmp / "gone", stored, self.empty), stored)

    def test_harness_from_cwd_walks_up(self) -> None:
        harness = make_harness(self.tmp)
        deep = harness / "a" / "b"
        deep.mkdir(parents=True)
        # 比的是规范路径：CI 的 runner 里 Path.cwd() 给的是 8.3 短名（RUNNER~1），
        # 而 mkdtemp 给的是长名，两个拼法必须是同一个值。
        self.assertEqual(config.harness_from_cwd(deep), harness.resolve())

    def test_detect_harness_returns_none(self) -> None:
        self.assertIsNone(config.detect_harness(None, None, self.empty))
        self.assertIsNone(config.detect_harness(self.tmp / "gone", "not-a-dir", self.empty))

    def test_resolve_without_anything_is_not_ready(self) -> None:
        cfg = config.resolve(path=self.tmp / "absent.json", cwd=self.empty)
        self.assertIsNone(cfg.harness)
        self.assertIsNone(cfg.bin_js)
        self.assertIsNone(cfg.token_log)
        self.assertFalse(cfg.ready)
        self.assertEqual(cfg.port, config.DEFAULT_PORT)

    def test_resolve_reports_bin_js_and_token_log(self) -> None:
        harness = make_harness(self.tmp)
        node = make_file(self.tmp, "node.exe")
        cfg_path = self.tmp / "cfg.json"
        cfg_path.write_text(json.dumps({"node": str(node)}), encoding="utf-8")
        cfg = config.resolve(explicit_harness=harness, explicit_port=3099,
                             path=cfg_path, cwd=self.empty)
        self.assertEqual(cfg.harness, harness)
        self.assertEqual(cfg.bin_js, harness / config.BIN_JS_REL)
        self.assertEqual(cfg.node, node)
        self.assertEqual(cfg.port, 3099)
        self.assertEqual(cfg.token_log, harness / config.TOKEN_LOG_NAME)
        self.assertTrue(cfg.ready)

    # ---- A1：config.json 往返 ----
    def test_save_load_roundtrip(self) -> None:
        harness = make_harness(self.tmp)
        node = make_file(self.tmp, "node.exe")
        dsh_home = self.tmp / "dsh_home"
        dsh_home.mkdir()
        cfg = config.DshConfig(harness=harness, node=node, bin_js=harness / config.BIN_JS_REL,
                               dsh_home=dsh_home, port=3099)
        target = config.save(cfg, self.tmp / "config.json")
        self.assertTrue(target.is_file())
        raw = json.loads(target.read_text(encoding="utf-8"))
        self.assertEqual(raw["harness"], str(harness))
        self.assertEqual(raw["port"], 3099)
        self.assertNotIn("chrome", raw)  # None 不落盘

        loaded = config.load(target)
        self.assertEqual(loaded["harness"], str(harness))
        self.assertEqual(loaded["node"], str(node))
        self.assertEqual(loaded["bin_js"], str(harness / config.BIN_JS_REL))
        self.assertEqual(loaded["dsh_home"], str(dsh_home))
        self.assertEqual(loaded["port"], 3099)

    def test_load_ignores_broken_file(self) -> None:
        broken = self.tmp / "config.json"
        broken.write_text("{not json", encoding="utf-8")
        self.assertEqual(config.load(broken), {})
        self.assertEqual(config.load(self.tmp / "missing.json"), {})

    def test_config_path_honours_env_override(self) -> None:
        target = self.tmp / "custom" / "config.json"
        with mock.patch.dict(os.environ, {config.CONFIG_ENV: str(target)}):
            self.assertEqual(config.config_path(), target)
        with mock.patch.dict(os.environ, {config.CONFIG_ENV: ""}):
            path = config.config_path()
        self.assertEqual(path.name, "config.json")
        self.assertEqual(path.parent.name, config.APP_NAME)

    def test_stale_path_is_reprobed(self) -> None:
        harness = make_harness(self.tmp)
        node = make_file(self.tmp, "node.exe")
        target = config.save(config.DshConfig(harness=harness, node=node, port=3099),
                             self.tmp / "config.json")
        self.assertIn("harness", config.load(target))

        for root, dirs, files in os.walk(harness, topdown=False):
            for name in files:
                Path(root, name).unlink()
            for name in dirs:
                Path(root, name).rmdir()
        harness.rmdir()

        self.assertNotIn("harness", config.load(target))  # 失效键被丢弃
        cfg = config.resolve(path=target, cwd=self.empty)
        self.assertIsNone(cfg.harness)   # 于是重新探测（这里探不到）
        self.assertFalse(cfg.ready)
        self.assertEqual(cfg.port, 3099)  # 仍然有效的键保留

    def test_resolve_port_validation(self) -> None:
        self.assertEqual(config.resolve_port(4000, 3080), 4000)
        self.assertEqual(config.resolve_port(None, 3099), 3099)
        self.assertEqual(config.resolve_port("abc", None), config.DEFAULT_PORT)
        self.assertEqual(config.resolve_port(70000, None), config.DEFAULT_PORT)
        self.assertEqual(config.resolve_port(None, None), config.DEFAULT_PORT)


class CliParsing(HermeticBase):
    """--harness / --port 必须真的进到 resolve，而不只是写在文档里。"""

    def test_cli_harness_equals_form_reaches_resolve(self) -> None:
        harness = make_harness(self.tmp, "cli-harness")
        parsed_harness, parsed_port = config.parse_cli([f"--harness={harness}"])
        self.assertEqual(parsed_harness, harness)
        self.assertIsNone(parsed_port)
        cfg = config.resolve(explicit_harness=parsed_harness, explicit_port=parsed_port,
                             path=self.tmp / "absent.json", cwd=self.empty)
        self.assertEqual(cfg.harness, harness)
        self.assertIsNotNone(cfg.bin_js)

    def test_cli_port_space_form_reaches_resolve(self) -> None:
        parsed_harness, parsed_port = config.parse_cli(["--port", "3999"])
        self.assertIsNone(parsed_harness)
        self.assertEqual(parsed_port, 3999)
        cfg = config.resolve(explicit_harness=parsed_harness, explicit_port=parsed_port,
                             path=self.tmp / "absent.json", cwd=self.empty)
        self.assertEqual(cfg.port, 3999)

    def test_cli_rejects_bad_input(self) -> None:
        cases = [("--port",), ("--port", "abc"), ("--port", "70000"),
                 ("--harness=",), ("--harnes", "x")]
        for argv in cases:
            with self.subTest(argv=argv), self.assertRaises(config.CliError):
                config.parse_cli(list(argv))


def _short_name(path: str) -> str | None:
    """问 Windows 要 8.3 短名；拿不到就返回 None（不支持的机器上跳过）。"""
    if os.name != "nt":
        return None
    import ctypes
    size = ctypes.windll.kernel32.GetShortPathNameW(str(path), None, 0)
    if not size:
        return None
    buffer = ctypes.create_unicode_buffer(size)
    if not ctypes.windll.kernel32.GetShortPathNameW(str(path), buffer, size):
        return None
    return buffer.value or None


class CanonicalPathTests(HermeticBase):
    """8.3 短名 / 长名 / 相对写法必须归一成同一个值。

    真实事故：GitHub runner 上 Path.cwd() 给的是短名（C:/Users/RUNNER~1/...），
    mkdtemp 给的是长名（C:/Users/runneradmin/...），两个拼法不相等 —— 于是用短名启动
    的控制台永远认不出
    自己启动的那个 DSH（bin.js 路径比对不上）。归一化是唯一的解法。
    """

    def test_canonical_path_removes_dot_segments_and_is_absolute(self) -> None:
        target = self.tmp / "a" / "b"
        target.mkdir(parents=True)
        messy = self.tmp / "a" / "b" / ".." / "b"
        self.assertEqual(config.canonical_path(messy), target.resolve())
        self.assertTrue(config.canonical_path(messy).is_absolute())

    def test_canonical_path_of_nothing_is_none(self) -> None:
        self.assertIsNone(config.canonical_path(None))
        self.assertIsNone(config.canonical_path(""))

    def test_two_spellings_of_one_directory_become_one_value(self) -> None:
        harness = make_harness(self.tmp)
        spellings = [harness, Path(str(harness) + os.sep + "."),
                     Path(str(harness) + os.sep + "a" + os.sep + ".."),
                     Path(str(harness).replace(os.sep, "/"))]
        (harness / "a").mkdir()
        self.assertEqual({config.canonical_path(item) for item in spellings},
                         {harness.resolve()})

    def test_short_name_and_long_name_normalize_to_one_value(self) -> None:
        harness = make_harness(self.tmp)
        long_form = config.canonical_path(harness)
        short_form = _short_name(long_form)
        if short_form is None or Path(short_form) == long_form:
            self.skipTest("这台机器没给出 8.3 短名（卷上短名被关了）")
        self.assertNotEqual(short_form, str(long_form))     # 确实是两种拼法
        self.assertEqual(config.canonical_path(short_form), long_form)

    def test_detect_harness_hands_back_a_canonical_path(self) -> None:
        harness = make_harness(self.tmp)
        messy = Path(str(harness) + os.sep + ".")
        self.assertEqual(config.detect_harness(messy, None, self.empty), harness.resolve())


if __name__ == "__main__":
    unittest.main()
