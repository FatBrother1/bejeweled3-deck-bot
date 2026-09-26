"""闪电模式。

和普通三消的差别只有一处：**时间宝石**。限时模式里不拿时间宝石就等着时间
耗尽，所以求解器要优先去消它。标记是 `flags & 131072`（COUNTER 位），计数在
`Piece+0x244`，由内存后端每次读盘时放进 `extra["timegems"]`。

求解器那边（solver_pro.rank_moves 的 timegems 参数）已经处理了加权，
这个文件负责把宝石位置传进去、并且把"这一步踩到时间宝石了"打出来。
"""
from .base import Mode as _Base


class Mode(_Base):
    KEY = "lightning"
    NAME = "闪电"
    GEO = "classic"
    EFFECTIVE = "score"

    def detect(self, ctx):
        # 棋盘上出现时间宝石 ⇒ 闪电。这是特征判据，不依赖模式识别。
        return bool((ctx["extra"] or {}).get("timegems"))

    def on_board_info(self, ctx, tg, bf):
        if tg:
            ctx["log"]("  ⏱ 时间宝石 %d 个: %s"
                       % (len(tg), ", ".join("(%d,%d)+%d" % t for t in tg)))
