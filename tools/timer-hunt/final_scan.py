#!/usr/bin/env python3
"""最终定位倒计时：numpy 精确值匹配。

★ 现在条件齐了 ★
  · 全进程扫描 1.0 秒（numpy 向量化）
  · 倒计时框位置已确认：原图 x=500..620, y=20..80（实测清晰显示 0:07）
  · 判据已修好，不会再误判结算

★ 做法 ★
  开新局后立刻：
    1. 抓一帧 → 存图（我会读出秒数）
    2. 立刻全进程扫描，找出所有「int/float/double == 该秒数」的地址
  因为扫描只要 1 秒，同一局内可以反复做几轮；
  真正的倒计时会在每一轮都恰好等于当时的屏幕秒数。

  为避免人工读图卡住流程，脚本先把「每个候选地址在各轮的值」记下来，
  再连同每轮的截图一起给我 —— 我读图后就能确定是哪个。
"""
import ctypes
import os
import re
import sys
import time

import numpy as np

sys.path.insert(0, "/home/deck")
from reader_mem import _Proc, find_pid, GAPP_ADDR, OFF_BOARD, _IOV, _libc   # noqa: E402
from cap2 import Cap                                                         # noqa: E402
from vmouse2 import VMouse2                                                  # noqa: E402
from PIL import Image                                                        # noqa: E402
import bot_v6                                                                # noqa: E402

CHUNK = 16 * 1024 * 1024
OUT = "/home/deck/final"
ROUNDS = 6


def rw_regions(pid):
    out = []
    with open("/proc/%d/maps" % pid) as f:
        for line in f:
            m = re.match(r"^([0-9a-f]+)-([0-9a-f]+)\s+(\S+)\s+(\S+)?", line)
            if not m:
                continue
            lo, hi, perm = int(m.group(1), 16), int(m.group(2), 16), m.group(3)
            path = m.group(4) or ""
            if "w" not in perm or hi - lo <= 0:
                continue
            if "/dev/" in path or ".pak" in path or ".so" in path:
                continue
            out.append((lo, hi))
    return out


def scan_value(pid, regs, want):
    """找出所有 == want 的地址。want 可为 int 或 float。"""
    hits = set()
    wi = np.int32(want) if float(want).is_integer() else None
    wf = np.float32(want)
    wd = np.float64(want)
    for lo, hi in regs:
        off0 = 0
        while off0 < hi - lo:
            size = min(CHUNK, hi - lo - off0)
            size -= size % 8
            if size <= 0:
                break
            buf = ctypes.create_string_buffer(size)
            local = _IOV(ctypes.cast(buf, ctypes.c_void_p), size)
            remote = _IOV(ctypes.c_void_p(lo + off0), size)
            n = _libc.process_vm_readv(pid, ctypes.byref(local), 1,
                                       ctypes.byref(remote), 1, 0)
            if n <= 0:
                off0 += size
                continue
            raw = buf.raw[:n // 8 * 8]
            base = lo + off0
            if wi is not None:
                a = np.frombuffer(raw, dtype="<i4")
                for idx in np.nonzero(a == wi)[0].tolist():
                    hits.add((base + idx * 4, "i"))
            a = np.frombuffer(raw, dtype="<f4")
            for idx in np.nonzero(a == wf)[0].tolist():
                hits.add((base + idx * 4, "f"))
            a = np.frombuffer(raw, dtype="<f8")
            for idx in np.nonzero(a == wd)[0].tolist():
                hits.add((base + idx * 8, "d"))
            off0 += size
    return hits


def main():
    os.makedirs(OUT, exist_ok=True)
    for f in os.listdir(OUT):
        os.remove(os.path.join(OUT, f))
    pid = find_pid()
    if pid is None:
        print("  ❌ 游戏没在跑")
        return
    pr = _Proc(pid)
    g = pr.u32(GAPP_ADDR)
    regs = rw_regions(pid)
    print("  PID=%d gApp=%s  可写段 %d 个 / %.0f MB"
          % (pid, hex(g) if g else None, len(regs),
             sum(h - l for l, h in regs) / 1e6))

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
        print("  已点『再玩一次』，等 2.0 秒")
        time.sleep(2.0)

    print()
    print("  ═══ 逐轮扫描：存图 + 记下所有候选 ═══")
    rounds = []
    for r in range(ROUNDS):
        a = grab()
        over = bot_v6.screen_is_gameover(a) if a is not None else None
        if a is not None:
            # 精确坐标：倒计时框 x=500..620, y=20..80
            Image.fromarray(a).crop((495, 15, 625, 85)).save("%s/r_%d.png" % (OUT, r))
            Image.fromarray(a).save("%s/full_%d.png" % (OUT, r))
        # 这一轮为「找出所有 0..61 的地址」
        t0 = time.perf_counter()
        allhits = set()
        for v in range(0, 62):
            allhits |= scan_value(pid, regs, v)
        dt = time.perf_counter() - t0
        rounds.append(allhits)
        print("    第 %d 轮：%d 个候选（扫 62 个值，%.1fs）  结算=%s"
              % (r, len(allhits), dt, over))
        if over:
            print("    （结算，停止）")
            break

    if len(rounds) < 2:
        print("  轮数太少")
        cap.stop()
        return

    common = set.intersection(*rounds)
    print()
    print("  %d 轮都出现的地址: %d 个" % (len(rounds), len(common)))
    with open("/home/deck/final_cands.txt", "w") as f:
        for addr, kind in sorted(common):
            f.write("0x%X %s\n" % (addr, kind))
    # 按区域归类
    in_g = [x for x in common if g and g <= x[0] < g + 0x20000]
    print("  其中落在 gApp 段的: %d" % len(in_g))
    for addr, kind in sorted(in_g)[:20]:
        print("    gApp+0x%X [%s]" % (addr - g, kind))
    print("  已存 /home/deck/final_cands.txt")
    cap.stop()
    print()
    print("  截图在 %s（每轮一张 r_N.png，就是倒计时框）" % OUT)


if __name__ == "__main__":
    main()
