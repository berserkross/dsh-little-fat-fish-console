"""界面主题与主操作映射（批次 E）：只验「长什么样、点哪颗」，不建窗口。"""
import unittest

from dshconsole import status, ui_theme

PHASES = (status.Phase.STOPPED, status.Phase.STARTING, status.Phase.RUNNING,
          status.Phase.DEGRADED, status.Phase.UNKNOWN)


class PhaseStyleTests(unittest.TestCase):
    def test_every_phase_has_a_style(self):
        self.assertEqual(set(ui_theme.PHASE_STYLE), set(PHASES))

    def test_colors_are_pairwise_distinct(self):
        colors = [ui_theme.PHASE_STYLE[p].color for p in PHASES]
        self.assertEqual(len(set(colors)), len(PHASES), colors)

    def test_each_phase_carries_a_text_marker(self):
        """不能只靠颜色区分五态：灰度截图和色弱用户只能看字/形状。"""
        words = [ui_theme.PHASE_WORD[p] for p in PHASES]
        self.assertEqual(len(set(words)), len(PHASES), words)
        self.assertTrue(all(word.strip() for word in words))

    def test_sweep_is_a_ratio(self):
        for phase in PHASES:
            sweep = ui_theme.PHASE_STYLE[phase].sweep
            self.assertGreater(sweep, 0.0, phase)
            self.assertLessEqual(sweep, 1.0, phase)
        # 启动中 / 未知是「没走满的灯」：弧长本身也是信息
        self.assertLess(ui_theme.PHASE_STYLE[status.Phase.STARTING].sweep, 1.0)
        self.assertLess(ui_theme.PHASE_STYLE[status.Phase.UNKNOWN].sweep, 1.0)

    def test_phase_labels_are_distinct_short_words(self):
        labels = [phase.label for phase in PHASES]
        self.assertEqual(len(set(labels)), len(PHASES), labels)
        self.assertTrue(all(label.strip() for label in labels))

    def test_style_is_immutable(self):
        style = ui_theme.PHASE_STYLE[status.Phase.RUNNING]
        with self.assertRaises(Exception):
            style.color = "#000000"      # type: ignore[misc]


