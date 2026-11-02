"""界面主题（批次 G「绘制玻璃」）：配色、尺寸、五态样式，以及对比度换算。

这里只有「长什么样」：点下去做什么仍在 dsh_gui。所以本模块没有副作用，也不碰探测层，
只从 status 取五个阶段当字典键 —— 改主题不该改行为。

视觉定位（用户拍板）：轻科幻 + 可爱 + 蓝主色 + 绘制出来的暗色玻璃。
「玻璃」是画出来的，不是真的透：整窗 alpha=1.0，桌面不参与成像，通透感来自衬底渐变 +
近实心卡面 + 亮边 + 柔影这四层，而不是让桌面内容穿透进来（第二轮返工的核心结论）。
配色分三层：
  1. 渲染层（widgets.GlassBackdrop 用 Pillow 画）：竖向深色渐变 + <=6% 的网格与星点；
  2. 面板层：CARD 是「玻璃板取样色」—— 渲染图上面板内部就是这个值，控件叠上去无缝；
  3. 控件层：CHIP 比面板亮一档（按钮必须看得出是按钮，不是输入框），TEXT 三级灰度。
全界面只有一个强调色（DeepSeek 蓝），并且分成两个用途：PRIMARY 是按钮底色（要配白字，
所以比品牌蓝深一点，凑够 4.5:1），PRIMARY_GLOW 只做光晕，永不承载文字。
"""
from __future__ import annotations

from dataclasses import dataclass

from . import status

# ---------------- 配色 ----------------
BG = "#070B18"             # 窗口兜底底色（渲染图没铺上时露出的颜色）
CARD = "#131E38"           # 玻璃面板：从渲染图取样的设计值
PANEL = CARD               # 同义名：面板层
CARD2 = "#1E2C4D"          # 面板内的次级控件（按钮底）：必须比面板亮一档
CARD3 = "#2A3D68"          # 悬停 / 按下
CHIP = CARD2               # 功能网格里每颗按钮的底色
CHIP_HOVER = CARD3
BORDER = "#2A3A5E"         # hairline：卡片描边与分隔
BORDER_STRONG = "#3D5588"  # 次要按钮的描边（要能被看见才像按钮）
PANEL_DEEP = "#0E1730"     # 日志井：比面板更深一档，长文不刺眼
LOG_BG = PANEL_DEEP
TEXT = "#EAF1FF"           # 主文字
DIM = "#A9BAD8"            # 次级文字（说明、详情）
FAINT = "#8598B8"          # 弱化文字（分组标题、页脚、占位）
LOG_TEXT = "#CBD9EE"       # 日志正文

# 强调色：PRIMARY 是按钮底色（白字 5.63:1），PRIMARY_GLOW 只做光晕。
PRIMARY = "#3D57E8"
PRIMARY_HOVER = "#4A66F2"   # 悬停变亮，白字仍 4.69:1
PRIMARY_GLOW = "#4D6BFE"    # DeepSeek 品牌蓝：只进光晕，不承载文字

# 语义色：只做前景色与灯，不铺大面积背景（背景一铺，对比度就靠猜了）。
GREEN = "#54E39C"          # 运行中
GREEN_DARK = "#3BC983"
RED = "#FF7B7F"            # 破坏性操作（停止 / 退出）
RED_DARK = "#E5676B"
AMBER = "#FFC168"          # 异常（端口被占用）
AMBER_DARK = "#E5A84F"
GREY = "#C6D2E4"           # 未运行：亮灰，正常停机不是报警
GREY_DARK = "#9AAAC2"
SLATE = "#3A4B78"          # 次要面板按钮（浮层里的「复制 / 收起」）
SLATE_DARK = "#2C3A5F"
CYAN = "#7FD4FF"           # 启动中
WHITE_PANEL = "#FFFFFF"    # 二维码底板：必须纯白，扫码才稳

FONT = "Microsoft YaHei UI"
MONO = "Consolas"

