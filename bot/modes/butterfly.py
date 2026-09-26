"""蝴蝶模式。

蝴蝶宝石 = 状态位 **128**（`Piece+0x228`），由内存后端放进
`extra["butterflies"]`。蝴蝶从底下出现、逐格往上飞，**飞到顶行这局就结束** ——
所以"能消掉蝴蝶"的招必须压倒性优先，求解器按 `100000 × (8 - 行号)` 加权
（越靠上越急）。

# 为什么这个模式单独占一份几何

蝴蝶的棋盘比经典**低约 58 像素**、格距也小一点（85.32/84.84 对 89.17/88.17）。
用经典几何时第 0 行的拖动会落到棋盘外、被游戏直接拒 —— 实测旧几何 0/4、
换 board_butterfly.json 后 6/6。症状就是"走法全被拒 + 反复拉黑 + 停手"。
"""
from .base import Mode as _Base


class Mode(_Base):
    KEY = "butterfly"
    NAME = "蝴蝶"
    GEO = "butterfly"
    EFFECTIVE = "score"
    GEO_WHY = "  ← 蝴蝶模式棋盘比经典低约 58px、格距更小，用错会点错格"

    def __init__(self):
        self._prev_n = 0        # 上一帧的蝴蝶只数（只在变化时打日志，别每步刷）

    def detect(self, ctx):
        # 棋盘上有蝴蝶宝石 ⇒ 蝴蝶模式。
        return bool((ctx["extra"] or {}).get("butterflies"))

    def on_board_info(self, ctx, tg, bf):
        if bf and len(bf) != self._prev_n:
            ctx["log"]("  🦋 蝴蝶 %d 只: %s  ← 飞到顶行就结束，优先消"
                       % (len(bf), ", ".join("(%d,%d)" % p for p in bf)))
            self._prev_n = len(bf)
