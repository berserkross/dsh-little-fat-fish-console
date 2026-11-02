"""自绘控件（批次 F「玻璃单列流」）：玻璃背景板、状态灯、鲸鱼娘素材、模态浮层、全屏日志窗。

只负责「长什么样 + 怎么关」，不承载业务：浮层里的每一个动作都由调用方 dsh_gui 传进来。
所有颜色与尺寸取自 ui_theme，改皮肤不必动这里。

玻璃背景板是整窗唯一的「半透明」来源：customtkinter 会把 fg_color="transparent" 在创建
时就解析成母控件的实底色（实测叠在 lowered Canvas 上也透不出来），所以真正的通透来自
Pillow 预渲染的整窗图 —— 深蓝径向渐变 + <=6% 网格星点 + 每块面板外扩 PANEL_RIM 的
玻璃框（1px 亮边 + 外柔影）。真实控件叠在图上，面板底色直接取渲染图上的采样色，
两者同色所以无缝。
"""
from __future__ import annotations

import math
import random
from functools import lru_cache
from typing import Callable, Sequence

import customtkinter as ctk
from PIL import Image, ImageDraw, ImageFilter, ImageTk

from . import resources
from . import status as app_status
from . import ui_theme

MenuItem = tuple[str, Callable[[], None]]

# 素材文件名：另一条线（自绘素材）交付到 dshconsole/data/art/。
# 这里只认名字，不认内容 —— 缺图就走矢量回退，绝不崩、也不留白块。
ART_FILES = {
    "idle": "mascot_idle@72.png",
    "running": "mascot_running@72.png",
    "error": "mascot_error@72.png",
    "hero": "mascot_hero@256.png",
    "logo": "mascot_logo@32.png",
}


def trim_textbox(box, limit: int) -> None:
    """行数自愈：超过 limit 就从顶部丢旧行。

    与主日志框同一套算法，放在这里给全屏窗复用；控件已销毁时静默返回。
    """
    try:
        total = int(str(box.index("end-1c")).split(".")[0])
    except Exception:
        return
    if total <= limit:
        return
    try:
        box.delete("1.0", "%d.0" % (total - limit + 1))
    except Exception:
        return


def snap_to_line(textbox) -> None:
    """把视口上沿对齐到整行，消掉顶部被切一半的那行。

    贴底（yview_moveto(1.0)）只保证最后一行可见，视口高度不是行高整数倍时，
    顶部那行就会只露下半截——而 index("@0,0") 报的是逻辑行，换行续行看不出错位。
    这里用内层控件的 dlineinfo 读那行的真实像素位置（y<0 表示行顶在视口之上），
    再按像素回滚。控件替身没有 _textbox，直接早退。
    """
    inner = getattr(textbox, "_textbox", None)
    if inner is None:
        return
    try:
        info = inner.dlineinfo("@0,0")
        if not info:
            return
        if info[1] < 0:
            inner.yview_scroll(info[1], "pixels")
    except Exception:  # noqa: BLE001 - 已销毁 / 控件替身
        return


# ---------------- 颜色小工具（Canvas 与 Pillow 都不吃 alpha，只能自己混） ----------------
def _rgb(color: str) -> tuple[int, int, int]:
    text = color.strip().lstrip("#")
    return (int(text[0:2], 16), int(text[2:4], 16), int(text[4:6], 16))


def _hex(rgb: Sequence[int]) -> str:
    return "#%02X%02X%02X" % (int(rgb[0]), int(rgb[1]), int(rgb[2]))


def blend(fore: str, back: str, weight: float) -> str:
    """把 fore 按 weight 混到 back 上，得到等价的不透明色（模拟半透明叠加）。"""
    t = max(0.0, min(1.0, float(weight)))
    f, b = _rgb(fore), _rgb(back)
    return _hex([round(b[i] + (f[i] - b[i]) * t) for i in range(3)])


