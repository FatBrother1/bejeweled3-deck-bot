#!/usr/bin/env python3
"""dfscan.py —— 全内存差分扫描：找「按固定速率下降」的槽位。

为什么用它：上一轮结论是倒计时主控随渲染结构体被 `rep movsl` 块拷贝搬运，
按「画面值 == N」去搜会被大量副本与复用暂存槽淹没（0x109CBEC 就是这么死的）。
反过来看：主控一定比它的副本更连续地按秒递减 —— 多趟差分直接筛「速率」。

判据（每趟之间）：
  值下降、幅度落在 (0, 5000/s)、并且当前值落在真值域 [1, 360000]
  只有「每一趟都命中」的地址才留下 —— 主控必须每趟都在降。

用法：
  python3 dfscan.py 3           # 3 趟，全量可写非文件内存（~1.1GB，约 4s/3趟）
  python3 dfscan.py 3 fast      # 只扫 gApp/Board 所在区 + 2MB 静态数据段（~27MB）
"""
import ctypes, re, sys, time
sys.path.insert(0, "/home/deck")
import numpy as np
from reader_mem import _IOV, _libc, find_pid, GAPP_ADDR, OFF_BOARD

CHUNK = 512 * 1024        # 512KB —— 实测 1MB 以上偶发短读
SLICE = 4_000_000         # 每次比较 4M 个 int32 = 16MB
MAXV = 360000
MAXRATE = 5000.0


def rd(pid, addr, size):
    buf = ctypes.create_string_buffer(size)
    lo = _IOV(ctypes.cast(buf, ctypes.c_void_p), size)
    r = _IOV(ctypes.c_void_p(addr), size)
    n = _libc.process_vm_readv(pid, ctypes.byref(lo), 1, ctypes.byref(r), 1, 0)
    if n == size:
        return buf.raw
    if n and n > 0:
        return buf.raw[:n]
    return None


def read_val(pid, addr, kind):
    d = rd(pid, addr, 4)
    if d is None or len(d) != 4:
        return None
    return float(np.frombuffer(d, "<f4" if kind == "f4" else "<i4")[0])


def all_regions(pid, fast=False):
    tgt = []
    if fast:
        raw = rd(pid, GAPP_ADDR, 4)
        gapp = int(np.frombuffer(raw, "<u4")[0]) if raw else 0
        raw = rd(pid, gapp + OFF_BOARD, 4)
        board = int(np.frombuffer(raw, "<u4")[0]) if raw else 0
        tgt = [gapp, board]
        print("      gApp=0x%X Board=0x%X" % (gapp, board))
    out = []
    for l in open("/proc/%d/maps" % pid):
        m = re.match(r"^([0-9a-f]+)-([0-9a-f]+)\s+(\S+)\s+\S+\s+\S+\s*\S*\s*(.*)", l)
        if not m:
            continue
        lo, hi = int(m.group(1), 16), int(m.group(2), 16)
        perm, path = m.group(3), m.group(4).strip()
        if "w" not in perm or hi <= lo:
            continue
        if "/dev/" in path or "memfd" in path:
            continue
        if fast:
            hit = any(lo <= t < hi for t in tgt)
            small = ("/" not in path) and (hi - lo) <= (4 << 20)
            if not (hit or small):
                continue
        out.append((lo, hi))
    return out


