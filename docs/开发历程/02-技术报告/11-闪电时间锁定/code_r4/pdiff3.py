#!/usr/bin/env python3
"""pdiff3.py —— 暂停态三次快照差分（分块文件流，峰值内存 < 20MB）。

方法演进：
  v1 pclock.py 把快照存 int64+float64 四份 → 8.6GB → 15:48 earlyoom 杀进程 + 游戏退出。
  v2 pdiff2.py 用 np.memmap → 页缓存仍计入 RSS → 1200MB 触顶中止。
  v3 本版：**纯分块顺序文件流**。
      · 快照：逐区、逐 512KB 块读内存 → 直接 append 写入磁盘文件。
      · 比较：同一顺序再读一遍内存 + 从文件读同长度块 → 分片比较 → 只留候选。
      · 全程序峰值 = 2 个 512KB 缓冲（< 20MB），与内存总量无关。

判据（三次快照，两个独立 Δt 交叉验证）：
  真主控必须同时满足 A-B 落差 ≈ Δt_AB、B-C 落差 ≈ Δt_BC。
  单个巧合几乎不可能同时满足两对，故交集极干净。
  Δt 来源 = 游戏自己的时钟 Board+0x38（厘秒），暂停时冻结。

用法：
  python3 pdiff3.py run [gap1] [gap2]   # 进局→暂停A→走gap1→暂停B→走gap2→暂停C→比较
  python3 pdiff3.py snap <tag>          # 当前状态拍快照
  python3 pdiff3.py diff <A> <B>        # 比较两个快照
"""
import ctypes, json, os, re, subprocess, sys, time
sys.path.insert(0, "/home/deck")
import numpy as np
from reader_mem import _IOV, _libc, find_pid, GAPP_ADDR, OFF_BOARD

CHUNK = 512 * 1024
SNAP_DIR = "/home/deck/pd3"
W, H = 1280, 800
MENU = (215, 730)
BACK = (889, 598)


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


def clock(pid):
    g = ru32(pid, GAPP_ADDR)
    if not g:
        return None, None, None
    b = ru32(pid, g + OFF_BOARD)
    if not b:
        return None, None, None
    return b, ru32(pid, b + 0x38), ru32(pid, b + 0xC84)


def regions(pid):
    out = []
    for l in open("/proc/%d/maps" % pid):
        m = re.match(r"^([0-9a-f]+)-([0-9a-f]+)\s+(\S+)\s+\S+\s+\S+\s*\S*\s*(.*)", l)
        if not m:
            continue
        lo, hi = int(m.group(1), 16), int(m.group(2), 16)
        perm, path = m.group(3), m.group(4).strip()
        if "w" not in perm or hi <= lo or "/dev/" in path or "memfd" in path:
            continue
        out.append((lo, hi))
    return out


def click(pt, wait):
    from vmouse2 import VMouse2
    m = VMouse2()
    m.click(pt[0], pt[1])
    m.close()
    time.sleep(wait)


def shot(path, crop=False):
    cmd = ["timeout", "20", "gst-launch-1.0", "-q", "pipewiresrc", "path=93",
           "num-buffers=1", "!", "videoconvert", "!"]
    if crop:
        cmd += ["videocrop", "left=990", "right=%d" % (W - 1175),
                "top=0", "bottom=%d" % (H - 110), "!",
                "videoscale", "!", "video/x-raw,width=1140", "!"]
    cmd += ["pngenc", "!", "filesink", "location=" + path]
    subprocess.run(cmd, capture_output=True)


def rss_mb():
    try:
        for l in open("/proc/self/status"):
            if l.startswith("VmRSS:"):
                return int(l.split()[1]) / 1024.0
    except Exception:
        pass
    return 0.0


def snap(tag):
    """当前（应已暂停）状态 → 快照文件 + 时钟。逐块顺序写，峰值低。"""
    pid = find_pid()
    if pid is None:
        print("  ❌ 游戏没在跑")
        return None
    os.makedirs(SNAP_DIR, exist_ok=True)
    regs = regions(pid)
    b, cs, s = clock(pid)
    binp = "%s/%s.bin" % (SNAP_DIR, tag)
    idx = []
    pos = 0
    with open(binp, "wb") as f:
        for lo, hi in regs:
            off = 0
            n = hi - lo
            wrote = 0
            ok = True
            while off < n:
                sz = min(CHUNK, n - off)
                d = rd(pid, lo + off, sz)
                if d is None or len(d) != sz:
                    ok = False
                    break
                f.write(d)
                wrote += sz
                off += sz
            idx.append([lo, pos, wrote if ok else -1])
            if ok:
                pos += wrote
    json.dump({"regions": idx, "cs": cs, "s": s, "board": b,
               "bytes": os.path.getsize(binp)},
              open("%s/%s.json" % (SNAP_DIR, tag), "w"))
    print("  [%s] Board=0x%X 时钟 cs=%s s=%s  快照 %.0fMB  RSS %.0fMB"
          % (tag, b or 0, cs, s, os.path.getsize(binp) / 1048576.0, rss_mb()))
    return cs


