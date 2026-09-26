"""模式基类：默认策略 = 普通三消（经典/禅意/冰风暴/闪电都跑这条）。

# 一个模式 = 一个文件

每个模式文件只声明**它跟别人不一样的地方**，其余继承这里。引擎只认下面
这几个接口，不认具体是哪个模式 —— 这样某个模式的修复只会落在它自己的
文件里，不会再出现"改在共享分支里、漏掉了另一个模式"的事
（2026-09-26 牌局就是这么坏的：钻石矿那条分支没覆盖到它）。

    KEY        标识（命令行 --mode 用它，也用来找 board_<KEY>.json）
    NAME       显示名（日志/面板）
    GEO        用哪份棋盘标定；board_<GEO>.json
    EFFECTIVE  "score" 靠分数变化判交换生效；"board" 靠棋盘变化判
    GEO_WHY    切到这个几何时日志里跟的那句解释

    detect(ctx)          从棋盘特征认出自己（注册表顺序决定优先级）
    choose(ctx)          选一步；返回 dict 或 None（None = 无招）
    on_board_info(ctx)   每步的盘面信息日志（可选）

# ctx（引擎每步构造，模式可以就地改）

    g              掩码后的棋盘（拉黑格已改写成 '?'）
    g_raw          真实棋盘
    blacklist      {(i,j): 被拒次数}
    banned         走法级拉黑 set(frozenset({(i,j),(i2,j2)}))
    banned_sticky  整局拉黑（同格式）
    extra          内存后端本次读到的附加信息（时间宝石/状态位/蝴蝶…）
    nd             棋盘上泥格数
    frame          本步画面（可能为 None）
    log            日志函数
"""
import solver_pro


class Mode(object):
    KEY = "classic"
    NAME = "经典"
    GEO = "classic"
    EFFECTIVE = "score"
    GEO_WHY = ""
    # 连续无招到多少次就退出。None = 就地待命、永不退出
    #（普通模式：退出会被守护立刻拉起、对着同一块冻结盘再打一轮）。
    DEAD_EXIT_AT = None

    # ── 检测 ────────────────────────────────────────────────
    def detect(self, ctx):
        """从棋盘特征认出自己。注册表里先匹配先赢，兜底模式返回 False。"""
        return False

    # ── 盘面信息 ────────────────────────────────────────────
    def special_flags(self, ctx):
        """火焰1 超立方2 闪电4 超新星5 —— 交给求解器模拟引爆范围。"""
        return {(i, j): f for (i, j, f) in ((ctx["extra"] or {}).get("flags") or [])
                if f in (1, 2, 4, 5)}

    def on_board_info(self, ctx, tg, bf):
        """每步打印盘面上的特殊东西。默认什么都不打。"""
        return

    # ── 选步 ────────────────────────────────────────────────
    def choose(self, ctx):
        """普通三消的选步链：求解 → 两道假死局兜底 → 取第一名。

        两道兜底都是实测踩出来的（2026-09-26）：
          ① 拉黑掩码会把 '?' 写进棋盘，'?' 不但自己不能连线，还会**切断
             别人的连线** —— 几个掩码就足以把真棋盘掩成 0 候选。
          ② 被游戏拒过的招会被 banned 挡掉；若所有合法招恰好都被挡掉，
             第①层也救不回来（它带着 banned 一起算）。
        两层都必须用 g_raw 重算 —— 用掩码版等于没救（蝴蝶模式实测趴窝 15 分钟）。
        """
        g = ctx["g"]; g_raw = ctx["g_raw"]
        extra = ctx["extra"] or {}
        tg = extra.get("timegems") or []
        fl = self.special_flags(ctx)
        bf = extra.get("butterflies") or []
        self.on_board_info(ctx, tg, bf)
        banned = ctx["banned"] | ctx["banned_sticky"]

        rk = solver_pro.rank_moves(g, timegems=tg, banned=banned,
                                   flags=fl, butterflies=bf)
        if not rk and ctx["blacklist"]:
            rk_raw = solver_pro.rank_moves(g_raw, timegems=tg, banned=banned,
                                           flags=fl, butterflies=bf)
            if rk_raw:
                ctx["log"]("  ★ 拉黑掩码掩出了假死局 → 清空拉黑，按真实棋盘走"
                           "（候选 %d，掩码格 %d）" % (len(rk_raw), len(ctx["blacklist"])))
                ctx["blacklist"].clear()
                ctx["g"] = [r[:] for r in g_raw]
                rk = rk_raw
        if not rk and (ctx["banned"] or ctx["banned_sticky"]):
            rk_free = solver_pro.rank_moves(g_raw, timegems=tg, banned=set(),
                                            flags=fl, butterflies=bf)
            if rk_free:
                ctx["log"]("  ★ 合法走法全被拉黑 → 解禁重算（候选 %d，原 ban %d 条，"
                           "掩码格 %d）"
                           % (len(rk_free), len(ctx["banned"]) + len(ctx["banned_sticky"]),
                              len(ctx["blacklist"])))
                ctx["banned"].clear(); ctx["banned_sticky"].clear()
                ctx["blacklist"].clear()
                ctx["g"] = [r[:] for r in g_raw]
                rk = rk_free
        if not rk:
            return None
        t = rk[0]
        return {"rk": rk, "t": t, "pred": t[1],
                "cells": (t[6], t[7]),
                "tgset": set((i, j) for i, j, _ in tg)}

    def on_picked(self, ctx, res):
        """选中之后的日志。默认：踩到时间宝石就报一句。"""
        (i1, j1), (i2, j2) = res["cells"]
        if res.get("tgset") and ((i1, j1) in res["tgset"] or (i2, j2) in res["tgset"]):
            ctx["log"]("  ★ 这一步直接拿时间宝石")

    def on_no_move(self, ctx):
        """没有可走的招时的日志。返回 "wait"（就地待命）或 "exit"。"""
        return "wait"

    def settles_on_clock_freeze(self, ctx):
        """时钟冻满阈值时问一句：这是本局结束，还是失焦暂停？

        ctx: {"nd": 泥土格数, "cs": 游戏时钟, "marker_live": 活跃标记判据}

        默认 False ⇒ 不认领，交给引擎的通用「失焦暂停」自愈去处理。
        只有钻石矿会认领（它每局 1:30，结束画面不是标准结算面板、像素判不出，
        但时钟会停）。
        """
        return False
