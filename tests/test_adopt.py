"""采纳运行中的实例：从 bin.js 反推 harness、写回 config.json。"""
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from dshconsole import adopt, config

REAL_TAIL = Path("node_modules") / "@deepseek-ai" / "dsh" / "lib" / "bin.js"


def make_install(root: Path, prefix: str = "") -> Path:
    """在 root/prefix 下造一份 harness 目录树，返回它的 bin.js。"""
    harness = root / prefix if prefix else root
    bin_js = harness / REAL_TAIL
    bin_js.parent.mkdir(parents=True, exist_ok=True)
    bin_js.write_text("// fake\n", encoding="utf-8")
    return bin_js


class HarnessFromBinJsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def test_plain_install(self):
        bin_js = make_install(self.root / "harness")
        self.assertEqual(adopt.harness_from_bin_js(bin_js), self.root / "harness")

    def test_npx_cache_layout(self):
        bin_js = make_install(self.root / "_npx" / "1e7f6d9")
        self.assertEqual(adopt.harness_from_bin_js(bin_js),
                         self.root / "_npx" / "1e7f6d9")

    def test_dot_bin_backslash_dotdot_is_collapsed(self):
        make_install(self.root / "_npx" / "hash")
        raw = str(self.root / "_npx" / "hash" / "node_modules" / ".bin"
                  / ".." / "@deepseek-ai" / "dsh" / "lib" / "bin.js")
        self.assertEqual(adopt.harness_from_bin_js(raw),
                         self.root / "_npx" / "hash")

    def test_missing_bin_js_is_not_guessed(self):
        self.assertIsNone(adopt.harness_from_bin_js(self.root / "nope" / REAL_TAIL))

    def test_empty_and_short_paths(self):
        for value in (None, "", "bin.js", r"C:\bin.js"):
            self.assertIsNone(adopt.harness_from_bin_js(value))


class FromProcessesTests(unittest.TestCase):
    def test_duplicates_and_junk_are_dropped(self):
        cands = adopt.from_processes([
            (9856, r"C:\a\node_modules\@deepseek-ai\dsh\lib\bin.js"),
            (9856, r"C:\a\node_modules\@deepseek-ai\dsh\lib\bin.js"),
            ("not-a-pid", "x"),
            (None, "x"),
            (12, None),
        ])
        self.assertEqual([c.pid for c in cands], [9856])
        self.assertIn("PID 9856", cands[0].label)

    def test_none_payload_is_empty(self):
        self.assertEqual(adopt.from_processes(None), [])


class CandidatesTests(unittest.TestCase):
    def test_probe_error_is_reported_not_swallowed(self):
        with mock.patch.object(adopt.probe, "other_dsh_processes",
                               lambda *_a, **_k: (None, "超时")):
            found, err = adopt.candidates("x")
        self.assertIsNone(found)
        self.assertEqual(err, "超时")

    def test_candidates_are_converted(self):
        with mock.patch.object(adopt.probe, "other_dsh_processes",
                               lambda *_a, **_k: ([(7, r"C:\a\node_modules\@deepseek-ai\dsh\lib\bin.js")], None)):
            found, err = adopt.candidates("x")
        self.assertIsNone(err)
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0].pid, 7)


class AdoptTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.bin_js = make_install(self.root / "harness")
        self.harness = self.root / "harness"
        self.cfg_path = self.root / "config.json"
        self.cfg = config.resolve(explicit_harness=str(self.root / "other"),
                                  path=self.cfg_path, cwd=self.root)

    def test_writes_harness_and_source_marker(self):
        cand = adopt.Candidate(pid=4242, bin_js=str(self.bin_js), harness=self.harness)
        new, message = adopt.adopt(self.cfg, cand, path=self.cfg_path)
        self.assertIsNotNone(new)
        self.assertEqual(new.harness, self.harness)
        self.assertEqual(new.source, adopt.ADOPTED)
        self.assertIn("已改为控制", message)
        saved = json.loads(self.cfg_path.read_text(encoding="utf-8"))
        self.assertEqual(saved["source"], "adopted")
        reloaded = config.load(self.cfg_path)
        self.assertEqual(reloaded["harness"], str(self.harness))
        self.assertEqual(reloaded["source"], "adopted")

    def test_unresolved_harness_is_refused_and_writes_nothing(self):
        cand = adopt.Candidate(pid=1, bin_js=r"C:\weird\bin.js", harness=None)
        new, message = adopt.adopt(self.cfg, cand, path=self.cfg_path)
        self.assertIsNone(new)
        self.assertIn("--harness", message)
        self.assertFalse(self.cfg_path.exists())


if __name__ == "__main__":
    unittest.main()
