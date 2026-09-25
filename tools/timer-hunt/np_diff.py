#!/usr/bin/env python3
"""找闪电倒计时 —— 纯 numpy 逐位比对版（不建字典）。

★ 上一版为什么失败 ★
  我把 105 万个候选塞进 Python dict，导致每遍扫描 3.3 秒（开销全在 dict 上），
  10 遍耗掉 33 秒，跨过了局末 —— 拿到的全是「冻结后的阶梯值」。
  而且 dict 里绝大多数是无关的小整数，信噪比极低。

★ 本版做法 ★
  1. 第一遍：把每段原始字节留在内存里（只留 < 512MB 的段，够用）
  2. 精确等 6.0 秒
  3. 第二遍：读同样的段
  4. 用 numpy 逐位相减，直接找出「降幅 ≈ 6」的位置
     全程零 Python 循环、零字典，应该 1~2 秒完成一遍

  这样两次采样间隔严格可控，且比对的地址空间完整。
"""
import ctypes
import re
import sys
import time

import numpy as np

sys.path.insert(0, "/home/deck")
from reader_mem import _Proc, find_pid, GAPP_ADDR, OFF_BOARD, _IOV, _libc   # noqa: E402
from cap2 import Cap                                                         # noqa: E402
from vmouse2 import VMouse2                                                  # noqa: E402
import bot_v6                                                                # noqa: E402

CHUNK = 16 * 1024 * 1024
BUDGET = 600 * 1024 * 1024      # 原始字节总预算


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


def grab_all(pid, regs, budget=BUDGET):
    """读回所有段，返回 [(lo, nbytes, bytearray), ...]。超预算的段跳过。"""
    out = []
    used = 0
    for lo, hi in regs:
        size = hi - lo
        if used + size > budget:
            continue
        off0 = 0
        parts = []
        ok = True
        while off0 < size:
            n = min(CHUNK, size - off0)
            buf = ctypes.create_string_buffer(n)
            local = _IOV(ctypes.cast(buf, ctypes.c_void_p), n)
            remote = _IOV(ctypes.c_void_p(lo + off0), n)
            got = _libc.process_vm_readv(pid, ctypes.byref(local), 1,
                                         ctypes.byref(remote), 1, 0)
            if got <= 0:
                ok = False
                break
            parts.append(buf.raw[:got])
            off0 += got
        if ok and parts:
            data = b"".join(parts)
            out.append((lo, len(data), data))
            used += len(data)
    return out, used


def main():
    pid = find_pid()
    if pid is None:
        print("  ❌ 游戏没在跑")
        return
    pr = _Proc(pid)
    g = pr.u32(GAPP_ADDR)
    print("  PID=%d gApp=%s" % (pid, hex(g) if g else None))

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

    regs = rw_regions(pid)
    print("  可写区域 %d 个，共 %.0f MB" % (len(regs), sum(h - l for l, h in regs) / 1e6))

    t0 = time.perf_counter()
    A, used = grab_all(pid, regs)
    tA = time.perf_counter() - t0
    print("  第一遍：%d 段 / %.0f MB（%.2f 秒）" % (len(A), used / 1e6, tA))

    WAIT = 6.0
    print("  精确等 %.1f 秒…" % WAIT)
    t1 = time.perf_counter()
    time.sleep(WAIT)
    elapsed = time.perf_counter() - t1

    t0 = time.perf_counter()
    B, _ = grab_all(pid, regs)
    tB = time.perf_counter() - t0
    print("  第二遍：%d 段（%.2f 秒）  实际间隔 %.2f 秒" % (len(B), tB, elapsed))

    Bmap = {lo: (n, d) for lo, n, d in B}
    print()
    print("  ── numpy 逐位比对，找降幅 ≈ %.1f 的位置 ──" % elapsed)
    results = []
    for lo, n, da in A:
        if lo not in Bmap:
            continue
        nb, db = Bmap[lo]
        m = min(n, nb)
        m8 = m // 8 * 8
        if m8 < 8:
            continue
        ra = np.frombuffer(da[:m8], dtype="<u1")
        rb = np.frombuffer(db[:m8], dtype="<u1")
        # 先按 int32 比
        ia = np.frombuffer(da[:m8], dtype="<i4")
        ib = np.frombuffer(db[:m8], dtype="<i4")
        drop = ia.astype("int64") - ib.astype("int64")
        # 只关心「降幅接近 elapsed」且两值都在合理区间
        sel = np.nonzero(
            (np.abs(drop - elapsed) <= 1.5) &
            (ib >= 0) & (ib <= 70) & (ia >= 0) & (ia <= 70)
        )[0]
        for idx in sel.tolist():
            results.append((lo + idx * 4, "s_i", int(ia[idx]), int(ib[idx])))
        # 毫秒
        sel = np.nonzero(
            (np.abs(drop - elapsed * 1000) <= 1500) &
            (ib >= 0) & (ib <= 70000)
        )[0]
        for idx in sel.tolist():
            results.append((lo + idx * 4, "ms", int(ia[idx]), int(ib[idx])))
        # float32
        fa = np.frombuffer(da[:m8], dtype="<f4").astype("float64")
        fb = np.frombuffer(db[:m8], dtype="<f4").astype("float64")
        good = np.isfinite(fa) & np.isfinite(fb)
        fdrop = np.where(good, fa - fb, -1e9)
        sel = np.nonzero(
            (np.abs(fdrop - elapsed) <= 1.5) &
            (fb >= 0) & (fb <= 70)
        )[0]
        for idx in sel.tolist():
            results.append((lo + idx * 4, "s_f", float(fa[idx]), float(fb[idx])))
        # float64
        m16 = m // 8 * 8
        dda = np.frombuffer(da[:m16], dtype="<f8")
        ddb = np.frombuffer(db[:m16], dtype="<f8")
        good = np.isfinite(dda) & np.isfinite(ddb)
        ddrop = np.where(good, dda - ddb, -1e9)
        sel = np.nonzero(
            (np.abs(ddrop - elapsed) <= 1.5) &
            (ddb >= 0) & (ddb <= 70)
        )[0]
        for idx in sel.tolist():
            results.append((lo + idx * 8, "s_d", float(dda[idx]), float(ddb[idx])))

    # 去重、排序（优先接近整秒、值域像倒计时）
    uniq = {}
    for addr, kind, va, vb in results:
        uniq[(addr, kind)] = (va, vb)
    ranked = sorted(uniq.items(),
                    key=lambda kv: (abs((kv[1][0] - kv[1][1]) - elapsed), kv[0][0]))
    print("    命中 %d 个（去重后 %d）" % (len(results), len(ranked)))
    print()
    for (addr, kind), (va, vb) in ranked[:40]:
        tag = ""
        if g and g <= addr < g + 0x20000:
            tag = "gApp+0x%X" % (addr - g)
        print("    0x%-12X [%-4s] %.2f → %.2f  (降 %.2f) %s"
              % (addr, kind, va, vb, va - vb, tag))
    with open("/home/deck/np2_cands.txt", "w") as f:
        for (addr, kind), (va, vb) in ranked:
            f.write("0x%X %s %.3f %.3f\n" % (addr, kind, va, vb))
    print("  已存 /home/deck/np2_cands.txt")
    cap.stop()


if __name__ == "__main__":
    main()
