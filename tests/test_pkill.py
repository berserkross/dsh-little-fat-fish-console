"""dshconsole.pkill 的单元测试：算清「杀谁、放过谁」，只碰真的该结束的进程。"""
from __future__ import annotations

import unittest

from dshconsole import pkill


class _Result:
    def __init__(self, ok: bool, stdout: str = "", text: str = ""):
        self.ok = ok
        self.stdout = stdout
        self.text = text or stdout

    def why(self) -> str:
        return "" if self.ok else (self.text or "失败")


class _Runner:
    """第一次回进程表，第二次回执行结果；把两次的脚本都记下来。"""

    def __init__(self, parents: str, ok: bool = True):
        self.parents = parents
        self.ok = ok
        self.calls: list[str] = []

    def __call__(self, script, timeout=None):
        self.calls.append(script)
        if len(self.calls) == 1:
            return _Result(True, self.parents)
        return _Result(self.ok, "done", "拒绝访问" if not self.ok else "")


class ParseTests(unittest.TestCase):
    def test_parse_parents_keeps_only_number_pairs(self):
        pairs = pkill.parse_parents("10=1\n 11 = 10 \n乱码\n12=abc\n")
        self.assertEqual(pairs, {10: 1, 11: 10})

    def test_ancestors_walk_up_and_stop_at_missing_parent(self):
        parent_of = {30: 20, 20: 10}
        self.assertEqual(pkill.ancestors(30, parent_of), [30, 20, 10])
        self.assertEqual(pkill.ancestors(10, parent_of), [10])

    def test_ancestors_do_not_loop_forever_on_a_cycle(self):
        self.assertEqual(pkill.ancestors(5, {5: 6, 6: 5}), [5, 6])


class KillSetTests(unittest.TestCase):
    def test_subtree_follows_children_not_parents(self):
        parent_of = {10: 1, 11: 10, 12: 11, 13: 1}
        kids = pkill.children_of(parent_of)
        self.assertEqual(pkill.subtree([10], kids), {10, 11, 12})
        self.assertEqual(pkill.subtree([13], kids), {13})

    def test_whole_tree_goes_when_nothing_is_protected(self):
        parent_of = {10: 1, 11: 10, 12: 11}
        self.assertEqual(pkill.kill_set([10], parent_of, []), [10, 11, 12])

    def test_protected_subtree_is_cut_out_with_its_children(self):
        # 控制台 11 是从 DSH(10) 里被拉起来的：10 要杀，11 和它下面的 12 都不能碰。
        parent_of = {10: 1, 11: 10, 12: 11, 13: 1}
        self.assertEqual(pkill.kill_set([10], parent_of, [11]), [10])
        self.assertEqual(pkill.kill_set([10], parent_of, [12]), [10, 11])

    def test_a_protected_pid_outside_the_tree_changes_nothing(self):
        parent_of = {10: 1, 11: 10}
        self.assertEqual(pkill.kill_set([10], parent_of, [99]), [10, 11])


class StopTreeTests(unittest.TestCase):
    def test_kills_only_what_should_die_and_reports_what_it_spared(self):
        runner = _Runner("10=1\n11=10\n12=11\n13=1\n")
        killed, spared, err = pkill.stop_tree([10], [11], runner=runner)
        self.assertEqual((killed, spared, err), ([10], [11, 12], None))
        self.assertEqual(len(runner.calls), 2)
        self.assertIn("Stop-Process -Id 10", runner.calls[1])
        self.assertNotIn("Stop-Process -Id 11", runner.calls[1])
        self.assertNotIn("Stop-Process -Id 12", runner.calls[1])

    def test_nothing_to_kill_means_no_kill_command(self):
        runner = _Runner("10=1\n11=10\n")
        killed, spared, err = pkill.stop_tree([11], [11], runner=runner)
        self.assertEqual((killed, spared, err), ([], [11], None))
        self.assertEqual(len(runner.calls), 1)

    def test_query_failure_is_reported_not_guessed(self):
        killed, _spared, err = pkill.stop_tree(
            [10], [], runner=lambda script, timeout=None: _Result(False, "", "拒绝访问"))
        self.assertEqual(killed, [])
        self.assertIn("查不到进程树", err or "")

    def test_empty_process_table_is_an_error_not_an_empty_tree(self):
        _killed, _spared, err = pkill.stop_tree([10], [], runner=_Runner(""))
        self.assertIn("没有返回任何进程", err or "")

    def test_no_roots_means_no_work(self):
        runner = _Runner("10=1\n")
        self.assertEqual(pkill.stop_tree([], [1], runner=runner), ([], [], None))
        self.assertEqual(runner.calls, [])

    def test_kill_failure_surfaces_the_reason(self):
        runner = _Runner("10=1\n", ok=False)
        killed, _spared, err = pkill.stop_tree([10], [], runner=runner)
        self.assertEqual(killed, [10])
        self.assertIn("拒绝访问", err or "")


if __name__ == "__main__":
    unittest.main()