class SizeConstantTests(unittest.TestCase):
    def test_status_lamp_is_a_small_dot(self):
        """批次 E 把 107px 的大环换成小圆点：它必须比状态条矮得多。"""
        self.assertGreater(ui_theme.STATUS_LAMP, 0)
        self.assertLessEqual(ui_theme.STATUS_LAMP, 16)
        self.assertGreater(ui_theme.STATUS_BAR_H, ui_theme.STATUS_LAMP * 2)

    def test_empty_log_floor_fits_the_avatar(self):
        """空态下限要放得下 HERO_SIZE 的圆形头像；有字就回落到 log_rows() 的规则。"""
        self.assertGreaterEqual(ui_theme.LOG_ROWS_EMPTY, ui_theme.LOG_ROWS_MIN)
        self.assertLessEqual(ui_theme.LOG_ROWS_EMPTY, ui_theme.LOG_ROWS_MAX)
        self.assertGreaterEqual(ui_theme.log_rows_with_empty(0, 10 ** 6) * ui_theme.LOG_LINE_PX,
                                ui_theme.HERO_SIZE)
        self.assertEqual(ui_theme.log_rows_with_empty(9, 10 ** 6), 9)
        self.assertEqual(ui_theme.log_rows_with_empty(0, ui_theme.LOG_LINE_PX),
                         ui_theme.LOG_ROWS_MIN)

    def test_log_rows_are_content_driven(self):
        """日志区高度跟着内容长：下限 5~6 行、上限有顶，中间按行数走。"""
        self.assertGreaterEqual(ui_theme.LOG_ROWS_MIN, 5)
        self.assertLessEqual(ui_theme.LOG_ROWS_MIN, 6)
        self.assertGreater(ui_theme.LOG_ROWS_MAX, ui_theme.LOG_ROWS_MIN)
        self.assertGreater(ui_theme.LOG_LINE_PX, 0)
        self.assertEqual(ui_theme.log_rows(0, 10 ** 6), ui_theme.LOG_ROWS_MIN)
        self.assertEqual(ui_theme.log_rows(ui_theme.LOG_ROWS_MIN + 2, 10 ** 6),
                         ui_theme.LOG_ROWS_MIN + 2)
        self.assertEqual(ui_theme.log_rows(10 ** 6, 10 ** 6), ui_theme.LOG_ROWS_MAX)
        # 窗口矮的时候不许硬撑：可用像素也参与钳制
        self.assertEqual(ui_theme.log_rows(10 ** 6, ui_theme.LOG_LINE_PX), ui_theme.LOG_ROWS_MIN)

    def test_header_and_empty_state_sizes(self):
        """头部 64px 的 ico 头像；上下各留 ≥8 逻辑像素，圆才不会被父框裁掉。"""
        self.assertGreaterEqual(ui_theme.BADGE_SIZE, 56)
        self.assertLessEqual(ui_theme.BADGE_SIZE, 72)
        self.assertGreaterEqual(ui_theme.HEADER_H - ui_theme.BADGE_SIZE, 16)
        self.assertGreater(ui_theme.HERO_SIZE, ui_theme.BADGE_SIZE * 2)
        self.assertTrue(ui_theme.EMPTY_LOG_HINT.strip())

    def test_overlay_sizes_are_positive(self):
        for width, height in (ui_theme.OVERLAY_QR, ui_theme.OVERLAY_LOG):
            self.assertGreater(width, 0)
            self.assertGreater(height, 0)

    def test_ring_and_drawer_constants_are_gone(self):
        """大环和抽屉都删了，留着常量就会被下一个改动悄悄用回去。"""
        for name in ("RING_SIZE", "RING_THICKNESS", "DRAWER_WIDTH", "DRAWER_ROW_HEIGHT"):
            self.assertFalse(hasattr(ui_theme, name), name)

    def test_grid_columns_breakpoints(self):
        self.assertEqual(ui_theme.grid_columns(ui_theme.COLUMNS_3_MIN), 3)
        self.assertEqual(ui_theme.grid_columns(ui_theme.COLUMNS_3_MIN - 1), 2)
        self.assertEqual(ui_theme.grid_columns(ui_theme.COLUMNS_2_MIN), 2)
        self.assertEqual(ui_theme.grid_columns(ui_theme.COLUMNS_2_MIN - 1), 1)
        self.assertEqual(ui_theme.grid_columns(0), 1)
        # 默认窗口宽度就得是 3 列：功能网格一开窗就是全展开的样子
        self.assertEqual(ui_theme.grid_columns(ui_theme.WINDOW_SIZE[0]), 3)

    def test_tokens_the_frozen_qr_overlay_needs_still_exist(self):
        """QrOverlay 是禁改件：它引用的 token 少一个就让整个手机访问浮层打不开。"""
        for name in ("CARD", "CARD2", "BORDER", "TEXT", "DIM", "SLATE", "SLATE_DARK",
                     "WHITE_PANEL", "FONT", "MONO", "OVERLAY_QR"):
            self.assertTrue(hasattr(ui_theme, name), name)

    def test_window_min_fits_inside_the_default_window(self):
        self.assertLessEqual(ui_theme.WINDOW_MIN[0], ui_theme.WINDOW_SIZE[0])
        self.assertLessEqual(ui_theme.WINDOW_MIN[1], ui_theme.WINDOW_SIZE[1])


