"""任务模式。

**这一格是空的，而且现在也选不中它。** 两个原因：

1. which_mode.py 认不出任务 —— 任务界面没有棋盘对象，读不到 [Board+0x0]，
   会掉进图像指纹、显示成"菜单"（那一轮的注释里就写了这个已知缺口）。
2. bot 这边也没有任何任务模式的策略。

所以这个文件现在只是把位置占住：等哪天真进任务模式测出内存值/画面特征，
补上 detect 和策略即可，不用再动引擎。
"""
from .base import Mode as _Base


class Mode(_Base):
    KEY = "quest"
    NAME = "任务"
    GEO = "classic"
    EFFECTIVE = "score"

    def detect(self, ctx):
        return False
