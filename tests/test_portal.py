"""手机端动作码：60 秒、用一次、输错不消耗、白名单之外一律不认。"""
import unittest

from dshconsole import portal


class ActionGateTests(unittest.TestCase):
    def setUp(self):
        self.now = 1000.0

    def clock(self):
        return self.now

    def gate(self, *numbers):
        seq = iter(numbers or [482913])
        return portal.ActionGate(clock=self.clock, rand=lambda span: next(seq) % span)

    def test_mint_is_six_digits_and_starts_the_countdown(self):
        gate = self.gate(7)
        code = gate.mint()
        self.assertEqual(code, "000007")
        self.assertEqual(gate.remaining(), int(portal.CODE_TTL))

    def test_redeem_consumes_the_grant(self):
        gate = self.gate(482913)
        code = gate.mint()
        ok, message = gate.redeem(code, "restart")
        self.assertTrue(ok)
        self.assertIn("重启", message)
        self.assertEqual(gate.remaining(), 0)
        again, why = gate.redeem(code, "restart")
        self.assertFalse(again)
        self.assertIn("还没有签", why)

    def test_wrong_code_does_not_burn_the_grant(self):
        gate = self.gate(482913)
        code = gate.mint()
        ok, why = gate.redeem("000000", "stop")
        self.assertFalse(ok)
        self.assertIn("不对", why)
        self.assertEqual(gate.remaining(), int(portal.CODE_TTL))
        self.assertTrue(gate.redeem(code, "stop")[0])

    def test_code_expires_after_the_ttl(self):
        gate = self.gate(482913)
        code = gate.mint()
        self.now += portal.CODE_TTL + 0.5
        ok, why = gate.redeem(code, "start")
        self.assertFalse(ok)
        self.assertIn("过期", why)
        self.assertEqual(gate.remaining(), 0)

    def test_intent_outside_the_whitelist_never_passes(self):
        gate = self.gate(482913)
        code = gate.mint()
        ok, why = gate.redeem(code, "quit")
        self.assertFalse(ok)
        self.assertIn("不认识", why)
        self.assertTrue(gate.redeem(code, "start")[0])   # 没被顺手作废

    def test_minting_again_replaces_the_previous_code(self):
        gate = self.gate(111111, 222222)
        first = gate.mint()
        second = gate.mint()
        self.assertEqual((first, second), ("111111", "222222"))
        self.assertFalse(gate.redeem(first, "restart")[0])
        self.assertTrue(gate.redeem(second, "restart")[0])

    def test_actions_cover_exactly_the_lifecycle_trio(self):
        self.assertEqual(sorted(portal.ACTIONS), ["restart", "start", "stop"])


if __name__ == "__main__":
    unittest.main()
