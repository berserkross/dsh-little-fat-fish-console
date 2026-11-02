"""系统托盘（C1）。

pystray 是可选的：导入不到、或者这台机器给不出托盘（远程桌面、某些精简系统），
就安静返回失败原因，界面退回普通窗口 —— 托盘不该把程序弄崩。

托盘线程碰 Tk 控件是禁忌：菜单动作一律经 post（界面给的是 after(0, ...)）投递到
主线程执行。
"""

from __future__ import annotations

import threading

TITLE = "小肥鱼控制台"


def available() -> tuple[bool, str | None]:
    try:
        import pystray  # noqa: F401
    except Exception as exc:            # ImportError，或后端导入时自己炸了
        return False, f"没有可用的托盘库（{exc}）"
    return True, None


class Tray:
    """一层薄包装：起停托盘图标、换菜单、把动作搬回主线程。"""

    def __init__(self, icon_path=None, *, title: str = TITLE, post=None,
                 on_lost=None) -> None:
        self._icon_path = icon_path
        self.title = title
        self._post = post or (lambda fn, *args: fn(*args))
        self._on_lost = on_lost
        self._icon = None
        self._thread: threading.Thread | None = None
        self.reason: str | None = None
        self._items: list = []

    # ---- 生命周期 ----------------------------------------------------
    def start(self, items=None) -> tuple[bool, str | None]:
        """起托盘。返回 (是否成功, 失败原因)；失败时界面应该当没有托盘。"""
        ok, why = available()
        if not ok:
            self.reason = why
            return False, why
        if items:
            self._items = list(items)
        try:
            import pystray
            self._icon = pystray.Icon("dsh-console", self._image(), self.title,
                                      self._menu(pystray))
        except Exception as exc:
            self.reason = f"托盘初始化失败（{exc}）"
            return False, self.reason
        self._thread = threading.Thread(target=self._run, name="dsh-tray", daemon=True)
        self._thread.start()
        return True, None

    def _image(self):
        from PIL import Image
        from . import resources
        path = self._icon_path or resources.icon_path()
        image = Image.open(path)
        return image.convert("RGBA") if image.mode != "RGBA" else image

    def _run(self) -> None:
        try:
            self._icon.run()
        except Exception as exc:        # 托盘线程退出：界面要知道
            self.reason = f"托盘不可用（{exc}）"
            if self._on_lost is not None:
                try:
                    self._post(self._on_lost, self.reason)
                except Exception:
                    pass

    def stop(self) -> None:
        icon, self._icon = self._icon, None
        if icon is not None:
            try:
                icon.stop()
            except Exception:
                pass
        thread, self._thread = self._thread, None
        if thread is not None and thread is not threading.current_thread():
            thread.join(1.0)

    @property
    def running(self) -> bool:
        return self._icon is not None

    # ---- 菜单 --------------------------------------------------------
    def _menu(self, pystray):
        entries = []
        for index, (label, action) in enumerate(self._items):
            # pystray 把菜单文案当 text(item) 调用；零参的可调用对象必须包一层，
            # 否则点开菜单时它会带着 item 参数调进来，直接 TypeError（实测过一次）。
            text = ((lambda _item, _fn=label: _fn()) if callable(label)
                    else (lambda _item, _text=label: _text))
            entries.append(pystray.MenuItem(text, self._wrap(action), default=(index == 0)))
        return pystray.Menu(*entries)

    def _wrap(self, action):
        def handler(_icon=None, _item=None):
            try:
                self._post(action)
            except Exception:
                pass            # 托盘线程不能因为界面状态而崩
        return handler

    def update_menu(self, items) -> None:
        """换菜单（「显示/隐藏」的文案要跟着窗口状态变）。"""
        self._items = list(items)
        if self._icon is None:
            return
        try:
            import pystray
            self._icon.menu = self._menu(pystray)
            self._icon.update_menu()
        except Exception:
            pass
