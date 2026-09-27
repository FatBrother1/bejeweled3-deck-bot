#!/usr/bin/env python3
"""dfreeze.py —— SIGSTOP 双冻结全量差分（不做值域假设）。

上一版 fdump.py 的教训：只转储 [1,61] 的槽，若倒计时存的是
「结束时间戳」或别的刻度，就被值域过滤掉了，交集=0。

本版：冻结 → 全量读可写内存（约 1.1GB）→ 解冻 → 等 Δt → 再冻结 → 全量读
      → 对同一地址求 v1-v2，只要「两次都读到、且差值落在 Δt 附近」就保留。
      完全不管绝对值是多少。

同时做一次「冻结期间内存是否静止」的自检。

用法：
  python3 dfreeze.py 3.0        # 两次冻结间隔 3 秒
  python3 dfreeze.py 3.0 5      # 连续 5 次冻结（差分会更严）
"""
import ctypes, os, re, signal, subprocess, sys, time
sys.path.insert(0, "/home/deck")
import numpy as np
from reader_mem import _IOV, _libc, find_pid

CHUNK = 512 * 1024
W, H = 1280, 800


def rd(pid, addr, size):
    buf = ctypes.create_string_buffer(size)
    lo = _IOV(ctypes.cast(buf, ctypes.c_void_p), size)
    r = _IOV(ctypes.c_void_p(addr), size)
    n = _libc.process_vm_readv(pid, ctypes.byref(lo), 1, ctypes.byref(r), 1, 0)
    if n == size:
        return buf.raw
    return buf.raw[:n] if n and n > 0 else None


def regions(pid):
    out = []
    for l in open("/proc/%d/maps" % pid):
        m = re.match(r"^([0-9a-f]+)-([0-9a-f]+)\s+(\S+)\s+\S+\s+\S+\s*\S*\s*(.*)", l)
        if not m:
            continue
        lo, hi = int(m.group(1), 16), int(m.group(2), 16)
        permission, path = m.group(3), m.group(4).strip()
        if "w" not in permission or hi <= lo or "/dev/" in path or "memfd" in path:
            continue
        out.append((lo, hi))
    return out


