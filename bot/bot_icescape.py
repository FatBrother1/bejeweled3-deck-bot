#!/usr/bin/env python3
"""冰风暴模式入口 —— 等价于 `bot_v6.py --mode icescape`。

模式脚本化的门面：守护按 which_mode.py 检测到的模式拉起对应的这一个，
插件面板上也就有了真实的脚本名可显示（以前永远显示 bot_v6.py）。

引擎与策略本体仍在 `bot_v6.py`（循环/抓帧/读盘/鼠标）和 `modes/icescape.py`
（本模式的几何、有效判据、选步、检测）里，这里只负责把模式钉死。
"""
import os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import bot_v6

MODE = "icescape"


def _strip_mode(argv):
    """去掉调用方可能带的 --mode，避免和这里钉死的那个打架。"""
    out, i = [], 0
    while i < len(argv):
        if argv[i] == "--mode":
            i += 2
            continue
        if argv[i].startswith("--mode="):
            i += 1
            continue
        out.append(argv[i])
        i += 1
    return out


if __name__ == "__main__":
    sys.argv = [sys.argv[0], "--mode", MODE] + _strip_mode(sys.argv[1:])
    bot_v6.main()
