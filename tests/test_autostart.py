"""开机自启动：只碰 HKCU 的 Run 键，读不到当没开，撤销不存在的值也算成功。"""
from __future__ import annotations

import sys
import unittest

from dshconsole import autostart


class FakeKey:
    """winreg 的键对象本身就支持 with —— 假货也得支持，否则测的不是同一条路径。"""

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class FakeReg:
    HKEY_CURRENT_USER = "HKCU"
    KEY_SET_VALUE = 2
    REG_SZ = 1

    def __init__(self, values=None, unreadable=False):
        self.values = dict(values or {})
        self.unreadable = unreadable
        self.writes = []

    def OpenKey(self, _root, _path, *_access):
        if self.unreadable:
            raise OSError("拒绝访问")
        return FakeKey()

    def QueryValueEx(self, _key, name):
        if name not in self.values:
            raise FileNotFoundError(name)
        return self.values[name], self.REG_SZ

    def SetValueEx(self, _key, name, _reserved, _kind, value):
        self.values[name] = value
        self.writes.append((name, value))

    def DeleteValue(self, _key, name):
        if name not in self.values:
            raise FileNotFoundError(name)
        del self.values[name]


class AutostartTests(unittest.TestCase):
    def test_missing_value_reads_as_off(self):
        self.assertFalse(autostart.enabled(FakeReg()))

    def test_registered_value_reads_as_on(self):
        reg = FakeReg({autostart.VALUE_NAME: '"C:\\x\\DSHConsole.exe"'})
        self.assertTrue(autostart.enabled(reg))

    def test_unreadable_run_key_reads_as_off(self):
        """读注册表炸了绝不能让窗口起不来，也不能谎报「已开」。"""
        self.assertFalse(autostart.enabled(FakeReg(unreadable=True)))

    def test_enabling_writes_one_quoted_command(self):
        reg = FakeReg()
        autostart.set_enabled(True, reg)
        self.assertEqual(len(reg.writes), 1)
        name, command = reg.writes[0]
        self.assertEqual(name, autostart.VALUE_NAME)
        self.assertTrue(command.startswith('"'), command)
        self.assertIn("DSHConsole.exe" if getattr(sys, "frozen", False) else "dsh_gui.py", command)
        self.assertTrue(autostart.enabled(reg))

    def test_disabling_removes_the_value(self):
        reg = FakeReg({autostart.VALUE_NAME: '"x"'})
        autostart.set_enabled(False, reg)
        self.assertFalse(autostart.enabled(reg))

    def test_disabling_an_absent_value_is_not_an_error(self):
        reg = FakeReg()
        autostart.set_enabled(False, reg)      # 不该抛
        self.assertFalse(autostart.enabled(reg))

    def test_command_quotes_the_interpreter(self):
        self.assertTrue(autostart.target_command().startswith('"'))

    def test_available_follows_the_platform(self):
        self.assertEqual(autostart.available(), sys.platform.startswith("win"))


if __name__ == "__main__":
    unittest.main()
