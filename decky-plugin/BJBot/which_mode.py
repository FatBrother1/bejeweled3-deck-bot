#!/usr/bin/env python3
"""游戏模式探测（供 Decky 插件调用）。

    python3 which_mode.py          # 打印中文模式名
    python3 which_mode.py --json   # {"key","name","dist","src"}

## 两个信息源，内存优先

**① 内存（src="mem"）**
  读 `[Board+0x0]`。实测它在不同模式/界面下取不同值，
  且**同一界面重复进入时值相同**（实测 0x866B6C 两次出现）。
  缺点：这个偏移**只能区分"界面"，不能保证区分"禅意 vs 经典"** ——
  这两个模式的 UI 高度相似，尚未取到各自的样本验证。
  所以内存值只作**已知映射**用：命中表里的值才采信，否则交给图像。

**② 图像（src="img"）**
  10x16 网格 RGB 均值当指纹，跟 refs/ 里的参考图比欧氏距离，取最近。
  参考图是 1280x800 全屏下拍的实测画面。

两者都拿不到就返回"未知"，调用方按普通模式处理。

## 已知限制（如实写在代码里，别当它万能）

  · refs/ 里每个模式只有 1~2 张参考图，且部分模式**没样本**（经典、冰风暴）。
    样本少的模式容易误判 —— 面板上模式名仅供参考。
  · 游戏若不是 1280x800 全屏（改成窗口了），图像一路直接认输返回"未知"。
    实测踩过：误触改成 1024x768，左右出黑边，一切坐标和指纹全偏。
  · 同一模式的背景会随关卡轮换，指纹可能漂移。
"""
import json
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
REF_DIR = os.path.join(HERE, "refs")
GRID = (10, 16)

NAMES = {
    "zen": "禅意", "classic": "经典", "lightning": "闪电",
    "icescape": "冰风暴", "butterfly": "蝴蝶", "diamond": "钻石矿",
    "poker": "牌局", "menu": "菜单", "paused": "暂停", "unknown": "未知",
}

# [Board+0x0] 实测值 → 模式。只放**已通过画面确认**的。
#   0x866B6C 实测两次，画面均为禅意（35 关、紫色钻石进度、暂停"开始!"遮罩）
#   0x86511C 实测为主菜单
#   0x8665C4 实测为闪电（右上 1:00 倒计时）
#   0x8685EC 实测为钻石矿（底部泥土、紫色花朵面板）
#   0x867D0C 实测为蝴蝶（右侧紫色树）
#   0x869364 实测为主菜单（带"继续游戏?"弹窗）
MEM_MAP = {
    0x866B6C: "zen",
    0x86511C: "menu",
    0x8665C4: "lightning",
    0x8685EC: "diamond",
    0x867D0C: "butterfly",
    0x869364: "menu",
}


def _read_mem_b0():
    """读 [Board+0x0]。失败返回 None。"""
    try:
        sys.path.insert(0, "/home/deck")
        import reader_mem as R
        pr = R._Proc(R.find_pid())
        g = pr.u32(R.GAPP_ADDR)
        if not g:
            return None
        b = pr.u32(g + R.OFF_BOARD)
        if not b:
            return None
        return pr.i32(b)
    except Exception:
        return None


def _read_board_diamond():
    try:
        sys.path.insert(0, "/home/deck")
        import reader_mem as R
        r = R.MemReader()
        g, bad, extra = r._read_grid()
        if g:
            return sum(row.count("D") for row in g) >= 4
    except Exception:
        pass
    return False


def _fingerprint(frame):
    f = np.asarray(frame, dtype="float32")
    if f.ndim != 3 or f.shape[2] < 3:
        return None
    H, W, _ = f.shape
    rs = np.linspace(0, H, GRID[0] + 1).astype(int)
    cs = np.linspace(0, W, GRID[1] + 1).astype(int)
    cells = []
    for i in range(GRID[0]):
        for j in range(GRID[1]):
            c = f[rs[i]:rs[i + 1], cs[j]:cs[j + 1]]
            cells.extend([c[:, :, 0].mean(), c[:, :, 1].mean(), c[:, :, 2].mean()])
    v = np.array(cells, dtype="float32")
    return (v - v.mean()) / (v.std() + 1e-6)


def _load_refs():
    from PIL import Image
    out = []
    if not os.path.isdir(REF_DIR):
        return out
    for fn in sorted(os.listdir(REF_DIR)):
        if not fn.endswith(".png"):
            continue
        key = fn[5:-4] if fn.startswith("mode_") else fn[:-4]
        if key.endswith("2"):          # 同一模式的第二张参考图，归到同一 key
            key = key[:-1]
        try:
            v = _fingerprint(np.asarray(Image.open(os.path.join(REF_DIR, fn)).convert("RGB")))
            if v is not None:
                out.append((key, v))
        except Exception:
            continue
    return out


def _grab():
    try:
        sys.path.insert(0, "/home/deck")
        from cap2 import Cap
        c = Cap()
        try:
            for _ in range(25):
                a = c.get(timeout=1.0)
                if a is not None:
                    return a
        finally:
            c.stop()
    except Exception:
        return None
    return None


def detect(frame=None, refs=None):
    """返回 (key, 显示名, 距离, 来源)。"""
    # ① 内存优先（只认表里有的值）
    b0 = _read_mem_b0()
    if b0 is not None and b0 in MEM_MAP:
        k = MEM_MAP[b0]
        return k, NAMES.get(k, k), None, "mem"

    # ①b 棋盘泥格：钻石矿最可靠信号
    if _read_board_diamond():
        return "diamond", NAMES["diamond"], None, "memboard"

    # ② 图像
    if frame is None:
        frame = _grab()
    if frame is None:
        return "unknown", NAMES["unknown"], None, "none"
    if frame.shape[0] != 800 or frame.shape[1] != 1280:
        return "unknown", NAMES["unknown"], None, "size"
    if refs is None:
        refs = _load_refs()
    if not refs:
        return "unknown", NAMES["unknown"], None, "norefs"
    v = _fingerprint(frame)
    if v is None:
        return "unknown", NAMES["unknown"], None, "none"
    best, bd = None, 1e18
    for key, rv in refs:
        if rv.shape != v.shape:
            continue
        d = float(np.sqrt(((v - rv) ** 2).mean()))
        if d < bd:
            bd, best = d, key
    return best, NAMES.get(best, best), round(bd, 3), "img"


if __name__ == "__main__":
    k, n, d, src = detect()
    if "--json" in sys.argv:
        print(json.dumps({"key": k, "name": n, "dist": d, "src": src},
                         ensure_ascii=False))
    else:
        print(n)