def diff(tagA, tagB):
    pid = find_pid()
    ma = json.load(open("%s/%s.json" % (SNAP_DIR, tagA)))
    mb = json.load(open("%s/%s.json" % (SNAP_DIR, tagB)))
    if ma["cs"] is None or mb["cs"] is None:
        print("  ❌ 时钟缺失")
        return None
    dcs = mb["cs"] - ma["cs"]
    print("  时钟 %s cs=%s → %s cs=%s    Δ=%d cs = %.2f 秒"
          % (tagA, ma["cs"], tagB, mb["cs"], dcs, dcs / 100.0))
    fa = open("%s/%s.bin" % (SNAP_DIR, tagA), "rb")
    cand = []
    nreg = 0
    for (lo_a, pos_a, n_a), (lo_b, _, n_b) in zip(ma["regions"], mb["regions"]):
        if n_a <= 0 or n_b <= 0 or lo_a != lo_b or n_a != n_b:
            continue
        fa.seek(pos_a)
        off = 0
        while off < n_a:
            sz = min(CHUNK, n_a - off)
            db = rd(pid, lo_a + off, sz)
            if db is None or len(db) != sz:
                off += sz
                continue
            da = fa.read(sz)
            if len(da) != sz:
                break
            cnt = sz // 4
            va = np.frombuffer(da[:cnt * 4], "<i4")
            vb = np.frombuffer(db[:cnt * 4], "<i4")
            # --- float32 视图：秒刻度 ---
            fva = va.view("<f4").astype(np.float32, copy=False)
            fvb = vb.view("<f4").astype(np.float32, copy=False)
            fin = np.isfinite(fva) & np.isfinite(fvb)
            dfa = fva.astype(np.float64) - fvb.astype(np.float64)
            t_sec = dcs / 100.0
            m = fin & (np.abs(dfa - t_sec) <= 0.30) & (fva > 0) & (fva < 400)
            if m.any():
                for k in np.nonzero(m)[0]:
                    cand.append((lo_a + off + int(k) * 4, float(fva[k]), float(fvb[k]), "f4_s"))
            # 十分秒
            m = fin & (np.abs(dfa - dcs / 10.0) <= 3.0) & (fva > 0) & (fva < 4000)
            if m.any():
                for k in np.nonzero(m)[0]:
                    cand.append((lo_a + off + int(k) * 4, float(fva[k]), float(fvb[k]), "f4_t"))
            # --- int32 视图：秒 / 十分秒 ---
            ia = va.astype(np.int64)
            ib = vb.astype(np.int64)
            di = ia - ib
            m = (np.abs(di - t_sec) <= 1.5) & (ia > 0) & (ia < 400)
            if m.any():
                for k in np.nonzero(m)[0]:
                    cand.append((lo_a + off + int(k) * 4, float(ia[k]), float(ib[k]), "i4_s"))
            m = (np.abs(di - dcs / 10.0) <= 1.5) & (ia > 0) & (ia < 4000)
            if m.any():
                for k in np.nonzero(m)[0]:
                    cand.append((lo_a + off + int(k) * 4, float(ia[k]), float(ib[k]), "i4_t"))
            off += sz
        nreg += 1
    fa.close()
    print("  比较 %d 区 / RSS %.0fMB / 候选 %d" % (nreg, rss_mb(), len(cand)))
    return dcs, cand


def do_run(g1, g2):
    pid = find_pid()
    if pid is None:
        print("  ❌ 游戏没在跑")
        return
    print("[1] 暂停（点「菜单」）")
    click(MENU, 1.0)
    shot("/home/deck/pd3/A.png", crop=True)
    snap("A")
    print("[2] 返回，走 %.1fs" % g1)
    click(BACK, g1)
    click(MENU, 1.0)
    snap("B")
    print("[3] 返回，走 %.1fs" % g2)
    click(BACK, g2)
    click(MENU, 1.0)
    snap("C")

    r1 = diff("A", "B")
    r2 = diff("B", "C")
    if not r1 or not r2:
        return
    d1, c1 = r1
    d2, c2 = r2
    k1 = {(a, ax): (va, vb) for a, va, vb, ax in c1}
    k2 = {(a, ax): (va, vb) for a, va, vb, ax in c2}
    both = set(k1) & set(k2)
    print("\n=== 三次快照交叉验证：Δ1=%d cs  Δ2=%d cs；候选 A-B=%d，B-C=%d，交集=%d ==="
          % (d1, d2, len(k1), len(k2), len(both)))
    rows = sorted(both, key=lambda k: k[0])
    for a, ax in rows:
        v1 = k1[(a, ax)][0]
        v2 = k2[(a, ax)][0]
        print("   0x%-11X [%-5s] A=%.4f  B=%.4f  C=%.4f" % (a, ax, v1, k1[(a, ax)][1], v2))
    json.dump([{"addr": "0x%X" % a, "axis": ax} for a, ax in rows],
              open(SNAP_DIR + "/hit.json", "w"), indent=1)
    if not rows:
        print("   （空集：本轮无同时满足两对 Δ 的槽 —— 说明 Δ 判据过严或主控非单调）")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "run"
    if cmd == "snap":
        snap(sys.argv[2])
    elif cmd == "diff":
        r = diff(sys.argv[2], sys.argv[3])
        if r:
            for a, va, vb, ax in sorted(r[1], key=lambda t: t[0])[:100]:
                print("   0x%-11X [%-5s] %12.4f → %12.4f" % (a, ax, va, vb))
    elif cmd == "run":
        do_run(float(sys.argv[2]) if len(sys.argv) > 2 else 2.0,
               float(sys.argv[3]) if len(sys.argv) > 3 else 3.0)
    else:
        print(__doc__)