# ---------------- 玻璃渲染层 ----------------
# 渲染图里叠在渐变上的东西，一律用 0~255 的 RGBA 元组；网格与星点压在 6% 以内，
# 否则「装饰」会开始和正文抢注意力。
GLASS_GRAD_TOP = (26, 40, 74)           # 整窗竖向渐变的顶（窗口最亮处）
GLASS_GRAD_MID = (14, 22, 44)           # 中段
GLASS_GRAD_BOTTOM = (5, 8, 18)          # 底（最暗）：顶底差 ~30 级，肉眼能看出是一层渐变
CARD_FILL_ALPHA = 240                   # 卡面填充 240/255 = 0.94，合成后等效不透明度 0.94
GLASS_TINT = (255, 255, 255, 14)        # 卡面内部的补充白（5.5%，让卡面比纯色「有厚度」）
GLASS_EDGE = (150, 190, 255, 96)        # 1px 亮边（约 38%）：玻璃之所以像玻璃就靠这道边
GLASS_HIGHLIGHT = (214, 234, 255, 64)   # 卡面上沿内高光（光从上方来）
GLASS_SHADOW = (0, 0, 0, 140)           # 卡面下方的柔影：比衬底暗 55%，压出悬浮感
GLASS_SHADOW_OFFSET = 6                 # 柔影整体下移的像素（光在上方 → 影在下方）
GLOW = (77, 107, 254, 60)               # 主按钮光晕（品牌蓝，约 24%）
GRID_LINE = (120, 170, 255, 13)         # 衬底网格：5.1%
STAR_DOT = (190, 215, 255, 15)          # 星点：5.9%
AURORA = ((60, 110, 255, 26), (90, 220, 255, 16), (140, 120, 255, 14))
PANEL_RIM = 5                           # 烘焙玻璃框比真实面板外扩的像素

# ---------------- 尺寸 ----------------
# customtkinter 会按窗口缩放放大控件尺寸（150% DPI 下 ×1.5），这里的数字是放大前的
# 逻辑像素；pack/grid 的 padx/pady 是原生 Tk 像素、不缩放，所以外壳留白按小值给。
WINDOW_SIZE = (960, 700)   # 150% 下 1440x1050 视口像素：3 列 × 2 列按钮放得下
WINDOW_MIN = (620, 560)    # 再窄就只能单列，日志也只剩几行
# 整窗不透明：上一轮 0.96 让桌面浏览器的字在卡片/日志/状态行背后都读得出来（实测取样
# (28,39,64) 的面板上叠着可辨认的字形）。玻璃改为「画」出来之后，窗口本身必须全不透明。
WINDOW_ALPHA = 1.0
PAD = 14                   # 外壳留白
GAP = 10                   # 面板之间的间隙
# 头部条 = 徽章 64 + 上下各 12 的逻辑留白：徽章必须完整成圆，上下都不许被父框裁掉
# （上一轮 64 高的头 + rowspan 撑到 68 的行高，把玻璃圆盘的下弧裁掉了）。
HEADER_H = 88
STATUS_BAR_H = HEADER_H    # 兼容旧名
BADGE_SIZE = 64            # 头部圆形头像（ico 圆形裁切）的直径
STATUS_LAMP = 9            # 状态灯直径（发光圆点）
ACTION_H = 46              # 主操作按钮高度
SLOT_W = 260               # 条件按钮槽宽：「改为控制运行中的实例（PID 41544）」放得下
GRID_BTN_H = 36            # 功能网格里每颗按钮的高度
GRID_PAD = 8               # 按钮之间的间隙
CARD_RADIUS = 14           # 玻璃面板圆角
CHIP_RADIUS = 11           # 按钮圆角
PRIMARY_RADIUS = 12
COLUMNS_3_MIN = 660        # 可用宽度 ≥ 这个排 3 列
COLUMNS_2_MIN = 480        # 再窄排 2 列，最窄 1 列
GROUP_SPLIT_MIN = 250      # 单张组卡宽度 ≥ 这个时组内排 2 列按钮
LOG_LINE_PX = 16           # 一行等宽字的行高：日志高度 = 行数 * 这个值
LOG_ROWS_MIN = 6           # 日志区下限：低于 6 行就不像日志了
LOG_ROWS_MAX = 26          # 上限：再高就靠「展开全屏」，常驻区不该吃掉整个窗口
LOG_ROWS_COLLAPSED = 10    # 默认露出的行数（兼容旧名，也是首屏期望值）
# 空态下限：日志没字时这一格要放得下 HERO_SIZE 的圆形头像 + 一行提示（140+8+20 ≈ 168px），
# 6 行只有 96px，会把头像裁掉。有字时立刻回落到 log_rows() 的 6 行起算规则。
LOG_ROWS_EMPTY = 12
OVERLAY_QR = (440, 560)    # 二维码浮层尺寸
OVERLAY_LOG = (980, 620)   # 全屏日志尺寸
HERO_SIZE = 140            # 空态头像（日志为空时的 ico 圆形裁切大图）边长


def grid_columns(width: float) -> int:
    """功能网格按可用宽度排几列：3 → 2 → 1，永远 ≥ 1（不留空网格）。"""
    if width >= COLUMNS_3_MIN:
        return 3
    if width >= COLUMNS_2_MIN:
        return 2
    return 1


