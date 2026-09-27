#!/usr/bin/env python3
"""倒计时定位 v5 —— 等速下降 × 3 区间 + 扩展率等级（含 60/s 帧计时）。

v4 教训：19 个下降者几乎全是堆里被复用的动画计时器（0xA057EA4 前脚 35.66
后脚就乱跳成 342/641 —— 和上轮 0xF98DBF0 同一签名）。
v5 收紧：
  · 一局之内 4 次采样（间隔 5s），要求 3 个区间「同一速率」严格下降
    （动画计时器撑不过 15 秒；被复用的槽更不可能等速）。
  · 率等级补上 30/s、60/s（帧计时）。
"""
import ctypes
import os
import re
import sys
import time

import numpy as np

sys.path.insert(0, "/home/deck")
from reader_mem import _IOV, _libc, find_pid, GAPP_ADDR  # noqa: E402
from cap2 import Cap  # noqa: E402
from PIL import Image  # noqa: E402

CHUNK = 16 * 1024 * 1024
GAP = 5.0
RATE_TOL = {1.0: 0.3, 10.0: 3.0, 30.0: 8.0, 60.0: 15.0, 100.0: 30.0,
            1000.0: 300.0}
CLASSES = (
    ("s",   "<i4", 4, 1, 61),
    ("ms",  "<i4", 4, 100, 61000),
    ("f4",  "<f4", 4, 0.2, 65.0),
    ("f8",  "<f8", 8, 0.2, 65.0),
    ("f4b", "<f4", 4, 500.0, 65000.0),
    ("f8b", "<f8", 8, 500.0, 65000.0),
)
DT = {c[0]: (c[1], c[2]) for c in CLASSES}


def raw_read(pid, addr, size):
    buf = ctypes.create_string_buffer(size)
    local = _IOV(ctypes.cast(buf, ctypes.c_void_p), size)
    remote = _IOV(ctypes.c_void_p(addr), size)
    n = _libc.process_vm_readv(pid, ctypes.byref(local), 1,
                               ctypes.byref(remote), 1, 0)
    return buf.raw[:n] if n == size else None


def read_val(pid, addr, kind):
    dt, step = DT[kind]
    raw = raw_read(pid, addr, step)
    if raw is None:
        return None
    return float(np.frombuffer(raw, dtype=dt)[0])


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


def scan_once(pid, regs):
    acc = {c[0]: ([], []) for c in CLASSES}
    for lo, hi in regs:
        off0 = 0
        while off0 < hi - lo:
            size = min(CHUNK, hi - lo - off0)
            size -= size % 8
            if size <= 0:
                break
            raw = raw_read(pid, lo + off0, size)
            if raw is None:
                off0 += size
                continue
            base = lo + off0
            for kind, dt, step, vlo, vhi in CLASSES:
                n = len(raw) // step
                arr = np.frombuffer(raw[:n * step], dtype=dt)
                mask = (arr >= vlo) & (arr <= vhi)
                idx = np.nonzero(mask)[0]
                if len(idx):
                    acc[kind][0].append(base + idx.astype(np.uint64) * step)
                    acc[kind][1].append(arr[idx].astype(np.float64))
            off0 += size
    return {k: (np.concatenate(v[0]), np.concatenate(v[1]))
            for k, v in acc.items() if v[0]}


def fallers(prev, cur, dt, rate_set):
    out = {}
    for kind in prev:
        if kind not in cur:
            continue
        pa, pv = prev[kind]
        ca, cv = cur[kind]
        order = np.argsort(ca)
        ca, cv = ca[order], cv[order]
        lo = np.searchsorted(ca, pa)
        hi = np.searchsorted(ca, pa, side="right")
        hit = np.nonzero(hi > lo)[0]
        if not len(hit):
            continue
        rate = (pv[hit] - cv[lo[hit]]) / dt
        good = np.zeros(len(hit), dtype=bool)
        for k, tol in RATE_TOL.items():
            good |= np.abs(rate - k) < tol
        if good.any():
            out[kind] = (pa[hit][good], cv[lo[hit]][good])
    return out


def grab(cap):
    for _ in range(12):
        a = cap.get(timeout=0.5)
        if a is not None:
            return a
    return None


def main():
    import bot_v6
    from vmouse2 import VMouse2
    pid = find_pid()
    g = board = None
    raw = raw_read(pid, GAPP_ADDR, 4)
    if raw:
        g = int(np.frombuffer(raw, dtype="<u4")[0])
        rb = raw_read(pid, g + 0xBE8, 4)
        if rb:
            board = int(np.frombuffer(rb, dtype="<u4")[0])
    regs = rw_regions(pid)
    print("  PID=%d Board=%s" % (pid, hex(board) if board else "?"), flush=True)

    cap = Cap()
    vm = VMouse2()
    f = grab(cap)
    if f is not None and bot_v6.screen_is_gameover(f):
        vm.click(640, 738)
        print("    （结算 → 点『再玩一次』）", flush=True)
        time.sleep(4.5)

    NS = 4
    samples = []
    for i in range(NS):
        t = time.perf_counter()
        if i == 0:
            S = scan_once(pid, regs)
        else:
            time.sleep(GAP)
            t = time.perf_counter()
            if i == NS - 1:
                S = None      # 末轮只回读，不全扫
            else:
                S = scan_once(pid, regs)
        samples.append((t, S))
        print("  采样 %d 完成 (%.1fs)" % (i, time.perf_counter() - t), flush=True)

    # S0→S1→S2 全扫下降者；S3 回读验证等速
    t0, S0 = samples[0]
    t1, S1 = samples[1]
    t2, S2 = samples[2]
    t3, _ = samples[3]
    A = fallers(S0, S1, t1 - t0, RATE_TOL)
    del S0
    B = fallers(A, S2, t2 - t1, RATE_TOL)
    del S1, A
    print("  S1→S2 后存活: %d" % sum(len(v[0]) for v in B.values()), flush=True)

    print()
    print("  ═══ 等速下降幸存者（3 区间同速率）═══")
    rows = []
    for kind, (aa, vv) in B.items():
        for i in range(len(aa)):
            addr = int(aa[i])
            v2 = float(vv[i])
            v3 = read_val(pid, addr, kind)
            if v3 is None:
                continue
            r12 = None
            # 用 S2 值与 S3 值算第三区间速率
            rate3 = (v2 - v3) / (t3 - t2)
            rate_ok3 = any(abs(rate3 - k) < tol for k, tol in RATE_TOL.items())
            if not rate_ok3:
                continue
            rel = ""
            if board and board <= addr < board + 0x4000:
                rel = "Board+0x%X" % (addr - board)
            elif g and g <= addr < g + 0x20000:
                rel = "gApp+0x%X" % (addr - g)
            rows.append((addr, kind, v3, rate3, rel))
            print("    0x%-11X [%s] 值=%-12.3f 速率=%8.2f/s %s"
                  % (addr, kind, v3, rate3, rel))
    with open("/home/deck/timer_fallers.txt", "w") as fo:
        for addr, kind, v, r, rel in rows:
            fo.write("0x%X %s %.4f rate=%.2f %s\n" % (addr, kind, v, r, rel))
    print("  共 %d 个 → /home/deck/timer_fallers.txt" % len(rows))
    cap.stop()
    vm.close()


if __name__ == "__main__":
    main()