def read_all(pid, regs):
    """返回 [(lo, np.int32 数组)]，按 4 字节切。读不到的块跳过。"""
    out = []
    for lo, hi in regs:
        n = hi - lo
        arr = np.zeros((n + 3) // 4, dtype="<i4")
        off, ok = 0, True
        while off < n:
            sz = min(CHUNK, n - off)
            d = rd(pid, lo + off, sz)
            if d is None or len(d) != sz:
                ok = False
                break
            m = len(d) - (len(d) % 4)
            if m:
                arr[off // 4: off // 4 + m // 4] = np.frombuffer(d[:m], "<i4")
            off += sz
        if ok:
            out.append((lo, arr))
    return out


def crop(path):
    subprocess.run(
        ["timeout", "20", "gst-launch-1.0", "-q", "pipewiresrc", "path=93",
         "num-buffers=1", "!", "videoconvert", "!", "videocrop",
         "left=440", "right=%d" % (W - 1160), "top=5", "bottom=%d" % (H - 100),
         "!", "videoscale", "!", "video/x-raw,width=1440", "!",
         "pngenc", "!", "filesink", "location=" + path], capture_output=True)
    return path


def main():
    dt_nominal = float(sys.argv[1]) if len(sys.argv) > 1 else 3.0
    npass = int(sys.argv[2]) if len(sys.argv) > 2 else 2
    pid = find_pid()
    if pid is None:
        print("  ❌ 游戏没在跑")
        return
    regs = regions(pid)
    tot = sum(h - l for l, h in regs)
    print("PID=%d 可写非文件区 %d 个 / %.1f MB" % (pid, len(regs), tot / 1048576))

    snaps, times, frames = [], [], []
    for p in range(1, npass + 1):
        os.kill(pid, signal.SIGSTOP)
        t0 = time.perf_counter()
        try:
            time.sleep(0.2)
            crop("/tmp/tlock/fz_%d.png" % p)
            tf = time.perf_counter()
            snap = read_all(pid, regs)
            td = time.perf_counter()
            # 自检：冻结期间同一地址读两次应完全一致
            chk = None
            if snap:
                a = rd(pid, 0x3936BD78, 4)
                b = rd(pid, 0x3936BD78, 4)
                chk = (a == b)
        finally:
            os.kill(pid, signal.SIGCONT)
        times.append(t0)
        snaps.append(snap)
        frames.append(tf - t0)
        print("  [%d] 冻结 %.2fs 抓到 %.2fs 转储完成 %.2fs  冻结静止自检=%s  区数=%d"
              % (p, time.perf_counter() - t0, tf - t0, td - t0, chk, len(snap)), flush=True)
        if p < npass:
            time.sleep(dt_nominal)

    # 逐对差分（每一对都用「两次冻结的起始时刻差」当 Δt）
    for p in range(1, npass):
        dt = times[p] - times[p - 1]
        print("\n=== 第 %d→%d 次：Δt=%.3fs  差值应≈%.1f ===" % (p, p + 1, dt, dt))
        acc = {}
        for (lo1, a1), (lo2, a2) in zip(snaps[p - 1], snaps[p]):
            if lo1 != lo2:
                continue
            n = min(len(a1), len(a2))
            for s in range(0, n, 4_000_000):
                e = min(s + 4_000_000, n)
                v1 = a1[s:e].astype(np.int64)
                v2 = a2[s:e].astype(np.int64)
                diff = v1 - v2
                ok = (np.abs(diff - dt) < 1.2) & (v1 != v2)
                for k in np.nonzero(ok)[0]:
                    acc[lo1 + (s + int(k)) * 4] = (int(v1[k]), int(v2[k]), int(diff[k]))
        print("  int32 视图中差值≈Δt 的槽：%d 个" % len(acc))
        for a, (v1, v2, d) in sorted(acc.items(), key=lambda kv: kv[1][0])[:60]:
            print("    0x%-10X %12d → %12d  Δ=%d" % (a, v1, v2, d))
        np.savez("/home/deck/dfreeze_%d_%d.npz" % (p, p + 1),
                 A=np.array(sorted(acc), dtype=np.uint64),
                 V1=np.array([acc[a][0] for a in sorted(acc)], dtype=np.int64),
                 V2=np.array([acc[a][1] for a in sorted(acc)], dtype=np.int64))
        # float 视图
        accf = {}
        for (lo1, a1), (lo2, a2) in zip(snaps[p - 1], snaps[p]):
            if lo1 != lo2:
                continue
            n = min(len(a1), len(a2)) // 4
            f1 = a1[:n * 4].view("<f4").astype(np.float64)
            f2 = a2[:n * 4].view("<f4").astype(np.float64)
            fin = np.isfinite(f1) & np.isfinite(f2)
            diff = f1 - f2
            ok = fin & (np.abs(diff - dt) < 1.2) & (f1 != f2) & (np.abs(f2) < 1e7)
            for k in np.nonzero(ok)[0]:
                accf[lo1 + int(k) * 4] = (float(f1[k]), float(f2[k]), float(diff[k]))
        print("  float32 视图中差值≈Δt 的槽：%d 个" % len(accf))
        for a, (v1, v2, d) in sorted(accf.items(), key=lambda kv: kv[1][0])[:60]:
            print("    0x%-10X %14.4f → %14.4f  Δ=%.4f" % (a, v1, v2, d))
        np.savez("/home/deck/dfreezef_%d_%d.npz" % (p, p + 1),
                 A=np.array(sorted(accf), dtype=np.uint64),
                 V1=np.array([accf[a][0] for a in sorted(accf)], dtype=np.float64),
                 V2=np.array([accf[a][1] for a in sorted(accf)], dtype=np.float64))


if __name__ == "__main__":
    main()