def group_columns(card_width: float) -> int:
    """单张组卡内部排几列按钮：2 列是常态，卡片窄到放不下两个字就退回 1 列。"""
    return 2 if card_width >= GROUP_SPLIT_MIN else 1


def log_rows(line_count: int, available_px: int) -> int:
    """常驻日志区露几行：clamp(实际行数, LOG_ROWS_MIN, LOG_ROWS_MAX)。

    上限既受 LOG_ROWS_MAX 管，也受窗口实际剩余像素管 —— 日志永远不许把底栏挤出窗口。
    这是「日志区高度 = 行数」的唯一算法：日志不再吸收剩余高度（剩余高度归组卡那一行）。
    """
    room = int(max(0, available_px) // LOG_LINE_PX)
    want = max(LOG_ROWS_MIN, int(line_count or 0))
    cap = min(LOG_ROWS_MAX, room) if room >= LOG_ROWS_MIN else LOG_ROWS_MIN
    return max(LOG_ROWS_MIN, min(want, cap))


def log_rows_with_empty(line_count: int, available_px: int) -> int:
    """空日志时把这一格抬到能放下圆形头像的高度（LOG_ROWS_EMPTY），有字就回落。

    只影响「日志是不是空的」这一种状态：一行字都没有时 clamp 到 LOG_ROWS_MIN 会只剩
    96px，140px 的头像必然被裁，所以空态的下限单独给到 LOG_ROWS_EMPTY。
    """
    rows = log_rows(line_count, available_px)
    if int(line_count or 0) > 0:
        return rows
    room = int(max(0, available_px) // LOG_LINE_PX)
    cap = min(LOG_ROWS_MAX, room) if room >= LOG_ROWS_MIN else LOG_ROWS_MIN
    return max(rows, min(LOG_ROWS_EMPTY, cap))


# ---------------- 对比度（WCAG 2.1） ----------------
def _channel(value: int) -> float:
    """sRGB 单通道 → 线性值（WCAG 的相对亮度定义）。"""
    c = max(0, min(255, int(value))) / 255.0
    return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4


def relative_luminance(color: str) -> float:
    """#RRGGBB → 相对亮度。给 contrast_ratio 与测试用。"""
    text = color.strip().lstrip("#")
    if len(text) != 6:
        raise ValueError("颜色必须是 #RRGGBB：" + color)
    r, g, b = (int(text[i:i + 2], 16) for i in (0, 2, 4))
    return 0.2126 * _channel(r) + 0.7152 * _channel(g) + 0.0722 * _channel(b)


def contrast_ratio(fore: str, back: str) -> float:
    """两色的对比度（1.0~21.0）。正文类必须 ≥ 4.5:1，大字 ≥ 3:1。"""
    a, b = relative_luminance(fore), relative_luminance(back)
    high, low = max(a, b), min(a, b)
    return (high + 0.05) / (low + 0.05)


@dataclass(frozen=True)
class PhaseStyle:
    """一个阶段的视觉表达：颜色 + 灯的完整度。

    灯的完整度也是信息（启动中没走满），所以五态不能只靠颜色区分 —— 状态条上
    永远并列写着 PHASE_WORD 里的状态词。
    """

    color: str
    sweep: float           # 0.0~1.0：灯的填充比例，1.0 = 实心


PHASE_STYLE: dict[status.Phase, PhaseStyle] = {
    status.Phase.STOPPED: PhaseStyle(GREY, 1.0),
    status.Phase.STARTING: PhaseStyle(CYAN, 0.30),
    status.Phase.RUNNING: PhaseStyle(GREEN, 1.0),
    status.Phase.DEGRADED: PhaseStyle(AMBER, 1.0),
    status.Phase.UNKNOWN: PhaseStyle(FAINT, 0.66),
}

# 状态条一行放得下 2-4 个字：五态各有短词，全称（status.Phase.label，如
# 「异常（端口被占用）」）留在日志与提示里。短词只是全称的缩写，不会漂移成另一套词表。
PHASE_WORD: dict[status.Phase, str] = {
    status.Phase.STOPPED: "未运行",
    status.Phase.STARTING: "启动中",
    status.Phase.RUNNING: "运行中",
    status.Phase.DEGRADED: "异常",
    status.Phase.UNKNOWN: "未知",
}

# 空态提示（日志为空时的那一句话）。放在主题里，测试能断言它没被清空。
EMPTY_LOG_HINT = "还没有日志 —— 启动 DSH 后，这里会滚动显示实时输出"