# ---------------- 鲸鱼娘素材：只加载 + 回退，不自造图 ----------------
@lru_cache(maxsize=8)
def art_image(role: str) -> Image.Image | None:
    """读 dshconsole/data/art/ 里的一张素材；缺图返回 None（调用方走矢量回退）。

    路径走 resources.data_file，打包成 exe 后同样找得到；返回的图带 alpha，
    直接 alpha_composite 到目标画布上，白边不会出现。
    """
    name = ART_FILES.get(role)
    if not name:
        return None
    try:
        path = resources.data_file("art/" + name)
        if not path.is_file():
            return None
        with Image.open(path) as raw:
            return raw.convert("RGBA")
    except Exception:  # noqa: BLE001 - 缺图 / 坏图 / 打包后路径失效
        return None


def _whale(size: int, base: str, glow: float = 1.0) -> Image.Image:
    """内联矢量回退：一条圆头蓝鲸（透明底），风格与自绘素材同源。

    素材缺失时它顶上来 —— 头部徽章、日志空态都用它，所以永远有图形可看，
    不会出现「图片加载失败」的空框。
    """
    s = max(12, int(size))
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    body = blend(ui_theme.CYAN, "#FFFFFF", 0.18)
    belly = blend("#FFFFFF", body, 0.22)
    ring = blend(ui_theme.PRIMARY_GLOW, base, 1.0 - min(1.0, glow))
    # 身体：一个横向椭圆，右下留出尾巴的位置
    d.ellipse((s * 0.08, s * 0.30, s * 0.74, s * 0.76), fill=body)
    # 腹部高光：压在身体下半部
    d.ellipse((s * 0.16, s * 0.52, s * 0.70, s * 0.74), fill=belly)
    # 尾巴：两片三角，向上翘
    d.polygon([(s * 0.70, s * 0.52), (s * 0.92, s * 0.26), (s * 0.90, s * 0.56)], fill=body)
    d.polygon([(s * 0.70, s * 0.56), (s * 0.92, s * 0.62), (s * 0.86, s * 0.44)], fill=body)
    # 眼睛与腮红：可爱风的最小单元
    eye = max(2, int(s * 0.055))
    d.ellipse((s * 0.26, s * 0.44, s * 0.26 + eye, s * 0.44 + eye), fill=blend("#0B1730", body, 0.85))
    d.ellipse((s * 0.38, s * 0.55, s * 0.38 + eye * 1.6, s * 0.55 + eye), fill=blend("#FFB3C6", body, 0.55))
    # 喷水：三点，越远越小
    for i, r in enumerate((0.05, 0.035, 0.022)):
        cx, cy = s * (0.26 + i * 0.075), s * (0.20 - i * 0.03)
        d.ellipse((cx - s * r, cy - s * r, cx + s * r, cy + s * r), fill=ring)
    return img


def mascot(role: str, size: int, base: str) -> Image.Image:
    """取一张透明底鲸鱼娘（素材优先，缺失用矢量），缩放到 size。"""
    s = max(12, int(size))
    art = art_image(role)
    if art is None:
        return _whale(s, base)
    return art.resize((s, s), Image.LANCZOS)


@lru_cache(maxsize=16)
def badge(size: int, base: str) -> Image.Image:
    """头部徽章：圆形玻璃底盘 + 淡蓝发光描边 + 鲸鱼娘。

    底盘底色必须等于所在面板的采样色，否则圆图的四个角会在面板上留下一个方块。
    """
    s = max(20, int(size))
    img = Image.new("RGBA", (s, s), _rgb(base) + (255,))
    d = ImageDraw.Draw(img)
    # 外发光：三层由淡到浓的同心圆，模拟光晕（Canvas 没有 alpha，Pillow 这里有）
    for step, alpha in ((0, 34), (1, 58), (2, 92)):
        inset = s * (0.005 + 0.035 * (2 - step))
        d.ellipse((inset, inset, s - inset, s - inset),
                  outline=blend(ui_theme.PRIMARY_GLOW, base, alpha / 255.0))
    d.ellipse((s * 0.03, s * 0.03, s * 0.97, s * 0.97),
              outline=_rgb(blend(ui_theme.PRIMARY_GLOW, base, 0.55)))
    # 玻璃盘：中心比边缘亮一点，像一块被照亮的圆玻璃
    d.ellipse((s * 0.07, s * 0.07, s * 0.93, s * 0.93),
              fill=_rgb(blend(ui_theme.PRIMARY_GLOW, base, 0.16)))
    inner = mascot("idle", int(s * 0.74), base)
    off = (s - inner.width) // 2
    img.alpha_composite(inner, (off, off))
    return img


