"""冰风暴模式。

**注意：这一格目前是空的。** 冰风暴的实际玩法（冰柱上升、要往下压）与
普通三消不同，但 bot 到现在为止没有任何针对它的策略 —— 实测样本也没有
（refs/ 里没有冰风暴的参考图，模式检测那一轮就记着这个缺口）。

先占位，让引擎能选中它、走普通三消、并且有一份自己的几何和有效判据。
以后要做冰风暴策略，改这个文件。
"""
from .base import Mode as _Base


class Mode(_Base):
    KEY = "icescape"
    NAME = "冰风暴"
    GEO = "classic"
    EFFECTIVE = "score"

    def detect(self, ctx):
        # 认不出来（没有可靠特征）。由 which_mode.py 的内存判据
        # （[Board+0x0] == 0x8685EC）在外面定。
        return False
