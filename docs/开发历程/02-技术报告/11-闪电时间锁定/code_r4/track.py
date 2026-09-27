#!/usr/bin/env python3
"""闪电倒计时主控定位 v1 —— 数据段动态槽位追踪。

原理：倒计时主控必然在游戏运行时以固定步长递减（每秒 -1，秒制）。
      只读「游戏静态数据段」（约 2MB，含 gApp/Board/渲染属性暂存槽），
      以 ~300Hz 采样，同时按 int32 与 float32 两种视图筛出
      「单调不增且确实下降」的槽位。

用法：
  python3 track.py scan  8      # 粗筛 8 秒
  python3 track.py track 20     # 精跟 20 秒（用上次 scan 的候选）
"""
import ctypes, os, re, sys, time
sys.path.insert(0, "/home/deck")
import numpy as np
from reader_mem import _IOV, _libc, find_pid, GAPP_ADDR

CAND = "/home/deck/track_cand.npz"


def rd(pid, addr, size):
    buf = ctypes.create_string_buffer(size)
    lo = _IOV(ctypes.cast(buf, ctypes.c_void_p), size)
    r = _IOV(ctypes.c_void_p(addr), size)
    n = _libc.process_vm_readv(pid, ctypes.byref(lo), 1, ctypes.byref(r), 1, 0)
    return buf.raw[:n] if n == size else None


def region_of(pid, addr):
    for l in open("/proc/%d/maps" % pid):
        m = re.match(r"^([0-9a-f]+)-([0-9a-f]+)\s+(\S+)\s+\S+\s+\S+\s*\S*\s*(.*)", l)
        if not m:
            continue
        lo, hi = int(m.group(1), 16), int(m.group(2), 16)
        if lo <= addr < hi:
            return lo, hi, m.group(3), m.group(4).strip()
    return None


def get_region(pid):
    """优先取包含 GAPP_ADDR 的可写区；否则取最大匿名可写可执行区。"""
    r = region_of(pid, GAPP_ADDR)
    if r and "w" in r[2] and "/" not in r[3]:
        return r[0], r[1]
    best = None
    for l in open("/proc/%d/maps" % pid):
        m = re.match(r"^([0-9a-f]+)-([0-9a-f]+)\s+(\S+)\s+\S+\s+\S+\s*\S*\s*(.*)", l)
        if not m:
            continue
        lo, hi = int(m.group(1), 16), int(m.group(2), 16)
        perm, path = m.group(3), m.group(4).strip()
        if "w" not in perm or "/" in path or "/dev/" in path:
            continue
        if best is None or hi - lo > best[1] - best[0]:
            best = (lo, hi)
    return best


def describe(pid, base, size, tag):
    raw = rd(pid, GAPP_ADDR, 4)
    gapp = int(np.frombuffer(raw, "<u4")[0]) if raw else 0
    rb = rd(pid, gapp + 0xBE8, 4) if gapp else None
    board = int(np.frombuffer(rb, "<u4")[0]) if rb else 0
    print("[%s] PID=%d  区域 0x%X..0x%X (%.2f MB)" % (tag, pid, base, base + size, size / 1048576.0))
    print("      gApp=0x%X  Board=0x%X  (Board 在区内: %s)"
          % (gapp, board, "是" if base <= board < base + size else "**否**"))
    return gapp, board


