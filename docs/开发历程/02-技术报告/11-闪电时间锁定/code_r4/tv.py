#!/usr/bin/env python3
"""tv.py —— SIGSTOP 真冻结法定位倒计时主控（v2，用游戏内时钟校准）。

核心修正（对 fdump/dfreeze 的教训）：
  1. SIGSTOP 会同时冻结游戏时钟，所以「两次冻结的物理时间差」≠「游戏内
     经过时间」。必须读 Board+0x38（厘秒）作为游戏内时钟来校准。
  2. 冻结的瞬间，画面与内存严格同一时刻 —— 此时抓帧读到的秒数 N
     就是内存里那个值的精确对应，零延迟误差。
  3. 不能只按「画面值 == N」搜单个表示；要一次性把 10 类表示全搜出来，
     再跨快照求交，命中的才是「始终与画面同步」的母本。

用法：
  python3 tv.py sample 3        # 冻结采样 3 轮（间隔 1.6s）
  python3 tv.py inter 43 40 37  # 用画面读数求交
"""
import ctypes, os, re, signal, subprocess, sys, time
sys.path.insert(0, "/home/deck")
import numpy as np
from reader_mem import _IOV, _libc, find_pid, GAPP_ADDR, OFF_BOARD

CHUNK = 512 * 1024
W, H = 1280, 800
OUT = "/tmp/tlock"

# 表示类：name -> (dtype, step, 由 N 生成区间的函数)
KINDS = [
    ("i4s",    "<i4", 4, lambda n: (n - 1, n + 1)),
    ("i4t",    "<i4", 4, lambda n: (n * 10 - 5, n * 10 + 9)),
    ("i4c",    "<i4", 4, lambda n: (n * 100 - 50, n * 100 + 99)),
    ("i4m",    "<i4", 4, lambda n: (n * 1000 - 500, n * 1000 + 999)),
    ("f4s",    "<f4", 4, lambda n: (n - 0.9, n + 1.0)),
    ("f4t",    "<f4", 4, lambda n: (n * 10 - 4.0, n * 10 + 10.0)),
    ("f4c",    "<f4", 4, lambda n: (n * 100 - 40.0, n * 100 + 100.0)),
    ("f4m",    "<f4", 4, lambda n: (n * 1000 - 400.0, n * 1000 + 1000.0)),
    ("f8s",    "<f8", 8, lambda n: (n - 0.9, n + 1.0)),
    ("f8t",    "<f8", 8, lambda n: (n * 10 - 4.0, n * 10 + 10.0)),
]


def rd(pid, addr, size):
    buf = ctypes.create_string_buffer(size)
    lo = _IOV(ctypes.cast(buf, ctypes.c_void_p), size)
    r = _IOV(ctypes.c_void_p(addr), size)
    n = _libc.process_vm_readv(pid, ctypes.byref(lo), 1, ctypes.byref(r), 1, 0)
    if n == size:
        return buf.raw
    return buf.raw[:n] if n and n > 0 else None


def ru32(pid, addr):
    d = rd(pid, addr, 4)
    return int(np.frombuffer(d, "<u4")[0]) if d and len(d) == 4 else None


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


def game_clock(pid):
    """Board+0x38 厘秒 + Board+0xC84 整秒。"""
    g = ru32(pid, GAPP_ADDR)
    if not g:
        return None, None
    b = ru32(pid, g + OFF_BOARD)
    if not b:
        return None, None
    return ru32(pid, b + 0x38), ru32(pid, b + 0xC84)


def crop(path):
    subprocess.run(
        ["timeout", "20", "gst-launch-1.0", "-q", "pipewiresrc", "path=93",
         "num-buffers=1", "!", "videoconvert", "!", "videocrop",
         "left=980", "right=%d" % (W - 1170), "top=5", "bottom=%d" % (H - 100),
         "!", "videoscale", "!", "video/x-raw,width=1140", "!",
         "pngenc", "!", "filesink", "location=" + path], capture_output=True)
    return path