class GlassTokenTests(unittest.TestCase):
    """玻璃板参数：半透明只活在渲染图里，装饰必须淡到不抢字。"""

    def test_glass_tokens_are_rgba(self):
        for name in ("GLASS_TINT", "GLASS_EDGE", "GLASS_HIGHLIGHT", "GLASS_SHADOW",
                     "GLOW", "GRID_LINE", "STAR_DOT"):
            token = getattr(ui_theme, name)
            self.assertEqual(len(token), 4, name)
            self.assertTrue(all(0 <= int(v) <= 255 for v in token), name)

    def test_substrate_decor_is_faint(self):
        """网格与星点只是衬底：不透明度都不许超过 40/255（约 16%）。"""
        self.assertLessEqual(ui_theme.GRID_LINE[3], 40)
        self.assertLessEqual(ui_theme.STAR_DOT[3], 40)
        self.assertGreater(ui_theme.PANEL_RIM, 0)

    def test_window_is_fully_opaque(self):
        """整窗必须 alpha=1.0：玻璃靠画出来的渐变/卡面/亮边/柔影，不靠桌面透射。"""
        self.assertEqual(ui_theme.WINDOW_ALPHA, 1.0)

    def test_card_fill_is_near_solid(self):
        """卡面等效不透明度 ≥0.92：桌面字形不能从面板内部透出来。"""
        self.assertGreaterEqual(ui_theme.CARD_FILL_ALPHA / 255.0, 0.92)

    def test_window_gradient_is_visible(self):
        """竖向渐变要看得出来，柔影要有偏移，否则「玻璃感」就退回一块纯色。"""
        top, bottom = ui_theme.GLASS_GRAD_TOP, ui_theme.GLASS_GRAD_BOTTOM
        self.assertGreater(sum(top) - sum(bottom), 40)
        self.assertGreater(ui_theme.GLASS_SHADOW_OFFSET, 0)
        self.assertGreater(ui_theme.GLASS_SHADOW[3], 100)

    def test_contrast_ratios_clear_wcag_aa(self):
        """正文类文字 ≥ 4.5:1。改配色先跑这条，观感不许压过可读性。"""
        pairs = [(ui_theme.LOG_TEXT, ui_theme.PANEL_DEEP),
                 (ui_theme.TEXT, ui_theme.CARD),
                 (ui_theme.TEXT, ui_theme.CHIP),
                 (ui_theme.TEXT, ui_theme.CHIP_HOVER),
                 (ui_theme.DIM, ui_theme.CARD),
                 (ui_theme.FAINT, ui_theme.CARD),
                 ("#FFFFFF", ui_theme.PRIMARY),
                 ("#FFFFFF", ui_theme.PRIMARY_HOVER)]
        for fore, back in pairs:
            self.assertGreaterEqual(ui_theme.contrast_ratio(fore, back), 4.5,
                                    f"{fore} on {back}")

    def test_contrast_helper_is_symmetric_and_sane(self):
        self.assertAlmostEqual(ui_theme.contrast_ratio("#FFFFFF", "#000000"), 21.0, places=1)
        self.assertAlmostEqual(ui_theme.contrast_ratio("#000000", "#FFFFFF"), 21.0, places=1)
        self.assertAlmostEqual(ui_theme.contrast_ratio("#123456", "#123456"), 1.0, places=2)


class GlassRenderTests(unittest.TestCase):
    """渲染层的行为：白底（=桌面）不许透过卡面，渐变与柔影要真的画出来。"""

    def test_gradient_darkens_downwards(self):
        from dshconsole import widgets as w
        img = w._gradient(200, 160)
        top = sum(img.getpixel((100, 6))[:3])
        bottom = sum(img.getpixel((100, 154))[:3])
        self.assertGreater(top - bottom, 30, (top, bottom))

    def test_panel_hides_a_white_substrate(self):
        """白底垫在卡面后面：卡内像素必须被压暗，不能留白（=桌面内容透出来）。"""
        from PIL import Image
        from dshconsole import widgets as w
        img = Image.new("RGBA", (200, 160), (255, 255, 255, 255))
        samples = w.GlassBackdrop._compose_panels(
            None, img, [("p", "panel", 20, 20, 160, 120, 14)], 1.0)
        px = img.convert("RGB").getpixel((100, 80))
        self.assertLess(max(px), 120, px)
        self.assertIn("p", samples)
        self.assertTrue(samples["p"].startswith("#"), samples["p"])

    def test_shadow_lands_below_the_panel(self):
        """柔影下移：卡面正下方要比正上方暗（影在下、光在上）。"""
        from PIL import Image
        from dshconsole import widgets as w
        img = Image.new("RGBA", (240, 220), (60, 78, 118, 255))
        w.GlassBackdrop._compose_panels(None, img,
                                        [("p", "panel", 40, 50, 160, 100, 14)], 1.0)
        rgb = img.convert("RGB")
        below = sum(rgb.getpixel((120, 158))[:3])
        above = sum(rgb.getpixel((120, 44))[:3])
        self.assertLess(below, above, (below, above))


