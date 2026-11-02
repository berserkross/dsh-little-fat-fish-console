r"""按钮网格的测量表（批次 G）：同一列 chip 的 x0/x1 必须一致，列宽一致，末项通栏。

输出（两种列数各一份）：
  %TEMP%\ui_v4\chip-grid-3col.md / .csv   默认 960x700（3 列）
  %TEMP%\ui_v4\chip-grid-2col.md / .csv   640x900（2 列，第三组独占一整行）
判定：
  1. 同组同列：x0 与 x1 的极差 ≤1 设备像素（任何列数都要成立）；
  2. 跨组同列：列宽极差 ≤1 设备像素（只在三组同一行、即 3 列时要求，2 列时第三组整行通栏）；
  3. 末行只剩一项：该 chip 的 x0 = 首列 x0、x1 = 末列 x1（±1），即通栏；
  4. 手机访问组 5 项：2+2+1。

用法：py -3.11 tests\measure_chips.py
"""
from __future__ import annotations

import csv
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import dsh_gui                        # noqa: E402
from dshconsole import status         # noqa: E402

OUT = Path(os.environ.get("TEMP", ".")) / "ui_v4"
TOL = 1
CASES = (("3col", "960x700", True), ("2col", "640x900", False))


def settle(app, seconds: float = 0.9) -> None:
    end = time.time() + seconds
    while time.time() < end:
        app.update()
        time.sleep(0.02)


def measure(app):
    rows = []
    for group_index, (title, entries) in enumerate(dsh_gui.ACTION_GROUPS):
        card = app._groups[group_index]
        ox, oy = card.winfo_rootx(), card.winfo_rooty()
        for _icon, text, name in entries:
            button = app._group_buttons[name]
            info = button.grid_info()
            x0 = button.winfo_rootx() - ox
            y0 = button.winfo_rooty() - oy
            rows.append({
                "组": title, "行": int(info["row"]) - 1, "列": int(info["column"]),
                "跨列": int(info["columnspan"]), "文案": text,
                "x0": x0, "x1": x0 + button.winfo_width() - 1,
                "宽": button.winfo_width(), "高": button.winfo_height(), "y0": y0,
            })
    return rows


def table(rows) -> str:
    lines = ["| 组 | 行 | 列 | 跨列 | 文案 | x0 | x1 | 宽 | 高 |",
             "|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        lines.append("| %s | %d | %d | %d | %s | %d | %d | %d | %d |" % (
            r["组"], r["行"], r["列"], r["跨列"], r["文案"], r["x0"], r["x1"],
            r["宽"], r["高"]))
    return "\n".join(lines)


def check(rows, same_row: bool) -> list[str]:
    fails = []
    for title, _entries in dsh_gui.ACTION_GROUPS:
        by_col = {}
        for r in rows:
            if r["组"] == title and r["跨列"] == 1:
                by_col.setdefault(r["列"], []).append(r)
        for col, items in sorted(by_col.items()):
            x0s = [i["x0"] for i in items]
            x1s = [i["x1"] for i in items]
            if max(x0s) - min(x0s) > TOL or max(x1s) - min(x1s) > TOL:
                fails.append("%s 列%d 未对齐 x0=%s x1=%s" % (title, col, x0s, x1s))

    if same_row:
        for col in (0, 1):
            vals = {}
            for title, _e in dsh_gui.ACTION_GROUPS:
                got = [r["宽"] for r in rows
                       if r["组"] == title and r["列"] == col and r["跨列"] == 1]
                if got:
                    vals[title] = got[0]
            if len(vals) > 1 and max(vals.values()) - min(vals.values()) > TOL:
                fails.append("列%d 跨组列宽不一致 %s" % (col, vals))

    for title, _entries in dsh_gui.ACTION_GROUPS:
        mine = [r for r in rows if r["组"] == title]
        first_row = min(r["行"] for r in mine)
        last_row = max(r["行"] for r in mine)
        two_col = [r for r in mine if r["行"] == first_row]
        if len(two_col) < 2 or last_row == first_row:
            continue
        left, right = two_col[0], two_col[-1]
        tail = [r for r in mine if r["行"] == last_row]
        if len(tail) == 1:
            item = tail[0]
            if (abs(item["x0"] - left["x0"]) > TOL
                    or abs(item["x1"] - right["x1"]) > TOL):
                fails.append("%s 末项未通栏：x0=%d x1=%d 应为 %d..%d"
                             % (title, item["x0"], item["x1"], left["x0"], right["x1"]))

    phone = [r for r in rows if r["组"] == "手机访问"]
    shape = {}
    for r in phone:
        shape[r["行"]] = shape.get(r["行"], 0) + 1
    if [shape[k] for k in sorted(shape)] != [2, 2, 1]:
        fails.append("手机访问组排布不是 2+2+1：%s" % shape)
    return fails


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    all_fails = []
    for tag, geometry, same_row in CASES:
        app = dsh_gui.ConsoleApp()
        app._status_provider = lambda **kw: status.Status(
            phase=status.Phase.STOPPED, pids=[], port_open=False, phone_open=False,
            ts_ip=None, lan_ips=None, notes=[])
        app._pids_provider = lambda: ([], None)
        app._port_open = lambda: False
        app._snapshot.invalidate()
        app.geometry(geometry)
        settle(app)

        rows = measure(app)
        head = "## %s（窗口 %s，组卡列数 %d，设备像素 @150%%）" % (
            tag, geometry, 3 if same_row else 2)
        text = head + "\n\n" + table(rows) + "\n"
        (OUT / ("chip-grid-%s.md" % tag)).write_text(text, encoding="utf-8")
        with (OUT / ("chip-grid-%s.csv" % tag)).open("w", newline="", encoding="utf-8-sig") as fh:
            writer = csv.DictWriter(fh, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
        print(text)

        fails = check(rows, same_row)
        print("  %s：%s" % (tag, "OK" if not fails else "FAILED %d" % len(fails)))
        for item in fails:
            print("    - " + item)
        all_fails.extend("%s: %s" % (tag, f) for f in fails)

        app.after(120, app.destroy)
        app.mainloop()

    print()
    if all_fails:
        print("MEASURE FAILED (%d)" % len(all_fails))
        return 1
    print("MEASURE OK：同列对齐、三组等宽、末项通栏、手机组 2+2+1（3 列与 2 列两种）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
