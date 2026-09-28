"""冰风暴模式（2026-09-28 从空壳升级为策略模式）。

# 玩法机制（来自萌娘百科「宝石迷阵3」，与 bot 视角对齐）

目标是压住不断上升的冰柱，柱子登顶崩溃 = 整盘结冰结束。bot 看不见冰柱
（内存后端没有柱高），所以策略只能从「什么操作能压柱」反推：

  · **纵向匹配**把所在列的冰柱往下压一点 —— 横向匹配完全不压柱；
  · **闪电宝石（flag 4）**消除时清掉本行本列 ⇒ 直接砸它所在的列；
  · **双超能对撞**清空整个版面，冰柱全部击碎（冰风暴返还 1 枚超能）；
  · 火焰宝石只会炸 3×3，对柱子几乎没用。

实现：`solver_pro.rank_moves` 新增三个**默认 0** 的权重（不传 = 旧行为）：

    W_VERTICAL=3000   竖向匹配的招 +3000（压柱是唯一活路）
    W_STARCOL=2000    这一步会引爆闪电宝石 +2000（整列清空）
    W_HYPER2=50000    双超能对撞 +50000（全盘冰柱清空，一劳永逸）

量级对照：普通一步的模拟分在 50~几千，spec 加成 ×8；3000/2000 足以让
「压柱」压倒同等分数的横排消除，又不至于盖过时间宝石那种 1e5 级的硬需求。

# 已知边界

  · 没有柱高信息 ⇒ 没法「专压快到顶的列」，只能无差别压。
  · 几何沿用 classic —— 冰风暴的棋盘原点没标定过（refs/ 无参考图），
    如果上机发现行中心对不上，照闪电/蝴蝶那套重标一份 board_icescape.json。
  · 连击（x3 起 5000、x13 封顶 15000）是连续快速碎柱才有的奖励，bot 的
    0.6~0.75 步/秒节奏拿不满，不计入权重。
"""
from .base import Mode as _Base


class Mode(_Base):
    KEY = "icescape"
    NAME = "冰风暴"
    GEO = "classic"
    EFFECTIVE = "score"
    W_VERTICAL = 3000.0
    W_STARCOL = 2000.0
    W_HYPER2 = 50000.0

    def detect(self, ctx):
        # 认不出来（没有可靠特征）。由 which_mode.py 的内存判据
        # （[Board+0x0] == 0x8685EC）在外面定。
        return False

    def solver_kw(self):
        return dict(super().solver_kw(),
                    w_vertical=self.W_VERTICAL,
                    w_starcol=self.W_STARCOL,
                    w_hyper2=self.W_HYPER2)