class AvatarAssetTests(unittest.TestCase):
    """ico 头像：圆形裁切（圆外透明）+ 窗口图标 ico 优先。"""

    def setUp(self):
        from dshconsole import widgets as w
        self.w = w
        icon = w.resources.icon_path()
        if icon is None or not icon.is_file():
            self.skipTest("仓库里没有 .ico")
        self.icon = icon

    def test_cut_uses_the_documented_circle(self):
        w = self.w
        self.assertEqual(w.AVATAR_CENTER, (136, 130))
        self.assertEqual(w.AVATAR_RADIUS, 112)
        cut = w.avatar(96)
        self.assertIsNotNone(cut)
        self.assertEqual(cut.size, (96, 96))
        alpha = cut.getchannel("A")
        # 四个角全透明 = 出血裁切的硬切口没有露出来
        for corner in ((0, 0), (95, 0), (0, 95), (95, 95)):
            self.assertEqual(alpha.getpixel(corner), 0, corner)
        self.assertGreater(alpha.getpixel((48, 48)), 200)

    def test_badge_is_transparent_outside_the_disc(self):
        img = self.w.badge(96, ui_theme.CARD)
        self.assertEqual(img.size, (96, 96))
        self.assertEqual(img.getpixel((0, 0))[3], 0)

    def test_hero_picture_shares_the_avatar(self):
        img = self.w.hero_picture(140, ui_theme.PANEL_DEEP)
        self.assertEqual(img.size, (140, 140))
        self.assertEqual(img.getpixel((0, 0))[3], 0)

    def test_window_icon_prefers_the_ico(self):
        w = self.w
        calls = []

        class Win:
            def iconbitmap(self, *args, **kwargs):
                calls.append("ico")

            def iconphoto(self, *args, **kwargs):
                calls.append("png")

        self.assertTrue(w.apply_window_icon(Win()))
        self.assertEqual(calls[:1], ["ico"], calls)


class AssetFallbackTests(unittest.TestCase):
    """素材缺失必须优雅回退：不许抛异常，也不许返回空白图。"""

    def test_art_loader_tolerates_missing_art(self):
        from dshconsole import widgets as w
        for role in w.ART_FILES:
            got = w.art_image(role)        # 有图是 Path，没图是 None，两者都合法
            self.assertTrue(got is None or hasattr(got, "is_file"), role)

    def test_vector_fallbacks_paint_something(self):
        from dshconsole import widgets as w
        for image in (w.mascot("idle", 72, ui_theme.CARD),
                      w.badge(52, ui_theme.CARD),
                      w.hero_picture(132, ui_theme.PANEL_DEEP),
                      w._whale(48, ui_theme.CARD)):
            self.assertEqual(image.size, image.size)          # 是 PIL 图
            self.assertGreater(image.size[0], 0)
            alpha = image.convert("RGBA").getchannel("A")
            self.assertGreater(alpha.getextrema()[1], 0, "回退图整张全透明 = 白块")

    def test_blend_returns_hex(self):
        from dshconsole import widgets as w
        self.assertEqual(w.blend("#FFFFFF", "#000000", 0.5), "#808080")
        self.assertEqual(w.blend(ui_theme.PRIMARY_GLOW, ui_theme.CARD, 0.5), "#30449B")


class PrimaryActionTests(unittest.TestCase):
    """一屏一颗主按钮：文案随状态变，点下去仍走原来那颗回调。"""

    def setUp(self):
        try:
            import dsh_gui
        except Exception as exc:      # noqa: BLE001 - 缺 GUI 依赖时跳过
            raise unittest.SkipTest("无法导入 GUI：" + str(exc))
        self.gui = dsh_gui

    def test_labels_follow_the_five_phases(self):
        got = {p: self.gui.primary_action(p)[:2] for p in PHASES}
        self.assertEqual(got[status.Phase.STOPPED], ("启动 DSH", "start"))
        self.assertEqual(got[status.Phase.STARTING], ("停止 DSH", "stop"))
        self.assertEqual(got[status.Phase.RUNNING], ("停止 DSH", "stop"))
        self.assertEqual(got[status.Phase.DEGRADED], ("修复/重启", "restart"))
        self.assertEqual(got[status.Phase.UNKNOWN], ("重新探测", "refresh"))

    def test_callback_name_exists_on_the_app(self):
        app = self.gui.ConsoleApp
        for phase in PHASES:
            _label, name, _color, _hover = self.gui.primary_action(phase)
            self.assertTrue(hasattr(app, "on_" + name), name)

    def test_colors_come_from_the_theme(self):
        allowed = {ui_theme.PRIMARY, ui_theme.AMBER, ui_theme.SLATE, ui_theme.RED}
        for phase in PHASES:
            self.assertIn(self.gui.primary_action(phase)[2], allowed, phase)


if __name__ == "__main__":
    unittest.main()