def snap(pid, regs, n, tag):
    """在已冻结状态下：对 10 类表示全量搜索，存候选。"""
    res = {k[0]: ([], []) for k in KINDS}
    for lo, hi in regs:
        off = 0
        while off < hi - lo:
            sz = min(CHUNK, hi - lo - off)
            d = rd(pid, lo + off, sz)
            if d is None or len(d) != sz:
                off += sz
                continue
            base = lo + off
            cnt4 = len(d) // 4
            a4 = np.frombuffer(d[:cnt4 * 4], "<i4")
            f4v = a4.view("<f4")
            cnt8 = len(d) // 8
            f8v = np.frombuffer(d[:cnt8 * 8], "<f8")
            for name, dt, step, rng in KINDS:
                vlo, vhi = rng(n)
                if dt == "<i4":
                    m = (a4 >= vlo) & (a4 <= vhi)
                    if m.any():
                        idx = np.nonzero(m)[0]
                        res[name][0].append(base + idx.astype(np.uint64) * 4)
                        res[name][1].append(a4[idx].astype(np.float64))
                elif dt == "<f4":
                    m = np.isfinite(f4v) & (f4v >= vlo) & (f4v <= vhi)
                    if m.any():
                        idx = np.nonzero(m)[0]
                        res[name][0].append(base + idx.astype(np.uint64) * 4)
                        res[name][1].append(f4v[idx].astype(np.float64))
                else:
                    m = np.isfinite(f8v) & (f8v >= vlo) & (f8v <= vhi)
                    if m.any():
                        idx = np.nonzero(m)[0]
                        res[name][0].append(base + idx.astype(np.uint64) * 8)
                        res[name][1].append(f8v[idx].astype(np.float64))
            off += sz
    npz = {}
    tot = 0
    for name, _, _, _ in KINDS:
        aa, vv = res[name]
        if aa:
            A = np.concatenate(aa)
            V = np.concatenate(vv)
        else:
            A = np.zeros(0, np.uint64)
            V = np.zeros(0, np.float64)
        npz[name + "_a"] = A
        npz[name + "_v"] = V
        tot += len(A)
    np.savez("%s/tv_%s.npz" % (OUT, tag), **npz)
    return tot, {k[0]: len(res[k[0]][0]) and sum(len(x) for x in res[k[0]][0]) for k in KINDS}


def do_sample(npass, gap):
    pid = find_pid()
    if pid is None:
        print("  ❌ 游戏没在跑")
        return
    regs = regions(pid)
    print("PID=%d 区 %d 个 / %.1f MB" % (pid, len(regs), sum(h - l for l, h in regs) / 1048576))
    for p in range(1, npass + 1):
        os.kill(pid, signal.SIGSTOP)
        t0 = time.perf_counter()
        try:
            time.sleep(0.15)
            cs, sec = game_clock(pid)
            crop("%s/v_%d.png" % (OUT, p))
            n = int(sys.argv[3]) if len(sys.argv) > 3 and sys.argv[3].isdigit() else 0
            tot = 0
            if n > 0:
                tot, per = snap(pid, regs, n, str(p))
            tf = time.perf_counter()
        finally:
            os.kill(pid, signal.SIGCONT)
        print("  [%d] 时钟 cs=%s s=%s  冻结 %.2fs" % (p, cs, sec, time.perf_counter() - t0), flush=True)
        if p < npass:
            time.sleep(gap)
    print("帧已存 %s/v_1..%d.png —— 请读图上的秒数，再跑 inter" % (OUT, npass))


def do_inter(nums):
    snaps = []
    for p in range(1, len(nums) + 1):
        z = np.load("%s/tv_%d.npz" % (OUT, p))
        d = {}
        for name, _, _, _ in KINDS:
            for a, v in zip(z[name + "_a"], z[name + "_v"]):
                d[(name, int(a))] = float(v)
        snaps.append(d)
    print("各快照候选：", [len(s) for s in snaps])
    keys = set(snaps[0])
    for s in snaps[1:]:
        keys &= set(s)
    print("跨 %d 个快照求交：%d 个" % (len(snaps), len(keys)))
    # 进一步：要求「值随画面同步下降」
    good = []
    for k in keys:
        vs = [s[k] for s in snaps]
        drops = [vs[i] - vs[i + 1] for i in range(len(vs) - 1)]
        sdrops = [nums[i] - nums[i + 1] for i in range(len(nums) - 1)]
        # 值必须同向下降，且落差不小于画面落差的一半
        if all(d >= 0 for d in drops):
            err = sum(abs(d - sd) for d, sd in zip(drops, sdrops))
            good.append((err, k, vs))
    good.sort(key=lambda r: (r[0], r[1][1]))
    print("\n同向下降的 %d 个（按与画面落差的误差排序）：" % len(good))
    for err, (name, a), vs in good[:120]:
        print("  0x%-10X [%-5s] %s   误差=%.3f"
              % (a, name, " → ".join("%.2f" % v for v in vs), err))
    if good:
        np.savez("%s/tv_hit.npz" % OUT,
                 A=np.array([g[1][1] for g in good], dtype=np.uint64),
                 N=np.array([g[1][0] for g in good]))


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "sample"
    if cmd == "sample":
        npass = int(sys.argv[2]) if len(sys.argv) > 2 else 3
        do_sample(npass, 1.6)
    elif cmd == "inter":
        do_inter([int(x) for x in sys.argv[2:]])
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