def read_all(pid, regs):
    out = []
    for lo, hi in regs:
        n = hi - lo
        arr = np.zeros((n + 3) // 4, dtype="<i4")
        off = 0
        bad = False
        while off < n:
            sz = min(CHUNK, n - off)
            d = rd(pid, lo + off, sz)
            if d is None or len(d) != sz:
                bad = True
                break
            m = len(d) - (len(d) % 4)
            if m:
                arr[off // 4: off // 4 + m // 4] = np.frombuffer(d[:m], "<i4")
            off += sz
        if bad:
            continue
        out.append((lo, hi, arr))
    return out


def pair_scan(prev, cur, dt, cand_i, cand_f):
    ni = nf = 0
    for (lo, hi, pv0), (lo2, hi2, cv0) in zip(prev, cur):
        if lo != lo2 or hi != hi2:
            continue
        n = min(len(pv0), len(cv0))
        for s in range(0, n, SLICE):
            e = min(s + SLICE, n)
            pv, cv = pv0[s:e], cv0[s:e]
            # --- int32 视图 ---
            pi = pv.astype(np.int64)
            ci = cv.astype(np.int64)
            rate_i = (ci - pi) / dt
            mi = (rate_i < 0) & (rate_i > -MAXRATE) & (ci >= 1) & (ci <= MAXV) & (pi >= 1) & (pi <= MAXV)
            for k in np.nonzero(mi)[0]:
                a = lo + (s + int(k)) * 4
                cand_i.setdefault(a, []).append(float(rate_i[k]))
                ni += 1
            # --- float32 视图 ---
            pf = pv.view("<f4").astype(np.float64)
            cf = cv.view("<f4").astype(np.float64)
            rate_f = (cf - pf) / dt
            mf = ((rate_f < 0) & (rate_f > -MAXRATE) & np.isfinite(rate_f)
                  & (cf > 0.01) & (cf < MAXV) & (pf > 0.01) & (pf < MAXV))
            for k in np.nonzero(mf)[0]:
                a = lo + (s + int(k)) * 4
                cand_f.setdefault(a, []).append(float(rate_f[k]))
                nf += 1
    return ni, nf


def show(pid, d, kind, npairs):
    rows = sorted((sum(rs) / len(rs), a, rs) for a, rs in d.items())
    print("  --- %s：速率接近 -1 / -10 / -100 / -1000 的候选 ---" % kind)
    n = 0
    for avg, a, rs in rows:
        if any(abs(avg - t) < 0.25 * abs(t) for t in (-1, -10, -100, -1000)):
            v = read_val(pid, a, kind)
            print("    ★ 0x%-9X 速率=%10.3f /s  当前=%12.3f  各趟=%s"
                  % (a, avg, v if v is not None else -1, " ".join("%.2f" % r for r in rs)))
            n += 1
            if n >= 40:
                break
    if n == 0:
        print("      （无）")
    print("  --- %s：全部候选按速率绝对值排序 前 30 ---" % kind)
    for avg, a, rs in rows[:30]:
        v = read_val(pid, a, kind)
        print("      0x%-9X 速率=%10.3f /s  当前=%12.3f" % (a, avg, v if v is not None else -1))


def main():
    npass = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else 3
    fast = "fast" in sys.argv
    pid = find_pid()
    if pid is None:
        print("  ❌ 游戏没在跑")
        return
    regs = all_regions(pid, fast)
    tot = sum(h - l for l, h in regs)
    print("PID=%d  区域 %d 个 / %.1f MB  (%s)"
          % (pid, len(regs), tot / 1048576.0, "fast" if fast else "全量"), flush=True)
    t0 = time.perf_counter()
    prev = read_all(pid, regs)
    tp = time.perf_counter()
    print("  第1趟 %.2fs  成功区 %d/%d" % (tp - t0, len(prev), len(regs)), flush=True)
    cand_i, cand_f = {}, {}
    for p in range(2, npass + 1):
        cur = read_all(pid, regs)
        tc = time.perf_counter()
        dt = tc - tp
        ni, nf = pair_scan(prev, cur, dt, cand_i, cand_f)
        print("  第%d趟 %.2fs  dt=%.3fs  本趟下降槽 i4=%d f4=%d"
              % (p, tc - tp, dt, ni, nf), flush=True)
        prev = cur
        tp = tc
    npairs = npass - 1
    fin_i = {a: r for a, r in cand_i.items() if len(r) == npairs}
    fin_f = {a: r for a, r in cand_f.items() if len(r) == npairs}
    print("\n=== 每一趟都在降的槽：i4=%d  f4=%d（共 %d 趟）===" % (len(fin_i), len(fin_f), npass))
    show(pid, fin_i, "i4", npairs)
    show(pid, fin_f, "f4", npairs)
    np.savez("/home/deck/dfscan_result.npz",
             addrs=np.array(sorted(set(fin_i) | set(fin_f)), dtype=np.uint64))


if __name__ == "__main__":
    main()
