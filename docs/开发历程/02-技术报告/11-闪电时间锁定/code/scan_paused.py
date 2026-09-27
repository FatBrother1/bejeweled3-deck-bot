#!/usr/bin/env python3
"""暂停态扫描 —— 用户暂停游戏并报出倒计时数字，全盘精确匹配。

用法：
  python3 scan_paused.py 37          # 第一次：扫「37」的所有表示
  python3 scan_paused.py 33 37       # 第二次：扫「33」并与 37 的结果求交

表示类（显示 N 秒时，内存可能是）：
  s   : int32 == N
  cs  : int32 ∈ [N*100, (N+1)*100)
  ms  : int32 ∈ [N*1000, (N+1)*1000)
  f4s : float32 ∈ [N, N+1)
  f8s : float64 ∈ [N, N+1)
  f4c / f8c : float ∈ [N*100, (N+1)*100)
  f4m / f8m : float ∈ [N*1000, (N+1)*1000)
暂停时全场冻结 ⇒ 动画计时器不变 ⇒ 两次不同 N 的交集只剩真倒计时。
"""
import ctypes
import os
import re
import sys
import time

import numpy as np

sys.path.insert(0, "/home/deck")
from reader_mem import _IOV, _libc, find_pid, GAPP_ADDR  # noqa: E402

CHUNK = 16 * 1024 * 1024


def raw_read(pid, addr, size):
    buf = ctypes.create_string_buffer(size)
    local = _IOV(ctypes.cast(buf, ctypes.c_void_p), size)
    remote = _IOV(ctypes.c_void_p(addr), size)
    n = _libc.process_vm_readv(pid, ctypes.byref(local), 1,
                               ctypes.byref(remote), 1, 0)
    return buf.raw[:n] if n == size else None


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


def windows_for(n):
    """返回 [(类名, dtype, 步长, 下限, 上限)]。"""
    W = [
        ("s", "<i4", 4, n, n),
        ("cs", "<i4", 4, n * 100, (n + 1) * 100 - 1),
        ("ms", "<i4", 4, n * 1000, (n + 1) * 1000 - 1),
        ("f4s", "<f4", 4, float(n), float(n) + 1.0),
        ("f8s", "<f8", 8, float(n), float(n) + 1.0),
        ("f4c", "<f4", 4, n * 100.0, (n + 1) * 100.0),
        ("f8c", "<f8", 8, n * 100.0, (n + 1) * 100.0),
        ("f4m", "<f4", 4, n * 1000.0, (n + 1) * 1000.0),
        ("f8m", "<f8", 8, n * 1000.0, (n + 1) * 1000.0),
    ]
    return W


def scan_for(pid, regs, n):
    acc = {}
    W = windows_for(n)
    acc = {w[0]: ([], []) for w in W}
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
            for kind, dt, step, vlo, vhi in W:
                cnt = len(raw) // step
                arr = np.frombuffer(raw[:cnt * step], dtype=dt)
                mask = (arr >= vlo) & (arr <= vhi)
                idx = np.nonzero(mask)[0]
                if len(idx):
                    acc[kind][0].append(base + idx.astype(np.uint64) * step)
                    acc[kind][1].append(arr[idx].astype(np.float64))
            off0 += size
    return {k: (np.concatenate(v[0]), np.concatenate(v[1]))
            for k, v in acc.items() if v[0]}


def main():
    n2 = int(sys.argv[1])
    n1 = int(sys.argv[2]) if len(sys.argv) > 2 else None
    pid = find_pid()
    if pid is None:
        print("  ❌ 游戏没在跑")
        return
    g = None
    raw = raw_read(pid, GAPP_ADDR, 4)
    if raw:
        g = int(np.frombuffer(raw, dtype="<u4")[0])
    board = None
    if g:
        rb = raw_read(pid, g + 0xBE8, 4)
        if rb:
            board = int(np.frombuffer(rb, dtype="<u4")[0])
    print("  PID=%d Board=%s  扫描值=%d" % (pid, hex(board) if board else "?", n2),
          flush=True)
    regs = rw_regions(pid)
    t0 = time.perf_counter()
    cur = scan_for(pid, regs, n2)
    print("  命中: " + ", ".join("%s=%d" % (k, len(v[0])) for k, v in cur.items())
          + "  (%.1fs)" % (time.perf_counter() - t0), flush=True)

    if n1 is None:
        np.savez("/home/deck/pause_%d.npz" % n2,
                 **{k + "_a": v[0] for k, v in cur.items()},
                 **{k + "_v": v[1] for k, v in cur.items()})
        # 打印前 40 个
        shown = 0
        for kind, (aa, vv) in sorted(cur.items()):
            for i in range(len(aa)):
                if shown >= 40:
                    break
                addr = int(aa[i])
                rel = ""
                if board and board <= addr < board + 0x4000:
                    rel = "Board+0x%X" % (addr - board)
                elif g and g <= addr < g + 0x20000:
                    rel = "gApp+0x%X" % (addr - g)
                print("    0x%-11X [%s] %.3f %s" % (addr, kind, vv[i], rel))
                shown += 1
        print("  已存 /home/deck/pause_%d.npz（%d 个）"
              % (n2, sum(len(v[0]) for v in cur.values())))
        return

    # ── 与第一次求交 ──
    old = np.load("/home/deck/pause_%d.npz" % n1)
    print("  与 %d 的结果求交…" % n1, flush=True)
    total = 0
    for kind, (aa, vv) in sorted(cur.items()):
        key = kind + "_a"
        if key not in old:
            continue
        oa = old[key]
        ov = old[kind + "_v"]
        if not len(oa):
            continue
        s1 = set(oa.tolist())
        pos = {int(a): float(v) for a, v in zip(oa, ov)}
        both = [(int(a), float(v)) for a, v in zip(aa, vv) if int(a) in s1]
        if not both:
            continue
        print("  [%s] %d 个:" % (kind, len(both)))
        for a, v in both[:60]:
            rel = ""
            if board and board <= a < board + 0x4000:
                rel = "Board+0x%X" % (a - board)
            elif g and g <= a < g + 0x20000:
                rel = "gApp+0x%X" % (a - g)
            oldv = pos.get(a, -1)
            total += 1
            print("    0x%-11X  %d时=%-10.3f  现在=%.3f  %s" % (a, n1, oldv, v, rel))
    print("  交集合计 %d 个" % total)


if __name__ == "__main__":
    main()
