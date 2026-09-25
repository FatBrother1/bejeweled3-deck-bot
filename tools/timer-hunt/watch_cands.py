#!/usr/bin/env python3
"""甄别倒计时：每秒同时记录「候选值」与「屏幕截图」，事后用屏幕数字匹配。

候选来自 np_diff.py（159 个，都满足「6 秒内恰好降 6」）。
这么多是因为游戏里有大量动画/音效计时器也在 -1/秒 递减。
唯一的区别是：**只有真正的倒计时，其值等于屏幕右上角显示的数字**。

所以本脚本每秒存一张倒计时裁剪图 + 记录所有候选值，
跑完后把裁剪图拼成一条横条，人工（我）读出数字，再和记录的候选值对。
"""
import ctypes
import os
import sys
import time

import numpy as np

sys.path.insert(0, "/home/deck")
from reader_mem import _IOV, _libc, find_pid, _Proc, GAPP_ADDR   # noqa: E402
from cap2 import Cap                                              # noqa: E402
from vmouse2 import VMouse2                                       # noqa: E402
from PIL import Image                                             # noqa: E402
import bot_v6                                                     # noqa: E402

OUT = "/home/deck/watch"
N_WATCH = 40            # 只盯前 40 个候选
SECS = 12


def load_cands():
    rows = []
    try:
        with open("/home/deck/np2_cands.txt") as f:
            for line in f:
                p = line.split()
                if len(p) >= 3:
                    rows.append((int(p[0], 16), p[1]))
    except Exception:
        pass
    return rows


def read_many(pid, addrs, kinds):
    """多 iovec 批量读，返回 {addr: value}。"""
    out = {}
    B = 256
    for i in range(0, len(addrs), B):
        batch = addrs[i:i + B]
        bufs = [ctypes.create_string_buffer(8) for _ in batch]
        iov_l = (_IOV * len(batch))()
        iov_r = (_IOV * len(batch))()
        for j, a in enumerate(batch):
            iov_l[j] = _IOV(ctypes.cast(bufs[j], ctypes.c_void_p), 8)
            iov_r[j] = _IOV(ctypes.c_void_p(a), 8)
        if _libc.process_vm_readv(pid, iov_l, ctypes.c_ulong(len(batch)),
                                  iov_r, ctypes.c_ulong(len(batch)), 0) <= 0:
            continue
        for j, a in enumerate(batch):
            raw = bufs[j].raw
            k = kinds[a]
            if k in ("s_i", "ms"):
                out[a] = float(np.frombuffer(raw[:4], dtype="<i4")[0])
            elif k == "s_f":
                out[a] = float(np.frombuffer(raw[:4], dtype="<f4")[0])
            else:
                out[a] = float(np.frombuffer(raw[:8], dtype="<f8")[0])
    return out


def main():
    os.makedirs(OUT, exist_ok=True)
    for f in os.listdir(OUT):
        os.remove(os.path.join(OUT, f))

    cands = load_cands()
    if not cands:
        print("  ❌ 没有候选，先跑 np_diff.py")
        return
    cands = cands[:N_WATCH]
    addrs = [a for a, _ in cands]
    kinds = {a: k for a, k in cands}
    print("  盯 %d 个候选，每秒一帧，共 %d 秒" % (len(cands), SECS))

    pid = find_pid()
    pr = _Proc(pid)
    g = pr.u32(GAPP_ADDR)
    cap = Cap()

    def grab():
        for _ in range(12):
            a = cap.get(timeout=0.5)
            if a is not None:
                return a
        return None

    a = grab()
    over = bot_v6.screen_is_gameover(a) if a is not None else None
    print("  结算画面: %s" % over)
    if over is not False:
        m = VMouse2()
        m.click(640, 738)
        m.close()
        print("  已点『再玩一次』")
        time.sleep(2.0)

    rows = []
    t0 = time.time()
    for k in range(SECS):
        a = grab()
        over = bot_v6.screen_is_gameover(a) if a is not None else None
        if a is not None:
            # 倒计时框实际位置：约 x=1010..1100, y=28..72
            Image.fromarray(a).crop((1000, 22, 1120, 78)).resize((480, 224)).save(
                "%s/w_%02d.png" % (OUT, k))
        vals = read_many(pid, addrs, kinds)
        rows.append(vals)
        print("    t=%2d 采到 %d 个值  结算=%s" % (k, len(vals), over))
        if over:
            print("    （结算，停止）")
            break
        nxt = t0 + (k + 1) * 1.0
        d = nxt - time.time()
        if d > 0:
            time.sleep(d)

    # 拼横条
    tiles = []
    for k in range(len(rows)):
        p = "%s/w_%02d.png" % (OUT, k)
        if os.path.exists(p):
            tiles.append(Image.open(p))
    if tiles:
        W, H = tiles[0].size
        per = 6
        rowsn = (len(tiles) + per - 1) // per
        sheet = Image.new("RGB", (W * per, H * rowsn), (20, 20, 20))
        for i, im in enumerate(tiles):
            sheet.paste(im, ((i % per) * W, (i // per) * H))
        sheet.save("/home/deck/watch_sheet.png")
        print("  横条已存 watch_sheet.png（每行 6 张，按时间顺序）")

    # 打印候选在这 12 秒的值，按「是否逐秒 -1」排序
    print()
    print("  ── 候选值序列（只列逐秒 -1 的）──")
    lines = []
    for a_, k_ in cands:
        seq = [r.get(a_) for r in rows]
        seq = [v for v in seq if v is not None]
        if len(seq) < 5:
            continue
        diffs = [round(seq[i + 1] - seq[i], 2) for i in range(len(seq) - 1)]
        ones = sum(1 for d in diffs if abs(d + 1.0) < 0.05)
        if ones >= len(diffs) * 0.7:
            lines.append((ones, a_, k_, seq))
    lines.sort(reverse=True)
    for ones, a_, k_, seq in lines[:25]:
        tag = "gApp+0x%X" % (a_ - g) if g and g <= a_ < g + 0x20000 else ""
        print("    0x%-12X [%-4s] %d/%d 次恰-1  值=%s %s"
              % (a_, k_, ones, len(seq) - 1, [round(v, 1) for v in seq], tag))
    if not lines:
        print("    （无）")
    cap.stop()
    print()
    print("  下一步：看 watch_sheet.png 读出屏幕上的秒数，")
    print("          再和上面的序列对 —— 值等于屏幕数字的那个就是倒计时。")


if __name__ == "__main__":
    main()
