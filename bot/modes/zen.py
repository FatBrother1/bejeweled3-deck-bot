"""禅意模式。

棋盘版式与经典完全相同（都是 board.json），求解器也一样 —— 禅意和经典在
bot 这边唯一的差别是目标（禅意不计时、不结束；经典要过关），而现在的求解
器对两者是同一套"每一步分最高"。**这一格先占住**：以后禅意要做成"不追求
单步分、追求局面稳"的话，改这个文件就行，不会碰到经典。
"""
from .base import Mode as _Base


class Mode(_Base):
    KEY = "zen"
    NAME = "禅意"
    GEO = "classic"
    EFFECTIVE = "score"

    def detect(self, ctx):
        # 禅意和经典的棋盘版式、盘面特征都一样，靠棋盘认不出来。
        # 由 which_mode.py 的内存判据（[Board+0x0] == 0x866B6C）在外面定，
        # 这里返回 False，让注册表继续往下走。
        return False
