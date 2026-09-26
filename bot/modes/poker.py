"""牌局模式（Poker）。

# 这个模式跟别人最不一样的地方

**手牌是"牌型"而不是分数。** 一次消除给一张牌，花色 = 这次消除的多数色；
手牌从左往右填（`?` 是还没拿到的空位，不是暗牌），满 5 张自动结算。
分数只在结算那一刻给，**消除宝石本身不给分** —— 所以：

1. 有效判据必须走棋盘（`EFFECTIVE = "board"`），不能走分数。
   这一条就是 2026-09-26 那个 bug：牌局落在"分数判据"分支里，每一步真有效的
   交换都被判"被拒"，全进拉黑、棋盘被掩码、每 12 步停手 20 秒（实测 0.36 步/秒、
   91% 拉黑率）。
2. 目标不是"每一步分最高"，而是**让哪种颜色成为多数色** —— 见 solver_poker。

# 几何

牌局棋盘和钻石矿/蝴蝶同属"现代版式"（格距 85.25），但原点又不一样
（x0=482.5 y0=113）。一直用经典几何时采样只命中 44/64 格，规划出的走法落到
别的格子上被拒。标定后 64/64、总色距 1725（经典 5513）。

# 死局处理

牌局没有那两道"拉黑掩码假死局"兜底（它用的是另一套候选生成），无招就是无招：
打一行日志、等 1 秒、连续 30 次就退出（让守护重新拉起）。
"""
from .base import Mode as _Base


class Mode(_Base):
    KEY = "poker"
    NAME = "牌局"
    GEO = "poker"
    EFFECTIVE = "board"
    GEO_WHY = "  ← 牌局棋盘格距 85.25、原点与经典差 34px，用错会点错格"
    DEAD_EXIT_AT = 30       # 连续无招 30 次就退出（普通模式是就地待命、不退出）

    def detect(self, ctx):
        # 牌局靠画面认（左侧 7 行绿色分值表），由 detect_mode() 在引擎里做，
        # 这里不重复。返回 False，让注册表继续往下走。
        return False

    def choose(self, ctx):
        import poker as pk
        import solver_poker
        import solver_pro

        g = ctx["g"]
        fr = ctx["frame"]
        if fr is None:
            fr = ctx["get_frame"]()
        hand = pk.read_hand(fr) if fr is not None else None
        known = [c for c in (hand or []) if c != "?"]
        banned = ctx["banned"] | ctx["banned_sticky"]

        if not known:
            # 手牌一张没翻开 ⇒ 没有花色信息。这时也【不能】乱打 ——
            # 随便凑出的低阶牌型会累积骷髅。仅在别无选择时按普通评分走。
            rk = solver_pro.rank_moves(g, banned=banned)
            if not rk:
                return None
            t = rk[0]
            return {"rk": rk, "t": t, "pred": t[1], "cells": (t[6], t[7]),
                    "hand": hand, "known": known}
        rk = solver_poker.rank_moves_poker(g, hand=hand, topk=10)
        if not rk:
            return None
        t = rk[0]
        return {"rk": rk, "t": t, "pred": t[1], "cells": (t[5], t[6]),
                "hand": hand, "known": known}

    def on_picked(self, ctx, res):
        import poker as pk
        import solver_poker
        hand = res.get("hand")
        if not res.get("known"):
            return
        hv = pk.hand_value(hand)
        t = res["t"]
        alive, lock, need = pk.flush_state(hand)
        ctx["log"]("  手牌 %s  目标色=%s  牌型=%s  消目标色=%d%s  [%s]"
                   % ("".join(hand), solver_poker.get_last_target(),
                      hv[0], t[8],
                      "  ★严格多数" if len(t) > 10 and t[10] else "",
                      ("同花活·还差%d" % need) if alive and lock
                      else ("同花活·未定色" if alive else "同花已死")))

    def on_no_move(self, ctx):
        ctx["log"]("  牌局无走法(%d)等洗牌..." % ctx["dead"])
