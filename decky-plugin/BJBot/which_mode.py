#!/usr/bin/env python3
"""游戏模式探测（供 Decky 插件调用）。

    python3 which_mode.py          # 打印中文模式名
    python3 which_mode.py --json   # {"key","name","dist","src"}

## 两个信息源，内存优先

**① 内存（src="mem"）★ 2026-09-26 全量重测后这才是主判据**
  读 `[Board+0x0]`（棋盘对象的 vtable 指针）。点进某个模式时它立刻变成该模式的值，
  **六个模式的值已逐个对着画面核过**（见下面 MEM_MAP 的注释）。
  读不到它 = 当前没有棋盘对象 = 在菜单/加载中 → 直接报"菜单"（src="noboard"），
  **不再交给图像去猜** —— 图像会把模式选择树认成蝴蝶、把主菜单认成菜单。

**①b 泥土（src="memboard"）**
  棋盘里泥土格 ≥4 = 钻石矿。内存值不认识时的兜底，也用来防"值变了还报旧模式"。

**② 图像（src="img"，最后的兜底）**
  10x16 网格 RGB 均值当指纹，跟 refs/ 里的参考图比欧氏距离，取最近。
  参考图是 1280x800 全屏下拍的实测画面。**只在"有棋盘对象但值不认识"时才会走到**。

游戏没在跑 → "未知"（src="nogame"）。

## 已知限制（如实写在代码里，别当它万能）

  · refs/ 里每个模式只有 1~2 张参考图，且部分模式**没样本**（经典、冰风暴）。
    样本少的模式容易误判 —— 所以图像只在最后兜底，模式名不要只信它。
  · 游戏若不是 1280x800 全屏（改成窗口了），图像一路直接认输返回"未知"。
    实测踩过：误触改成 1024x768，左右出黑边，一切坐标和指纹全偏。
  · 同一模式的背景会随关卡轮换，指纹可能漂移。
  · 任务(Quests)界面没有棋盘对象，会显示"菜单" —— 可接受，别再拿图像去猜。
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

# [Board+0x0] 实测值 → 模式。★ 2026-09-26 全量重测，每条都对着画面核过：
#   0x86511C 经典   （城堡+彩虹背景，截图核过）
#   0x866B6C 禅意   （用户按顺序切换，逐段对时间轴核过）
#   0x8665C4 闪电   （左侧连击倍率柱；用户确认）
#   0x867D0C 蝴蝶   （用户按顺序切换核过）
#   0x8685EC 冰风暴 （左侧冰柱 + "游戏结束"冻结画面，截图核过）
#   0x8657D4 钻石矿 （画面 $138,500 + 泥土 30 格，截图核过）
#
# ★ 这个偏移其实是**棋盘对象的 vtable 指针**：点进某个模式时它立刻变成那个模式的值
#   （连"继续游戏?"弹窗期间都已经是新值）；菜单/加载中压根没有棋盘对象，读不到。
#
# ★★ 2026-09-26 的事故教训（用户报"模式显示全乱套了"）★★
#   旧表把 0x86511C 标成"菜单"、把 0x8685EC 标成"钻石矿"，还漏了真正的钻石矿 0x8657D4。
#   于是：经典 → 显示"菜单"；冰风暴 → 显示"钻石矿"；钻石矿没进表只能靠泥土兜底。
#   而菜单/加载中（读不到棋盘对象）时会掉进图像指纹，把"模式选择树"认成蝴蝶、
#   把主菜单认成菜单 —— 越猜越离谱。
#   ⇒ 纪律：**表里只放对着画面核过的值**；没核过的宁可不放，走下面的兜底。
MEM_MAP = {
    0x86511C: "classic",
    0x866B6C: "zen",
    0x8665C4: "lightning",
    0x867D0C: "butterfly",
    0x8685EC: "icescape",
    0x8657D4: "diamond",
}


def _read_mem_b0():
    """读 [Board+0x0]。读不到（没有棋盘对象 / 进程不在）返回 None。"""
    try:
        sys.path.insert(0, "/home/deck")
        import reader_mem as R
        pid = R.find_pid()
        if not pid:
            return None
        pr = R._Proc(pid)
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
    # ① 内存值优先（只认对着画面核过的）
    b0 = _read_mem_b0()
    if b0 is not None and b0 in MEM_MAP:
        k = MEM_MAP[b0]
        return k, NAMES.get(k, k), None, "mem"

    # ①b 棋盘泥格：钻石矿最可靠的信号（内存值不认识时也能认出来）
    if _read_board_diamond():
        return "diamond", NAMES["diamond"], None, "memboard"

    # ①c 连棋盘对象都没有 = 在菜单 / 加载中（2026-09-26 新增）
    #   ★ 这一步是本次修复的关键：以前这里直接掉进图像指纹，而指纹会把
    #     "模式选择树"认成蝴蝶、把主菜单认成菜单 —— 越猜越离谱。
    #     没有棋盘就是没有对局，如实报"菜单"，别猜。
    if b0 is None:
        running = False
        try:
            sys.path.insert(0, "/home/deck")
            import reader_mem as R
            running = R.find_pid() is not None
        except Exception:
            running = False
        if not running:
            return "unknown", NAMES["unknown"], None, "nogame"
        return "menu", NAMES["menu"], None, "noboard"

    # ② 图像（最后兜底：有棋盘对象、但值不认识 —— 比如游戏更新后偏移变了）
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
