#!/usr/bin/env python3
"""Bejeweled 3 识别（numpy 版，PipeWire 90fps 通路专用）。

方法：**逐像素投票 + 饱和优先**（用数据选出来的规则，见 pickrule.py）
  ① 逐像素投票：宝石是 3D 渲染，格心是高光、格边是暗面，任何"取一个代表色"
     的做法（中位数/直方图）都会踩坑。
  ② 饱和优先：高饱和像素投出的色最可信。这点很关键 —— 紫色火焰宝石的火焰
     白光裹在**外圈**，若按"边缘环"或整格投票会被白光带偏成白宝石 ❌；
     而高饱和像素投票得到 P(0.80) ✅（实测确认）。
  ③ 道具不做特殊处理：实测火焰宝石本就该按本色识别（它就是可匹配的紫宝石）；
     金色超立方体读成金色/白也只会轻微高估可走步数，不值得为它引入误报。

判别规则由 pickrule.py 在三组数据上选出：干净棋盘 0 误报。
"""
import json
import numpy as np

BOARD_PATH = "/home/deck/bjbot/board.json"
BOARD = json.load(open(BOARD_PATH))

# 宝石本体色（实测标定，1280x800 + 汉化高清补丁）
REF = {
    "R": (252, 28, 58),
    "P": (185, 6, 185),
    "G": (12, 205, 32),
    "W": (238, 238, 238),
    "O": (250, 110, 20),
    "B": (8, 120, 243),
    "Y": (251, 220, 22),
}
KEYS = list(REF.keys())
REFARR = np.array([REF[k] for k in KEYS], np.float32)
VOTE_MAXDIST = 75.0
MIN_VOTES = 0.30
SAT_MIN = 0.30

def _vote(px, mask):
    """在 mask 选中的像素上投票。返回 (glyph, ratio, n_valid)。"""
    m = mask
    if int(m.sum()) < 10: return "-", 0.0, 0
    pb = px[m]
    d = np.linalg.norm(pb[:, None, :] - REFARR[None, :, :], axis=2)
    near = d.min(1); v = d.argmin(1)
    valid = near <= VOTE_MAXDIST
    n = int(valid.sum())
    if n < 10: return "-", 0.0, n
    c = np.bincount(v[valid], minlength=len(KEYS))
    k = int(c.argmax())
    return KEYS[k], float(c[k]) / n, n

def read_grid_np(arr, refs=None):
    """arr: HxWx3 uint8。返回 (grid, conf)
    conf[i][j] = (glyph, ratio, saturation_mean, source)"""
    a = arr.astype(np.float32)
    grid = []; conf = []
    for i in range(8):
        row = []; crow = []
        cy = int(round(BOARD["y0"] + i * BOARD["pitch_y"]))
        for j in range(8):
            cx = int(round(BOARD["x0"] + j * BOARD["pitch_x"]))
            px = a[cy - 19:cy + 20, cx - 19:cx + 20].reshape(-1, 3)
            mx = px.max(1); mn = px.min(1)
            sat = np.where(mx > 0, (mx - mn) / np.maximum(mx, 1), 0)
            bright = mx > 105
            msat = float(sat[bright].mean()) if bright.sum() else 0.0

            # ① 饱和优先
            g, r, n = _vote(px, bright & (sat >= SAT_MIN))
            if g != "-" and r >= MIN_VOTES:
                row.append(g); crow.append((g, r, msat, "sat")); continue
            # ② 饱和像素多但无色可信 -> 道具/异常
            if int((bright & (sat >= SAT_MIN)).sum()) >= 25 and msat >= 0.20:
                row.append("S"); crow.append(("S", 0.0, msat, "spec")); continue
            # ③ 整格兜底（白宝石等低饱和）
            g2, r2, n2 = _vote(px, bright)
            if g2 != "-" and r2 >= MIN_VOTES:
                row.append(g2); crow.append((g2, r2, msat, "all")); continue
            row.append("?"); crow.append(("?", 0.0, msat, "low"))
        grid.append(row); conf.append(crow)
    return grid, conf

def is_board_like(conf, max_bad=3):
    """bad = '?' 格数（'S' 特殊格不算异常）。"""
    bad = sum(1 for r in conf for (g, _, _, _) in r if g == "?")
    return bad <= max_bad, bad

def fingerprint(g):
    return tuple("".join(r) for r in g)
