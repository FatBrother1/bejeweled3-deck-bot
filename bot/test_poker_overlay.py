#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""牌局「结算覆盖层 + 走法级拉黑 + 不再用掩码盘」—— 离线验证（2026-09-27）

背景（风暴的完整链条，实测证据见 modes/poker.py 注释）：
  打满 5 张牌 → 中央弹一排白卡（约 2 秒，游戏不接受交换）→ 它的判据是白卡带
  （R-B≈0），引擎两个通用画面判据都命中不了 → bot 照常出手、交换必被拒 →
  牌局求解器原来不认走法级拉黑（`rank_moves_poker` 没有 banned 参数）⇒ 同一招
  连试 3 次 ⇒ 那 2 格拉黑到阈值 3 ⇒ 掩码把盘上仅剩的几招全掩掉 ⇒ 无走法(30)
  退出 ⇒ 守护重拉 ⇒ 1~2 分钟一轮。

覆盖：
  A. settle_overlay：真实帧上「结算=True、正常=False」，判据余量 ≥3 倍
  B. overlay_action：结算帧给动作、正常帧给 None、判不了不认领
  C. choose 认走法级拉黑；候选全被 ban 时解禁重算
  E. choose 用真实棋盘（g_raw）：掩码把 5 格掩死也照样能选
  F. 返回结构不变（bot_v6 依赖 t[1]/t[5]/t[6]/t[8]）

跑法：`python3 test_poker_overlay.py [帧目录]`
      A/B 需要 numpy + 真实帧（st_normal.png / st_stuck1.png）；
      帧不在就自动跳过 A/B，其余照跑。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from modes import poker as P            # noqa: E402
import solver_poker as SP               # noqa: E402

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(("  ✓ " if cond else "  ✗ ") + name + ("" if cond else "   ← " + str(detail)))


M = P.Mode()


def mkctx(g, g_raw=None, banned=None, banned_sticky=None, blacklist=None, frame=None):
    return {"g": g,
            "g_raw": g_raw if g_raw is not None else [r[:] for r in g],
            "banned": set(banned or ()),
            "banned_sticky": set(banned_sticky or ()),
            "blacklist": dict(blacklist or {}),
            "frame": frame, "get_frame": (lambda: None), "extra": {}, "nd": 0,
            "log": (lambda s: None), "bad": 0, "dead": 0}


# 一块有招的真实盘（2026-09-27 上机读盘，暴力法核对过 = 3 招）
BOARD = [list(r) for r in ("RYGRPYWW", "GPWORBPG", "WOPBPOYB", "ORROWGBG",
                           "GBPWBYPR", "GRBYRPWY", "BOYYWWPG", "POPPOOGR")]

# ── A / B：真实帧上的判据 ────────────────────────────────────
d = sys.argv[1] if len(sys.argv) > 1 else "."
try:
    from PIL import Image
    import numpy as np

    def load(n):
        p = os.path.join(d, n)
        if not os.path.exists(p):
            return None
        return np.asarray(Image.open(p).convert("RGB"))

    normal, settle = load("st_normal.png"), load("st_stuck1.png")
    if normal is not None and settle is not None:
        def wr(f):
            x0, y0, x1, y1 = M.SETTLE_BAND
            return float((f[y0:y1, x0:x1].min(axis=2) > 200).mean())

        wn, ws = wr(normal), wr(settle)
        check("A1 结算帧判为结算", M.settle_overlay(settle) is True,
              M.settle_overlay(settle))
        check("A2 正常帧判为正常", M.settle_overlay(normal) is False,
              M.settle_overlay(normal))
        check("A3 判据余量 ≥3 倍", ws > wn * 3 and ws > M.SETTLE_WHITE > wn,
              "正常 %.3f 阈值 %.2f 结算 %.3f" % (wn, M.SETTLE_WHITE, ws))
        check("B1 结算帧 overlay_action 有动作",
              M.overlay_action({"frame": settle}) is not None)
        check("B2 正常帧 overlay_action 为 None",
              M.overlay_action({"frame": normal}) is None)
        check("B3 拿不到帧时不认领", M.settle_overlay(None) is None)
    else:
        print("  （跳过 A/B：帧文件不在 %s）" % d)
except ImportError as e:
    print("  （跳过 A/B：%s）" % e)

# ── C：认走法级拉黑 ─────────────────────────────────────────
rk = SP.rank_moves_poker(BOARD, hand=list("GG???"), topk=10)
if rk:
    top = frozenset((rk[0][5], rk[0][6]))
    res = M.choose(mkctx(BOARD, banned=[top]))
    check("C1 banned 里的招不再被选中",
          res is not None and frozenset((res["t"][5], res["t"][6])) != top,
          "仍选中 %s" % (top,))
    allb = set(frozenset((t[5], t[6])) for t in rk)
    check("C2 候选全被 ban → 解禁重算并给出招",
          M.choose(mkctx(BOARD, banned=allb)) is not None)
    ctx_s = mkctx(BOARD, banned_sticky=[top])
    r_s = M.choose(ctx_s)
    check("C3 banned_sticky 同样生效",
          r_s is not None and frozenset((r_s["t"][5], r_s["t"][6])) != top)
else:
    print("  （跳过 C：这块盘没招）")

# ── E：掩码盘掩死也不影响（choose 用 g_raw）──────────────────
masked = [r[:] for r in BOARD]
for (i, j) in ((5, 5), (5, 6), (6, 6), (7, 0), (7, 1)):
    masked[i][j] = "?"
ctx4 = mkctx(masked, g_raw=BOARD,
             blacklist={(5, 5): 3, (5, 6): 3, (6, 6): 3, (7, 0): 3, (7, 1): 3})
res4 = M.choose(ctx4)
check("E1 掩码盘（5 格 '?'）照样选出招", res4 is not None)
if res4 is not None:
    t = res4["t"]
    check("E2 选出的招落在真实棋盘上（不是 '?'）",
          BOARD[t[5][0]][t[5][1]] != "?" and BOARD[t[6][0]][t[6][1]] != "?")
    check("F1 返回结构不变",
          len(t) >= 9 and isinstance(t[1], int)
          and isinstance(t[5], tuple) and isinstance(t[6], tuple)
          and isinstance(t[8], int))

print()
print("通过 %d / 失败 %d" % (len(PASS), len(FAIL)))
sys.exit(1 if FAIL else 0)
