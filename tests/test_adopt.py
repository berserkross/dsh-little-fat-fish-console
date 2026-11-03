"""采纳运行中的实例：从 bin.js 反推 harness、写回 config.json。"""
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from dshconsole import adopt, config, psrun

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


class PortOwnerTests(unittest.TestCase):
    """端口占用者：「接管」最硬的一条线索，解析与失败都要说得清。"""

    def _runner(self, payload):
        return lambda *_a, **_k: payload

    def test_parse_returns_pid_and_command_line(self):
        got = adopt.parse_port_owner('{"pid":4242,"command_line":"node x"}')
        self.assertEqual(got, (4242, "node x"))

    def test_null_and_garbage_are_none(self):
        for raw in ("", "null", "NULL", "not json", "[]"):
            self.assertIsNone(adopt.parse_port_owner(raw))

    def test_bin_js_is_picked_out_of_the_command_line(self):
        with tempfile.TemporaryDirectory() as tmp:
            bin_js = make_install(Path(tmp) / "harness")
            line = f'"node.EXE" "{bin_js}" web --port 3080'
            self.assertTrue(adopt.bin_js_from_command_line(line).endswith("bin.js"))

    def test_command_line_without_bin_js_is_refused(self):
        self.assertIsNone(adopt.bin_js_from_command_line("notepad.exe foo.txt"))

    def test_candidate_from_port_owner_carries_via_port(self):
        with tempfile.TemporaryDirectory() as tmp:
            bin_js = make_install(Path(tmp) / "harness")
            payload = psrun.PsResult(
                True, 0, json.dumps({"pid": 4242, "command_line": f'node "{bin_js}" web'}),
                "", None)
            cand, why = adopt.from_port_owner(3080, runner=self._runner(payload))
        self.assertIsNone(why)
        self.assertEqual((cand.pid, cand.via), (4242, adopt.VIA_PORT))
        self.assertIn("正在监听端口", cand.label)

    def test_runner_failure_is_reported(self):
        cand, why = adopt.from_port_owner(
            3080, runner=self._runner(psrun.PsResult(False, 1, "", "boom", None)))
        self.assertIsNone(cand)
        self.assertIn("查端口", why)

    def test_free_port_is_not_an_error(self):
        cand, why = adopt.from_port_owner(
            3080, runner=self._runner(psrun.PsResult(True, 0, "null", "", None)))
        self.assertIsNone(cand)
        self.assertIsNone(why)

    def test_owner_without_bin_js_says_which_pid(self):
        payload = psrun.PsResult(
            True, 0, json.dumps({"pid": 999, "command_line": "python server.py"}), "", None)
        cand, why = adopt.from_port_owner(3080, runner=self._runner(payload))
        self.assertIsNone(cand)
        self.assertIn("999", why)


class MergeTests(unittest.TestCase):
    def test_dedupes_by_pid_and_keeps_order(self):
        port = adopt.Candidate(pid=1, bin_js="a", harness=None, via=adopt.VIA_PORT)
        same = adopt.Candidate(pid=1, bin_js="a", harness=None)
        other = adopt.Candidate(pid=2, bin_js="b", harness=None)
        got = adopt.merge([port], [same, other])
        self.assertEqual([c.pid for c in got], [1, 2])
        self.assertEqual(got[0].via, adopt.VIA_PORT)

    def test_limit_keeps_the_first(self):
        cands = [adopt.Candidate(pid=i, bin_js="x", harness=None) for i in range(1, 6)]
        self.assertEqual([c.pid for c in adopt.merge(cands)], [1, 2, 3])


if __name__ == "__main__":
    unittest.main()
