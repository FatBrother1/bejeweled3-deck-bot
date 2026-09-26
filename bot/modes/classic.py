"""经典模式。"""
from .base import Mode as _Base


class Mode(_Base):
    KEY = "classic"
    NAME = "经典"
    GEO = "classic"
    EFFECTIVE = "score"

    def detect(self, ctx):
        # 兜底模式：别人都不认领就是它。注册表里放最后。
        return True
