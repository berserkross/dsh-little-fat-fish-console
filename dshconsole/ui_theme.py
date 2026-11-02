"""界面主题（批次 D「大环 + 抽屉」）：配色、尺寸、五态样式集中一处。

这里只有「长什么样」：点下去做什么仍在 dsh_gui。所以本模块没有副作用，也不碰探测层，
只从 status 取五个阶段当字典键 —— 改主题不该改行为。
"""
from __future__ import annotations

from dataclasses import dataclass

from . import status

# ---------------- 配色（DeepSeek 蓝主基调，与批次 C 一致） ----------------
PRIMARY = "#4D6BFE"        # DeepSeek 品牌蓝
PRIMARY_HOVER = "#3A55E0"
CYAN = "#35D5F4"           # 启动中
GREEN = "#2BB673"          # 运行中
GREEN_DARK = "#1E8F5B"
RED = "#F0526B"            # 破坏性操作（停止 / 退出）
RED_DARK = "#C93A52"
AMBER = "#F59E0B"          # 异常（端口被占用）
AMBER_DARK = "#C97C08"
GREY = "#7A88A8"           # 未运行：中性灰。正常停机不是报警，不用红
GREY_DARK = "#5C6B8E"
VIOLET = "#8B5CF6"
VIOLET_DARK = "#6F43D8"
TEAL = "#14B8A6"
TEAL_DARK = "#0D9488"
SLATE = "#44527A"
SLATE_DARK = "#34405E"
BG = "#070C1A"             # 窗口底色
CARD = "#0E1830"           # 卡片
CARD2 = "#152242"          # 次级卡片 / 悬停
BORDER = "#1D2B4F"
TEXT = "#E6EDF8"
DIM = "#8A97B8"
FAINT = "#5C6B8E"
WHITE_PANEL = "#FFFFFF"    # 二维码底板：必须纯白，扫码才稳

FONT = "Microsoft YaHei UI"
MONO = "Consolas"

# ---------------- 尺寸 ----------------
RING_SIZE = 120            # 顶部状态环直径（px）
RING_THICKNESS = 10
LOG_ROWS_COLLAPSED = 15    # 日志默认只露末尾 15 行，剩下的去「展开全屏」看
LOG_LINE_PX = 18           # 一行等宽字的行高（px）：折叠高度 = 行数 * 这个值
DRAWER_WIDTH = 236         # 「⋯」抽屉宽度
DRAWER_ROW_HEIGHT = 32
OVERLAY_QR = (440, 560)    # 二维码浮层尺寸（比主窗口矮一截，四边都留余量）
OVERLAY_LOG = (980, 620)   # 全屏日志尺寸


@dataclass(frozen=True)
class PhaseStyle:
    """一个阶段的视觉表达：颜色 + 环扫过比例 + 文字前的小标记。

    环颜色之外必须有文字：灰度截图与色弱用户只能靠字分辨五态。
    """

    color: str
    sweep: float           # 前程环扫过的比例，1.0 = 整圈
    dot: str


# 未运行 / 未知用「没走满的环」表达：环的完整度也是信息，不只是颜色。
PHASE_STYLE: dict[status.Phase, PhaseStyle] = {
    status.Phase.STOPPED: PhaseStyle(GREY, 1.0, "○"),
    status.Phase.STARTING: PhaseStyle(CYAN, 0.30, "◔"),
    status.Phase.RUNNING: PhaseStyle(GREEN, 1.0, "●"),
    status.Phase.DEGRADED: PhaseStyle(AMBER, 1.0, "◐"),
    status.Phase.UNKNOWN: PhaseStyle(FAINT, 0.66, "？"),
}

# 环内只能放下 2-4 个字：五态各有短词，全称留给右侧那行说明。
# 两者都来自 status.Phase.label，短词只是它的缩写，不会漂移成另一套词表。
PHASE_WORD: dict[status.Phase, str] = {
    status.Phase.STOPPED: "未运行",
    status.Phase.STARTING: "启动中",
    status.Phase.RUNNING: "运行中",
    status.Phase.DEGRADED: "异常",
    status.Phase.UNKNOWN: "未知",
}
