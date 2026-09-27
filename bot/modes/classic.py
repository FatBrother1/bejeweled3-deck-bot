"""经典模式。

# 万变魔方（超立方体）策略 —— 2026-09-27 用户点名

用户的原话：只要有万变魔方，游戏即使没有可消除的宝石也不会结束；消除魔方后
会产生新的可消三连；魔方**可以带进下一关**。所以经典模式的打法改成：

  1. **能造就该造**（`W_MAKE_HYPER`）—— 一条 5 连造一个魔方，求解器给这种招
     加分，让它压过普通招；
  2. **造出来就攒着**（`SAVE_HYPER`）—— 魔方招一律排到候选表最后，不动它；
  3. **真没招了才用** —— 候选表里只剩魔方招时，`rk[0]` 自然就是它。这一条
     不是"禁用魔方"，是"降到最后"，所以不会出现有魔方却走投无路的情况。

魔方在内存里的样子：`Piece+0x228` 的状态位 == 2、颜色是 -1（reader_mem 把它
读成字形 'S'）。因为颜色无效，普通连线判定（`solver_pro.same`）里 'S' 不参与
连线 —— 它只能靠"跟邻居换一下"引爆，这也正是"盘上有魔方就永远有招可走"的
原因。

# 为什么这一条只写在经典模式里

禅意/冰风暴/任务共用基类，它们的 W_MAKE_HYPER/SAVE_HYPER 取默认的"不管"，
行为与从前逐字节一致 —— 用户点的是经典，别的模式不跟着改。
"""
from .base import Mode as _Base


class Mode(_Base):
    KEY = "classic"
    NAME = "经典"
    GEO = "classic"
    EFFECTIVE = "score"

    # 造一个魔方加多少分。普通招的分数在几十~几千这个量级，3000 足以让
    # "这一步能造魔方"压过绝大多数别的考虑，又不至于把明显更好的大级联压掉。
    W_MAKE_HYPER = 3000.0
    # 有别的招就不动魔方。
    SAVE_HYPER = True

    def __init__(self):
        self._prev_hc = None      # 上一帧的魔方位置（变化沿触发日志，别每步刷）

    def detect(self, ctx):
        # 兜底模式：别人都不认领就是它。注册表里放最后。
        return True

    def _hyper_cells(self, ctx):
        fl = self.special_flags(ctx)
        return sorted(p for p, f in fl.items() if f == 2)

    def on_board_info(self, ctx, tg, bf):
        hc = self._hyper_cells(ctx)
        if hc != self._prev_hc:
            if hc:
                ctx["log"]("  ◆ 盘上万变魔方 %d 个: %s  ← 攒着，没招了才用"
                           % (len(hc), ", ".join("(%d,%d)" % p for p in hc)))
            elif self._prev_hc:
                ctx["log"]("  ◆ 魔方已不在盘上（用掉了，或被别的特殊宝石引爆）")
            self._prev_hc = hc

    def on_picked(self, ctx, res):
        """这一步要是动了魔方，明说是"没招了才动"—— 日志里好核对。"""
        (i1, j1), (i2, j2) = res["cells"]
        g = ctx["g"]
        if g[i1][j1] == "S" or g[i2][j2] == "S":
            ctx["log"]("  ★ 盘上没有可消的三连了 → 动用万变魔方 %s<->%s"
                       % ((i1, j1), (i2, j2)))
        _Base.on_picked(self, ctx, res)
