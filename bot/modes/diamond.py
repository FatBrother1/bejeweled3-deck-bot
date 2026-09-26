"""钻石矿模式。

泥土格读作 `D`，不可消不可换；消旁边的宝石会自动挖开，泥一破画面自动下移。
**目标 = 往下挖，越深越好**（2026-09-25 用户纠偏），金子只是顺带的分数 ——
所以求解器按深度给贴泥的招加权（`+300 × (1 + 泥格行号/7)`）。

# 为什么这个模式的有效判据跟别人不一样

别的模式靠"分数变了没有"判这次交换游戏收没收。钻石矿不行：**它的分数在内存里
读不到**（实测画面 $48,000 而 `Board+0xD24` 读 0）。所以只能靠棋盘变化判，
而且必须再叠一条"我们拖的那两格确实变了"，否则泥土状态抖动之类的无关变化
会把被拒的招洗白。

# 为什么它自己认领"时钟冻结"

钻石矿每局 1:30，时间到会结束。它的结束画面不是标准橙色结算面板（像素判不出），
但游戏时钟会停 —— 判据是"有泥 + 本局确实开始过 + 时钟冻结满 8 次采样（约 20 秒）"。
这是钻石矿独有的，所以由它自己认领；别的模式冻结这么久就是失焦暂停，走通用自愈。
"""
from .base import Mode as _Base


class Mode(_Base):
    KEY = "diamond"
    NAME = "钻石矿"
    GEO = "diamond"
    EFFECTIVE = "board"
    GEO_WHY = "  ← 钻石矿格子比经典低约 54px，用错会点错格"

    def __init__(self):
        self._prev_nd = 0       # 上一帧的泥土格数（变化沿触发日志）

    def detect(self, ctx):
        # 棋盘上有泥土 ⇒ 钻石矿。
        return ctx["nd"] > 0

    def on_board_info(self, ctx, tg, bf):
        nd = ctx["nd"]
        if nd and not self._prev_nd:
            ctx["log"]("  ★ 钻石矿：泥土 %d 格（不可消不可换；消旁边的宝石自动挖开）"
                       % nd)
        self._prev_nd = nd

    def settles_on_clock_freeze(self, ctx):
        """时钟冻满阈值时问一句：这是不是本局结束（而不是失焦暂停）？

        原判据：`cs_frozen >= 8 and nd > 0 and cs > 0 and marker_live()`。
        其中 `nd > 0` 就是"是不是钻石矿"，现在由这个文件回答。
        """
        return ctx["nd"] > 0 and ctx["cs"] > 0 and ctx["marker_live"]()
