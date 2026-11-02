"""状态缓存：TTL 内复用、手动刷新穿透、失败不缓存（C6 的非阻塞刷新靠它）。"""
import unittest

from dshconsole import snapshot


class FakeClock:
    def __init__(self):
        self.now = 100.0

    def __call__(self):
        return self.now


class SnapshotTests(unittest.TestCase):
    def setUp(self):
        self.clock = FakeClock()
        self.loads = 0

    def make(self, ttl=3.0):
        def load():
            self.loads += 1
            return f"结果{self.loads}"

        return snapshot.Snapshot(load, ttl=ttl, clock=self.clock)

    def test_first_get_loads_and_reports_not_cached(self):
        snap = self.make()
        self.assertEqual(snap.get(), ("结果1", False))
        self.assertEqual(self.loads, 1)

    def test_inside_ttl_reuses_the_previous_value(self):
        snap = self.make()
        snap.get()
        self.clock.now += 1.0                      # 还在 3 秒内
        self.assertEqual(snap.get(), ("结果1", True))
        self.assertEqual(self.loads, 1)

    def test_expired_entry_reloads(self):
        snap = self.make(ttl=2.0)
        snap.get()
        self.clock.now += 2.5
        self.assertEqual(snap.get(), ("结果2", False))
        self.assertEqual(self.loads, 2)

    def test_force_pierces_the_cache(self):
        snap = self.make()
        snap.get()
        self.assertEqual(snap.get(force=True), ("结果2", False))
        self.assertEqual(self.loads, 2)

    def test_invalidate_forces_the_next_load(self):
        snap = self.make()
        snap.get()
        snap.invalidate()
        self.assertEqual(snap.get(), ("结果2", False))

    def test_failed_load_is_not_cached(self):
        boom = []

        def load():
            boom.append(1)
            raise RuntimeError("探测炸了")

        snap = snapshot.Snapshot(load, ttl=60.0, clock=self.clock)
        for _ in range(2):
            with self.assertRaises(RuntimeError):
                snap.get()
        self.assertEqual(len(boom), 2)             # 失败没有变成缓存里的「成功」
        self.assertIsNone(snap.age())

    def test_age_reports_seconds_since_the_last_load(self):
        snap = self.make()
        self.assertIsNone(snap.age())
        snap.get()
        self.clock.now += 1.5
        self.assertAlmostEqual(snap.age(), 1.5, places=3)

    def test_ttl_floor_is_not_silently_zero(self):
        snap = self.make(ttl=0.0)                  # TTL=0 等于不缓存，每次都要重取
        snap.get()
        self.assertEqual(snap.get(), ("结果2", False))


if __name__ == "__main__":
    unittest.main()
