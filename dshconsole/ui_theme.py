"""界面主题（批次 E「无环单列信息流」）：配色、尺寸、五态样式集中一处。

这里只有「长什么样」：点下去做什么仍在 dsh_gui。所以本模块没有副作用，也不碰探测层，
只从 status 取五个阶段当字典键 —— 改主题不该改行为。

视觉规范（dark SaaS 方向）：近黑画布 + 逐级提亮的炭黑面板承载层级，分隔只用 1px
hairline，全界面只有一个强调色（DeepSeek 蓝）且只出现在主操作与焦点上；信息由文字
承担，颜色只是辅助（灰度截图与色弱用户必须仍能分辨五态）。
"""
from __future__ import annotations

from dataclasses import dataclass

from . import status

# ---------------- 配色 ----------------
# 层级靠表面色，不靠边框与阴影：BG → CARD → CARD2 → CARD3 逐级提亮。
BG = "#08090B"             # 窗口画布（近黑，不是纯黑：纯黑会把界面压闷）
CARD = "#0F1012"           # 面板 / 卡片
CARD2 = "#17181B"          # 面板内的次级控件（按钮底）
CARD3 = "#1F2125"          # 悬停 / 按下
BORDER = "#23252A"         # hairline：卡片的 1px 描边与分隔
BORDER_STRONG = "#34343A"  # 次要按钮的描边（要能被看见才像按钮）
TEXT = "#F7F8F8"           # 主文字
DIM = "#A6ADB7"            # 次级文字（说明、详情）
FAINT = "#6E747C"          # 弱化文字（分组标题、页脚、占位）
LOG_TEXT = "#C3CBD6"       # 日志正文：比主文字弱一档，长时间盯着不刺眼

# 唯一强调色：DeepSeek 品牌蓝。只给主操作与焦点环，不做装饰性点缀。
PRIMARY = "#4D6BFE"
PRIMARY_HOVER = "#6D86FF"

# 语义色：状态灯与破坏性操作。只做前景色，不铺背景色块。
GREEN = "#34C77B"          # 运行中
GREEN_DARK = "#28A263"
RED = "#E5484D"            # 破坏性操作（停止 / 退出）
RED_DARK = "#C43A3F"
AMBER = "#E5B454"          # 异常（端口被占用）
AMBER_DARK = "#C0923A"
GREY = "#8A8F98"           # 未运行：中性灰。正常停机不是报警，不用红
GREY_DARK = "#6E747C"
SLATE = "#5A6B8C"          # 未知 / 次要面板按钮
SLATE_DARK = "#44527A"
CYAN = "#5AC8FA"           # 启动中
WHITE_PANEL = "#FFFFFF"    # 二维码底板：必须纯白，扫码才稳

FONT = "Microsoft YaHei UI"
MONO = "Consolas"

# ---------------- 尺寸 ----------------
# customtkinter 会按窗口缩放放大控件尺寸（150% DPI 下 ×1.5），这里的数字是放大前的
# 逻辑像素；pack/grid 的 padx/pady 是原生 Tk 像素、不缩放，所以外壳留白按小值给。
WINDOW_SIZE = (700, 640)   # 默认窗口：150% 下 1050x960 视口像素，1600 高的屏幕放得下
WINDOW_MIN = (600, 580)    # 再矮日志就只剩几行了
PAD = 12                   # 外壳留白
GAP = 8                    # 面板之间的竖向间隙
STATUS_BAR_H = 44          # 顶部状态条
STATUS_LAMP = 10           # 状态灯直径（小圆点，不再是 120px 大环）
ACTION_H = 38              # 主操作行高度
SLOT_W = 250               # 条件按钮槽宽：「改为控制运行中的实例（PID 41544）」放得下
GRID_BTN_H = 28            # 功能网格里每颗按钮的高度
GRID_PAD = 3               # 按钮之间的竖向间隙
COLUMNS_3_MIN = 660        # 可用宽度 ≥ 这个排 3 列（默认窗口就落在 3 列）
COLUMNS_2_MIN = 480        # 再窄排 2 列，最窄排 1 列
LOG_ROWS_COLLAPSED = 15    # 日志常驻区默认露出的行数（下限，窗口更高就多露）
LOG_LINE_PX = 16           # 一行等宽字的行高：常驻高度 = 行数 * 这个值
OVERLAY_QR = (440, 560)    # 二维码浮层尺寸
OVERLAY_LOG = (980, 620)   # 全屏日志尺寸


def grid_columns(width: float) -> int:
    """功能网格按可用宽度排几列：3 → 2 → 1，永远 ≥ 1（不留空网格）。"""
    if width >= COLUMNS_3_MIN:
        return 3
    if width >= COLUMNS_2_MIN:
        return 2
    return 1


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