def do_scan(pid, base, size, dur):
    print("粗筛 %.1fs，采样中…" % dur)
    snaps, ts = [], []
    t0 = time.perf_counter()
    while True:
        el = time.perf_counter() - t0
        if el > dur:
            break
        d = rd(pid, base, size)
        if d is None:
            print("  读取失败")
            break
        snaps.append(np.frombuffer(d, "<i4").copy())
        ts.append(el)
        time.sleep(0.004)
    if len(snaps) < 4:
        print("  采样太少")
        return
    M = np.stack(snaps)
    K = len(ts)
    print("  采样 %d 次 / %.2fs (%.0f Hz)" % (K, ts[-1], K / ts[-1]))
    Mi = M.astype(np.int64)
    Mf = M.view("<f4").astype(np.float64)
    fin = np.isfinite(Mf)

    out = {}
    # --- int32 视图：单调不增且确实下降 ---
    di = np.diff(Mi, axis=0)
    mask_i = (di < 0).any(0) & (di <= 0).all(0) & ((Mi[0] - Mi[-1]) > 0)
    idx_i = np.nonzero(mask_i)[0]
    out["i4"] = idx_i
    # --- float32 视图 ---
    df = np.diff(Mf, axis=0)
    mask_f = (df < 0).any(0) & (df <= 0).all(0) & ((Mf[0] - Mf[-1]) > 0) & fin.all(0)
    idx_f = np.nonzero(mask_f)[0]
    out["f4"] = idx_f

    for kind in ("i4", "f4"):
        idx = out[kind]
        print("  [%s] 候选 %d 个" % (kind, len(idx)))
        seq = Mi if kind == "i4" else Mf
        drop = seq[0] - seq[-1]
        order = np.argsort(-drop)[:25]
        for j in order:
            i = int(idx[j])
            a = base + i * 4
            s = seq[:, i]
            head = ",".join(("%d" % v) if kind == "i4" else ("%.3f" % v) for v in s[:10])
            print("    0x%-9X 落差=%.3f  %s" % (a, drop[i], head))

    np.savez(CAND, base=base, size=size, idx_i=idx_i, idx_f=idx_f)
    print("  候选已存 %s（i4=%d f4=%d）" % (CAND, len(idx_i), len(idx_f)))


def do_track(pid, base, size, dur):
    z = np.load(CAND)
    idx_i, idx_f = z["idx_i"], z["idx_f"]
    # 合并并按地址排序去重
    both = np.unique(np.concatenate([idx_i, idx_f]))
    print("精跟 %.1fs，同时记录 i4/f4 两套值，共 %d 个候选槽…" % (dur, len(both)))
    vals, ts = [], []
    t0 = time.perf_counter()
    while True:
        el = time.perf_counter() - t0
        if el > dur:
            break
        d = rd(pid, base, size)
        if d is None:
            continue
        arr = np.frombuffer(d, "<i4")[both]
        vals.append(arr.copy())
        ts.append(el)
    if len(vals) < 4:
        print("  采样太少")
        return
    V = np.stack(vals)                       # int32 原始位
    Vi = V.astype(np.int64)                  # int 解释
    Vf = V.view("<f4").astype(np.float64)    # float 解释
    T = np.array(ts)
    print("  采样 %d 次 / %.2fs (%.0f Hz)" % (len(ts), T[-1], len(ts) / T[-1]))

    rep = []
    for k, gi in enumerate(both):
        a = base + int(gi) * 4
        si, sf = Vi[:, k], Vf[:, k]
        di = np.diff(si)
        df = np.diff(sf)
        # int 视图判据
        if (di <= 0).all() and (di < 0).any():
            drop = int(si[0] - si[-1])
            nchg = int((di < 0).sum())
            rep.append((drop / max(T[-1], 1e-6), a, "i4", drop, nchg, si))
        # float 视图判据
        if np.isfinite(sf).all() and (df <= 0).all() and (df < 0).any():
            drop = float(sf[0] - sf[-1])
            nchg = int((df < 0).sum())
            rep.append((drop / max(T[-1], 1e-6), a, "f4", drop, nchg, sf))

    rep.sort(key=lambda r: -r[0])
    print("  下降候选 %d 条（按平均下降速度排序，前 40）：" % len(rep))
    for rate, a, kind, drop, nchg, s in rep[:40]:
        head = ",".join(("%d" % v) if kind == "i4" else ("%.2f" % v) for v in s[:14])
        print("    速率=%8.3f /s  0x%-9X [%s] 落差=%.3f 变动%d次  %s"
              % (rate, a, kind, drop, nchg, head))
    np.savez("/home/deck/track_result.npz",
             base=base, addrs=np.array([base + int(g) * 4 for g in both]), V=V, T=T)


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "scan"
    dur = float(sys.argv[2]) if len(sys.argv) > 2 else 8.0
    pid = find_pid()
    if pid is None:
        print("  ❌ 游戏没在跑")
        return
    if mode == "track":
        z = np.load(CAND)
        base, size = int(z["base"]), int(z["size"])
    else:
        base, size = get_region(pid)
    describe(pid, base, size, mode)
    if mode == "track":
        do_track(pid, base, size, dur)
    else:
        do_scan(pid, base, size, dur)


if __name__ == "__main__":
    main()
