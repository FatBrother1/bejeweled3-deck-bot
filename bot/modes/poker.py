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

    # ── 手牌结算覆盖层（2026-09-27 新增）─────────────────────────
    #   区域 = 中央横排 5 张白卡所在的那一条；判据 = 白像素（min(R,G,B)>200）占比。
    #   实测（1280x800 真实帧，本机复算）：
    #       结算覆盖层   0.475
    #       正常对局     0.004
    #       游戏结束画面 0.000
    #   阈值 0.15 两侧余量都在 3 倍以上。
    #
    #   ★ 为什么必须认它（风暴的真因）★
    #     打满 5 张牌时游戏在中央弹一排白卡 + 牌型名 + 「+分数」（约 2 秒动画，
    #     金色星星飞散）。这段窗口游戏**不接受交换**，而它的判据是白卡带
    #     （R-B≈0），引擎那两个通用画面判据（结算面板/徽章面板，都靠暖色占比）
    #     一个都命中不了 ⇒ bot 照常出手、必被拒 ⇒ 见 choose() 里那段说明。
    SETTLE_BAND = (570, 330, 1010, 470)      # x0, y0, x1, y1
    SETTLE_WHITE = 0.15

    def detect(self, ctx):
        # 牌局靠画面认（左侧 7 行绿色分值表），由 detect_mode() 在引擎里做，
        # 这里不重复。返回 False，让注册表继续往下走。
        return False

    def settle_overlay(self, frame):
        """是不是「手牌结算覆盖层」。True / False / None（None = 判不了）。

        判据与实测见类常量注释。拿不到帧或帧太小返回 None（不认领）。
        """
        if frame is None:
            return None
        try:
            import numpy as np
            f = np.asarray(frame, dtype="float32")
            if f.ndim != 3 or f.shape[0] < 480 or f.shape[1] < 1020:
                return None
            x0, y0, x1, y1 = self.SETTLE_BAND
            p = f[y0:y1, x0:x1]
            return bool((p.min(axis=2) > 200).mean() > self.SETTLE_WHITE)
        except Exception:
            return None

    def overlay_action(self, ctx):
        """手牌结算覆盖层：等它放完，这一步不出手。

        为什么是"等"而不是"点掉"：实测它是**动画**（约 2 秒，金色星星飞散），
        自己会消失，不需要点；点了反而可能点到棋盘格。
        清空拉黑：这段窗口里的拒绝是画面造成的、不是招不好，留着会把盘掩死。
        """
        if self.settle_overlay(ctx.get("frame")) is True:
            return {"name": "手牌结算覆盖层",
                    "what": "等它放完（这段窗口游戏不接受交换）",
                    "wait": 1.0, "clear_blacklist": True}
        return None

    def choose(self, ctx):
        import poker as pk
        import solver_poker

        # ★ 用真实棋盘：掩码（拉黑格改写 '?'）对牌局有害无益 ——
        #   '?' 不但自己不能连线、还会切断别人的连线，而牌局盘本来就只有几招
        #   （随机稳定盘统计：中位 11 招、≤3 招的比例 0.0%），几个掩码就足以
        #   造出假死局。掩码原本的作用（别重选刚被拒的招）由下面的 banned 过滤承担。
        g = ctx["g_raw"]
        fr = ctx["frame"]
        if fr is None:
            fr = ctx["get_frame"]()
        hand = pk.read_hand(fr) if fr is not None else None
        known = [c for c in (hand or []) if c != "?"]

        # ★ 2026-09-27：手牌一张没翻开时**也**走牌局求解器。
        #
        # 旧代码这里退回普通评分（`solver_pro.rank_moves`，= 谁消得多谁第一），
        # 理由是"没有花色信息、乱打会攒骷髅"。但每手牌的**第一张**恰恰决定了
        # 这手能追哪个花色（已翻开一出现第二种颜色，同花就死了），把它交给一个
        # 与牌型无关的贪心，等于"宝石消除求快"。用户本轮要的是
        # "宝石消除不求快，只求优解优先拿到同花"。
        #
        # 没有花色信息时 solver_poker 不会瞎选：它按"有多少步能把这个色做成
        # 严格多数"挑一个能持续产出的色当目标（第 17 轮的规则，当时被这条
        # 分支挡在外面、从没在实战里跑过）。
        rk = solver_poker.rank_moves_poker(g, hand=hand, topk=10)

        # ★ 走法级拉黑（2026-09-27 补）：`rank_moves_poker` 没有 banned 参数，
        #   原来被拒的招每一步都会被重选 —— 实测同一招连试 3 次、把那 2 格拉黑到
        #   阈值 3，掩码随即把盘上仅剩的招全掩掉（「无走法风暴」的完整链条）。
        #   普通求解器 `solver_pro.rank_moves` 一直有这个参数，牌局这条漏了。
        ban = ctx["banned"] | ctx["banned_sticky"]
        if rk and ban:
            rk_ok = [t for t in rk if frozenset((t[5], t[6])) not in ban]
            if rk_ok:
                rk = rk_ok
            else:
                # 候选全被拉黑 = 刚才每一步都被拒。可能是结算窗口那种"画面造成的
                # 拒绝"（棋盘其实没变），也可能是真的没法走。解禁一次重算 ——
                # 不解禁就会在原地打转，最后按「无走法」退出。
                ctx["log"]("  ★ 候选 %d 条全被走法级拉黑 → 解禁重算"
                           "（棋盘没变，可能是画面造成的假拒绝）" % len(rk))
                ctx["banned"].clear(); ctx["banned_sticky"].clear()
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