def hero_picture(size: int, base: str) -> Image.Image:
    """空态插画（透明底），尺寸按窗口缩放后给，150% 下不会缩成一小坨。"""
    return mascot("hero", size, base)


def apply_window_icon(win) -> bool:
    """标题栏图标：优先自绘 logo（PNG），缺失回退仓库里的 .ico。返回是否用上了素材。"""
    logo = art_image("logo")
    if logo is not None:
        try:
            win._icon_photo = ImageTk.PhotoImage(logo)  # 必须留引用，否则 Tk 回收后图标变空白
            win.iconphoto(True, win._icon_photo)
            return True
        except Exception:  # noqa: BLE001 - 无显示环境
            pass
    icon = resources.icon_path()
    if icon is not None:
        try:
            win.iconbitmap(str(icon))
        except Exception:  # noqa: BLE001 - .ico 读不了（Linux / 坏图）
            pass
    return False


# ---------------- 状态灯 ----------------
class StatusLamp(ctk.CTkCanvas):
    """状态灯：一颗发光的圆点，颜色 + 填充比例表达五态。

    读法：实心点＝走满一圈（未运行 / 运行中 / 异常），缺口弧＝还在路上（启动中 / 未知）。
    外圈两层同色低亮度圆是光晕（Canvas 不吃 alpha，用与底色混出来的等效色画）。
    灯本身只有颜色和形状，状态词永远并列写在头部 —— 灰度截图与色弱用户靠那行字。
    """

    def __init__(self, master, size: int = ui_theme.STATUS_LAMP, **kwargs) -> None:
        background = kwargs.pop("bg", ui_theme.CARD)
        pad = 5
        box = int(size) + pad * 2
        super().__init__(master, width=box, height=box, bg=background,
                         highlightthickness=0, bd=0, **kwargs)
        self._box = box
        self._pad = pad
        self._bg = background
        self.phase_text = ui_theme.PHASE_WORD[app_status.Phase.UNKNOWN]
        self.color = ui_theme.FAINT
        self.sweep = 0.0
        self._halo = self.create_oval(0, 0, box, box, outline="", fill="")
        self._glow = self.create_oval(box * 0.13, box * 0.13, box * 0.87, box * 0.87,
                                      outline="", fill="")
        core = (pad, pad, box - pad, box - pad)
        self._core = self.create_oval(*core, outline=ui_theme.FAINT, fill=ui_theme.FAINT)
        self._arc = self.create_arc(*core, start=90, extent=-90, style="arc",
                                    outline=ui_theme.FAINT, width=3)
        self._hollow = self.create_oval(*core, outline=ui_theme.FAINT, width=2, fill="")
        self.render(ui_theme.FAINT, 0.0)

    def render(self, color: str, sweep: float) -> None:
        """重画一次：走满的实心、没走满的留弧、比例为 0 的只剩一圈空心。"""
        ratio = max(0.0, min(1.0, float(sweep)))
        filled = ratio >= 1.0
        partial = 0.0 < ratio < 1.0
        # 光晕：越外越淡，混出等效色（Canvas 没有 alpha 通道）
        self.itemconfigure(self._halo, fill=blend(color, self._bg, 0.10),
                           state="normal" if filled or partial else "hidden")
        self.itemconfigure(self._glow, fill=blend(color, self._bg, 0.22),
                           state="normal" if filled or partial else "hidden")
        self.itemconfigure(self._core, fill=color, outline=color,
                           state="normal" if filled else "hidden")
        # 封顶 359 度：整圈会被 Tk 9 归零，画出来什么都没有。
        self.itemconfigure(self._arc, outline=color, extent=-359.0 * ratio,
                           state="normal" if partial else "hidden")
        self.itemconfigure(self._hollow, outline=color,
                           state="normal" if not filled and not partial else "hidden")
        self.color = color
        self.sweep = ratio

    def set_status(self, phase) -> None:
        """按阶段点亮：颜色与填充比例都取自 PHASE_STYLE。"""
        style = ui_theme.PHASE_STYLE.get(phase) or ui_theme.PHASE_STYLE[app_status.Phase.UNKNOWN]
        word = ui_theme.PHASE_WORD.get(phase) or ui_theme.PHASE_WORD[app_status.Phase.UNKNOWN]
        self.render(style.color, style.sweep)
        self.phase_text = word


