"""日志视口对齐助手：snap_to_line 只碰像素，不碰内容。

这几条用例都拿替身替代真实控件，所以不需要显示器；widgets 导入失败时整模块跳过。
"""
from __future__ import annotations

import unittest

try:
    from dshconsole import widgets
except Exception as exc:  # noqa: BLE001 - 没有 GUI 依赖的环境跳过
    widgets = None
    _IMPORT_ERROR = exc
else:
    _IMPORT_ERROR = None


class _FakeInner:
    def __init__(self, info):
        self._info = info
        self.scrolls = []

    def dlineinfo(self, _index):
        if isinstance(self._info, Exception):
            raise self._info
        return self._info

    def yview_scroll(self, amount, unit):
        self.scrolls.append((amount, unit))


class _FakeBox:
    def __init__(self, inner):
        self._textbox = inner


@unittest.skipIf(widgets is None, "GUI 依赖缺失：%s" % (_IMPORT_ERROR,))
class SnapToLineTests(unittest.TestCase):
    def test_scrolls_up_when_top_row_is_cut(self):
        inner = _FakeInner((2, -9, 10, 22, 17))
        widgets.snap_to_line(_FakeBox(inner))
        self.assertEqual(inner.scrolls, [(-9, "pixels")])

    def test_no_scroll_when_top_row_is_flush(self):
        inner = _FakeInner((2, 0, 10, 22, 17))
        widgets.snap_to_line(_FakeBox(inner))
        self.assertEqual(inner.scrolls, [])

    def test_no_scroll_when_line_info_is_missing(self):
        inner = _FakeInner(None)
        widgets.snap_to_line(_FakeBox(inner))
        self.assertEqual(inner.scrolls, [])

    def test_stub_without_inner_textbox_is_ignored(self):
        class Stub:  # 测试里的 SimpleNamespace 就是这种形状
            pass

        widgets.snap_to_line(Stub())  # 不抛异常即通过

    def test_destroyed_widget_is_ignored(self):
        inner = _FakeInner(RuntimeError("invalid command name"))
        widgets.snap_to_line(_FakeBox(inner))
        self.assertEqual(inner.scrolls, [])


if __name__ == "__main__":
    unittest.main()
