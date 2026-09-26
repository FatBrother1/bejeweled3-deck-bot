"""模式注册表。

**一个模式 = 一个文件。** 引擎不认识具体模式，只按顺序问每个模式
"这一帧是不是你"，第一个认领的赢；没人认领就落到 classic 兜底。

加一个新模式 = 在这里的 _KEYS 里加个名字 + 写一个文件，引擎不用动。
"""
import importlib

# 顺序 = 检测优先级。poker 排最前（它由引擎的画面判据给 hint，最准），
# 然后按"特征越独特越靠前"排：泥土 > 蝴蝶 > 时间宝石，最后 classic 兜底。
_KEYS = ["poker", "diamond", "butterfly", "lightning",
         "icescape", "zen", "quest", "classic"]

_BY_KEY = {}
for _k in _KEYS:
    _BY_KEY[_k] = importlib.import_module("." + _k, __name__).Mode()


def keys():
    """所有已注册的模式标识。"""
    return list(_KEYS)


def by_key(k):
    """按标识取模式实例；不认识返回 None。"""
    return _BY_KEY.get(k)


def detect(ctx):
    """选模式：hint 优先，然后按注册表顺序问，最后 classic 兜底。"""
    hint = ctx.get("hint")
    if hint and hint in _BY_KEY:
        return _BY_KEY[hint]
    for k in _KEYS:
        m = _BY_KEY[k]
        try:
            if m.detect(ctx):
                return m
        except Exception:
            continue
    return _BY_KEY["classic"]