# ---------------- 玻璃背景板 ----------------
@lru_cache(maxsize=3)
def _gradient(width: int, height: int) -> Image.Image:
    """深蓝径向渐变：左上偏一点暖蓝，四周压到近黑（衬得住半透明白字）。

    先算 96x96 再双三次放大 —— 渐变的低频特征不需要逐像素算，省掉整窗的 Python 循环。
    """
    top, edge = (34, 56, 104), (6, 10, 22)
    small = Image.new("RGB", (96, 96))
    put = small.load()
    for y in range(96):
        for x in range(96):
            u = x / 95.0 - 0.22
            v = y / 95.0 - 0.02
            dist = min(1.0, math.hypot(u * 1.5, v * 1.25) / 1.15)
            t = (1.0 - dist) ** 1.8
            put[x, y] = tuple(int(edge[i] + (top[i] - edge[i]) * t) for i in range(3))
    return small.resize((max(1, width), max(1, height)), Image.BICUBIC).convert("RGBA")


def _aurora(width: int, height: int) -> Image.Image:
    """极光：三团大范围低亮度色块，1/3 分辨率上画完再放大（模糊成本降到 1/9）。"""
    sw, sh = max(1, width // 3), max(1, height // 3)
    layer = Image.new("RGBA", (sw, sh), (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    for i, color in enumerate(ui_theme.AURORA):
        cx = (0.16 + 0.36 * i) * sw
        cy = (0.10 + 0.30 * (i % 2)) * sh
        rx, ry = sw * (0.34 + 0.06 * i), sh * (0.28 + 0.05 * i)
        draw.ellipse((cx - rx, cy - ry, cx + rx, cy + ry), fill=color)
    layer = layer.filter(ImageFilter.GaussianBlur(max(1, sw // 14)))
    return layer.resize((max(1, width), max(1, height)), Image.BILINEAR)


def _grid_stars(width: int, height: int, scale: float) -> Image.Image:
    """衬底网格 + 星点：全部压在 6% 以内，只做质感，绝不干扰读字。"""
    layer = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    step = max(18, int(round(30 * scale)))
    for x in range(0, width, step):
        draw.line((x, 0, x, height), fill=ui_theme.GRID_LINE)
    for y in range(0, height, step):
        draw.line((0, y, width, y), fill=ui_theme.GRID_LINE)
    rnd = random.Random(20260101)  # 固定种子：每帧星位一致，拖动窗口不会「闪」出新的星
    for _ in range(max(24, int(width * height / 14000))):
        x, y = rnd.randrange(width), rnd.randrange(height)
        r = 1 if rnd.random() < 0.72 else 2
        draw.ellipse((x, y, x + r, y + r), fill=ui_theme.STAR_DOT)
    return layer


class GlassBackdrop(ctk.CTkCanvas):
    """整窗玻璃背景板：一张 Pillow 合成的图，铺在窗口最底层。

    调用方只给「面板矩形」（逻辑坐标），这里负责外扩 PANEL_RIM 烘出玻璃框，
    并把面板内部的采样色回传 —— 控件用这个颜色当底色就无缝。
    """

    def __init__(self, master, background: str = ui_theme.BG, **kwargs) -> None:
        super().__init__(master, background=background, highlightthickness=0, bd=0, **kwargs)
        self._photo = None
        self._item = None
        self._painting = False
        self.last_ms = 0

    def paint(self, width: int, height: int, scale: float,
              panels: Sequence[tuple[str, str, int, int, int, int, int]] = ()) -> dict[str, str]:
        """重画整窗底图，返回 {面板 key: 采样色}。

        panels 每项 = (key, kind, x, y, w, h, radius)，逻辑像素；kind：
          "panel" —— 玻璃面板（回传采样色）
          "glow"  —— 主按钮光晕（只发光，不采样）
        画不出来就保留上一帧（宁可旧底图，也不要半黑窗口）。
        """
        import time
        started = time.perf_counter()
        w = max(1, int(round(width * scale)))
        h = max(1, int(round(height * scale)))
        try:
            img = _gradient(w, h).copy()
            img.alpha_composite(_aurora(w, h))
            img.alpha_composite(_grid_stars(w, h, scale))
            samples = self._compose_panels(img, panels, scale)
            photo = ImageTk.PhotoImage(img)
            self._photo = photo
            if self._item is None:
                self._item = self.create_image(0, 0, anchor="nw", image=photo)
            else:
                self.itemconfigure(self._item, image=photo)
            self.last_ms = int((time.perf_counter() - started) * 1000)
            return samples
        except Exception:  # noqa: BLE001 - 无显示 / 图太大 / PhotoImage 失败
            return {}

    def _compose_panels(self, img: Image.Image, panels, scale: float) -> dict[str, str]:
        w, h = img.size
        shadow = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        glass = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        sd, gd = ImageDraw.Draw(shadow), ImageDraw.Draw(glass)
        card = _rgb(ui_theme.CARD)
        rim = int(round(ui_theme.PANEL_RIM * scale))
        edge = max(1, int(round(scale)))
        boxes = []
        for key, kind, x, y, pw, ph, radius in panels:
            box = (x * scale, y * scale, (x + pw) * scale, (y + ph) * scale)
            if kind == "glow":
                grow = rim + 3 * scale
                sd.rounded_rectangle((box[0] - grow, box[1] - grow, box[2] + grow, box[3] + grow),
                                     radius=int(radius * scale + grow), fill=ui_theme.GLOW)
                continue
            out = (box[0] - rim, box[1] - rim, box[2] + rim, box[3] + rim)
            r_out = int(round(radius * scale)) + rim
            sd.rounded_rectangle((out[0] - rim, out[1] - rim, out[2] + rim, out[3] + 2 * rim),
                                 radius=r_out + rim, fill=ui_theme.GLASS_SHADOW)
            gd.rounded_rectangle(out, radius=r_out, fill=card + (255,))
            gd.rounded_rectangle(out, radius=r_out, outline=ui_theme.GLASS_EDGE, width=edge)
            # 上沿内高光：玻璃味全靠这一道，宽度只占边框内侧 1~2px
            gd.rounded_rectangle((out[0] + 2 * rim, out[1] + rim,
                                  out[2] - 2 * rim, out[1] + rim + edge * 2),
                                 radius=r_out, fill=ui_theme.GLASS_HIGHLIGHT)
            boxes.append((key, box))
        shadow = shadow.filter(ImageFilter.GaussianBlur(max(1.0, 3.0 * scale)))
        img.alpha_composite(shadow)
        img.alpha_composite(glass)
        out_colors = {}
        for key, box in boxes:
            cx = int((box[0] + box[2]) / 2)
            cy = int((box[1] + box[3]) / 2)
            cx = max(0, min(w - 1, cx))
            cy = max(0, min(h - 1, cy))
            out_colors[key] = _hex(img.getpixel((cx, cy))[:3])
        return out_colors


class _PopLayer(ctk.CTkToplevel):
    """浮层共同骨架：无边框、居中、Esc 关闭、点外部关闭、✕ 关闭。

    grab_set 之后窗外的点击也会投给本窗口，所以用 x_root/y_root 判断点在不在里面。
    """

    def __init__(self, master, *, width: int, height: int, on_close=None) -> None:
        super().__init__(master)
        self.withdraw()
        self.overrideredirect(True)
        self.configure(fg_color=ui_theme.BORDER)
        self._width = int(width)
        self._height = int(height)
        self._on_close = on_close
        self._closed = False
        self.card = ctk.CTkFrame(self, fg_color=ui_theme.CARD, corner_radius=14)
        self.card.pack(fill="both", expand=True, padx=1, pady=1)
        self.bind("<Escape>", lambda _event: self.close())
        self.bind("<Button-1>", self._on_root_click)

    def _on_root_click(self, event) -> None:
        if 0 <= event.x_root - self.winfo_rootx() < self.winfo_width() and \
                0 <= event.y_root - self.winfo_rooty() < self.winfo_height():
            return
        self.close()

    def _center(self) -> tuple[int, int]:
        try:
            master = self.master
            width, height = master.winfo_width(), master.winfo_height()
            if width > 1 and height > 1:
                return (master.winfo_rootx() + (width - self._width) // 2,
                        master.winfo_rooty() + (height - self._height) // 2)
        except Exception:
            pass
        return ((self.winfo_screenwidth() - self._width) // 2,
                (self.winfo_screenheight() - self._height) // 2)

    def show(self):
        self.update_idletasks()
        x, y = self._center()
        self.geometry("%dx%d+%d+%d" % (self._width, self._height, x, y))
        self.deiconify()
        try:
            self.attributes("-topmost", True)
            self.transient(self.master)
            self.lift()
            self.focus_force()
            self.grab_set()
        except Exception:
            pass
        return self

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            self.grab_release()
        except Exception:
            pass
        callback, self._on_close = self._on_close, None
        try:
            self.destroy()
        except Exception:
            pass
        if callback is not None:
            try:
                callback()
            except Exception:
                pass


def overlay_header(layer: _PopLayer, title: str, subtitle: str = "") -> ctk.CTkFrame:
    """浮层标题栏：左标题（可带副标题）+ 右 ✕。返回下方内容容器。"""
    head = ctk.CTkFrame(layer.card, fg_color="transparent")
    head.pack(fill="x", padx=16, pady=(14, 8))
    left = ctk.CTkFrame(head, fg_color="transparent")
    left.pack(side="left", fill="x", expand=True)
    ctk.CTkLabel(left, text=title, anchor="w", text_color=ui_theme.TEXT,
                 font=ctk.CTkFont(family=ui_theme.FONT, size=15, weight="bold")).pack(anchor="w")
    if subtitle:
        ctk.CTkLabel(left, text=subtitle, anchor="w", text_color=ui_theme.DIM,
                     font=ctk.CTkFont(family=ui_theme.FONT, size=11)).pack(anchor="w")
    ctk.CTkButton(head, text="✕", width=30, height=28, corner_radius=8, cursor="hand2",
                  fg_color="transparent", hover_color=ui_theme.CARD2,
                  text_color=ui_theme.DIM, font=ctk.CTkFont(family=ui_theme.FONT, size=13),
                  command=layer.close).pack(side="right", padx=(8, 0))
    body = ctk.CTkFrame(layer.card, fg_color="transparent")
    body.pack(fill="both", expand=True, padx=16, pady=(0, 14))
    return body


class QrOverlay(_PopLayer):
    """手机访问浮层：地址下拉 + 二维码 + 复制。关闭后主界面不留二维码。"""

    def __init__(self, master, *, on_close=None) -> None:
        width, height = ui_theme.OVERLAY_QR
        super().__init__(master, width=width, height=height, on_close=on_close)
        body = overlay_header(self, "手机访问", "同一 Wi-Fi 局域网，或已登录的 Tailscale")
        self.picker = ctk.CTkOptionMenu(
            body, values=["（尚未探测到地址）"], height=32, corner_radius=8,
            fg_color=ui_theme.CARD2, button_color=ui_theme.SLATE,
            button_hover_color=ui_theme.SLATE_DARK, text_color=ui_theme.TEXT,
            dropdown_fg_color=ui_theme.CARD2, dropdown_hover_color=ui_theme.SLATE,
            dropdown_text_color=ui_theme.TEXT,
            font=ctk.CTkFont(family=ui_theme.FONT, size=12),
            dropdown_font=ctk.CTkFont(family=ui_theme.FONT, size=12))
        self.picker.pack(fill="x")
        self.panel = ctk.CTkFrame(body, fg_color=ui_theme.WHITE_PANEL, corner_radius=12)
        self.panel.pack(fill="both", expand=True, pady=12)
        self.image_label = ctk.CTkLabel(self.panel, text="", fg_color=ui_theme.WHITE_PANEL,
                                        text_color=ui_theme.SLATE, width=252, height=252)
        self.image_label.pack(expand=True)
        self.hint = ctk.CTkLabel(body, text="", anchor="w", text_color=ui_theme.DIM,
                                 font=ctk.CTkFont(family=ui_theme.MONO, size=11))
        self.hint.pack(fill="x")
        self.actions = ctk.CTkFrame(body, fg_color="transparent")
        self.actions.pack(fill="x", pady=(10, 0))

    def bind_actions(self, copy_command: Callable[[], None],
                     on_select: Callable[[str], None] | None = None) -> None:
        ctk.CTkButton(self.actions, text="复制这个地址", height=34, corner_radius=8,
                      fg_color=ui_theme.SLATE, hover_color=ui_theme.SLATE_DARK,
                      text_color=ui_theme.TEXT,
                      font=ctk.CTkFont(family=ui_theme.FONT, size=12),
                      command=copy_command, cursor="hand2").pack(side="left", fill="x", expand=True)
        ctk.CTkButton(self.actions, text="关闭", height=34, corner_radius=8,
                      fg_color="transparent", border_width=1, border_color=ui_theme.BORDER,
                      hover_color=ui_theme.CARD2, text_color=ui_theme.DIM,
                      font=ctk.CTkFont(family=ui_theme.FONT, size=12),
                      command=self.close, cursor="hand2").pack(side="left", padx=(10, 0))
        if on_select is not None:
            self.picker.configure(command=on_select)


class LogOverlay(_PopLayer):
    """全屏日志：镜像主日志框的内容，跟随/打码/截断都由主框先做一遍。"""

    def __init__(self, master, *, limit: int, on_close=None) -> None:
        width, height = ui_theme.OVERLAY_LOG
        # 浮层不该比主窗还大：主窗窄时按主窗留 24 逻辑像素边距收窄，
        # 否则「展开全屏」会挂在窗口外面，看起来像另一个应用的窗口。
        try:
            scale = master._get_window_scaling()
            avail_w = int(master.winfo_width() / scale) - 24
            avail_h = int(master.winfo_height() / scale) - 24
            width = max(420, min(width, avail_w))
            height = max(320, min(height, avail_h))
        except Exception:      # noqa: BLE001 - 控件替身/未布局
            pass
        super().__init__(master, width=width, height=height, on_close=on_close)
        body = overlay_header(self, "运行日志", "与主界面同一份内容 · 最多 %d 行" % limit)
        self._limit = int(limit)
        self.textbox = ctk.CTkTextbox(
            body, fg_color=ui_theme.PANEL_DEEP, text_color=ui_theme.LOG_TEXT,
                      corner_radius=10,
            border_width=1, border_color=ui_theme.BORDER, wrap="word",
            font=ctk.CTkFont(family=ui_theme.MONO, size=12), state="disabled")
        self.textbox.pack(fill="both", expand=True)
        ctk.CTkButton(body, text="收起（Esc）", height=32, corner_radius=8,
                      fg_color=ui_theme.SLATE, hover_color=ui_theme.SLATE_DARK,
                      text_color=ui_theme.TEXT, font=ctk.CTkFont(family=ui_theme.FONT, size=12),
                      command=self.close, cursor="hand2").pack(anchor="e", pady=(10, 0))
        self.line_count = 0

    def fill(self, text: str) -> None:
        """整体替换：调用方已经把内容打码并截断过一次，这里只做长度保险。"""
        try:
            self.textbox.configure(state="normal")
            self.textbox.delete("1.0", "end")
            if text:
                self.textbox.insert("1.0", text + "\n")
            trim_textbox(self.textbox, self._limit)
            self.textbox.configure(state="disabled")
            self.line_count = int(str(self.textbox.index("end-1c")).split(".")[0])
        except Exception:
            return

    def follow(self) -> None:
        """贴到末尾，再把上沿对齐到行首：只做 yview_moveto(1.0) 会让第一行只露下半截。"""
        try:
            self.textbox.yview_moveto(1.0)
        except Exception:
            return
        snap_to_line(self.textbox)
        # 首次显示时行高还没量出来（dlineinfo 返回空），窗口画完再对一次。
        try:
            self.textbox.after(80, lambda: snap_to_line(self.textbox))
        except Exception:  # noqa: BLE001 - 已销毁
            pass
