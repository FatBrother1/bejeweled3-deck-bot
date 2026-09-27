#!/usr/bin/env python3
"""pdiff.py —— 内存安全版「暂停态快照差分」（修 2026-09-25 15:48 earlyoom 事故）。

事故根因：上一版 pclock.py 把两次全量快照各存成 int64 + float64 四份数组，
  4 × 8B × 2.65亿 ≈ 8.6GB → earlyoom 在 15:48:03 杀掉 python3，
  游戏（Steam 会话）随之退出。

本版三条硬约束：
  1. **只存 int32 原样**（1.06GB/快照），绝不 upcast 到 int64/float64。
  2. **快照 B 边读边比**：读一块、比一块、只留候选，峰值 ≈ A(1.06GB) + 512KB。
  3. **RSS 硬闸**：超过 LIMIT_MB 立刻释放并中止，绝不让 earlyoom 出手。

Δt 用游戏自己的时钟 Board+0x38（厘秒）：暂停时它冻结，两次快照各读一次，
差值精确到 10ms，不依赖物理时间、不依赖读画面。

用法：
  python3 pdiff.py run [间隔秒]   # 进局→暂停→快照A→返回→等待→暂停→比B
  python3 pdiff.py snap          # 只在当前（应已暂停）状态做快照A
  python3 pdiff.py cmp           # 用已有 A + 当前状态做快照B并比较
"""
import ctypes, json, os, re, subprocess, sys, time
sys.path.insert(0, "/home/deck")
import numpy as np
from reader_mem import _IOV, _libc, find_pid, GAPP_ADDR, OFF_BOARD

CHUNK = 512 * 1024
W, H = 1280, 800
OUT = "/tmp/tlock"
LIMIT_MB = 1800          # RSS 硬闸
MENU = (215, 730)
BACK = (889, 598)
A_FILE = OUT + "/pd_A.npz"
META = OUT + "/pd_meta.json"


def rss_mb():
    try:
        for l in open("/proc/self/status"):
            if l.startswith("VmRSS:"):
                return int(l.split()[1]) / 1024.0
    except Exception:
        pass
    return 0.0


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
        return None, None
    b = ru32(pid, g + OFF_BOARD)
    if not b:
        return None, None
    return ru32(pid, b + 0x38), ru32(pid, b + 0xC84)


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
        cmd += ["videocrop", "left=950", "right=%d" % (W - 1180),
                "top=0", "bottom=%d" % (H - 120), "!",
                "videoscale", "!", "video/x-raw,width=1380", "!"]
    cmd += ["pngenc", "!", "filesink", "location=" + path]
    subprocess.run(cmd, capture_output=True)


def read_region(pid, lo, hi):
    """读一个区，返回 int32 数组（不 upcast），失败返回 None。"""
    n = hi - lo
    arr = np.zeros((n + 3) // 4, dtype="<i4")
    off = 0
    while off < n:
        sz = min(CHUNK, n - off)
        d = rd(pid, lo + off, sz)
        if d is None or len(d) != sz:
            return None
        m = len(d) - (len(d) % 4)
        if m:
            arr[off // 4:off // 4 + m // 4] = np.frombuffer(d[:m], "<i4")
        off += sz
    return arr


def snapshot_a(pid, regs):
    store = []
    for lo, hi in regs:
        a = read_region(pid, lo, hi)
        if a is None:
            continue
        store.append((lo, a))
        if rss_mb() > LIMIT_MB:
            print("  ⚠️ RSS %.0fMB 触顶，中止快照" % rss_mb())
            return None
    # 落盘（int32，1.06GB）
    los = np.array([l for l, _ in store], dtype=np.uint64)
    his = np.array([l + len(a) * 4 for l, a in store], dtype=np.uint64)
    np.savez(A_FILE, los=los, his=his,
             flat=np.concatenate([a for _, a in store]))
    print("  快照A 完成：%d 区 / %d 槽 / RSS %.0fMB"
          % (len(store), sum(len(a) for _, a in store), rss_mb()))
    return store


def compare(pid, store, dcs):
    """边读B边比，只留候选。返回候选列表。"""
    cand = []          # (addr, va, vb, axis)
    hit = np.load(A_FILE)
    los = hit["los"]
    his = hit["his"]
    flat = hit["flat"]
    pos = 0
    nreg = 0
    for i in range(len(los)):
        lo = int(los[i])
        hi = int(his[i])
        n = (hi - lo) // 4
        fa = flat[pos:pos + n]
        pos += n
        b = read_region(pid, lo, hi)
        nreg += 1
        if b is None or len(b) < n:
            continue
        b = b[:n]
        # ---- int32 轴 ----
        d = fa.astype(np.int32) - b      # int32 相减，仍 int32（不 upcast）
        d32 = d.astype(np.int32, copy=False)
        for target, name, tol in ((dcs, "cs", 2), (dcs / 10.0, "ds", 2), (dcs / 100.0, "s", 2)):
            m = np.abs(d32.astype(np.int64) - target) <= tol
            if m.any():
                for k in np.nonzero(m)[0]:
                    cand.append((lo + int(k) * 4, int(fa[k]), int(b[k]), "i4_" + name))
        # ---- float32 轴（分片做，不整块 upcast） ----
        f32a = fa.view("<f4")
        f32b = b.view("<f4")
        nf = len(f32a)
        for s in range(0, nf, 2_000_000):
            e = min(s + 2_000_000, nf)
            va = f32a[s:e].astype(np.float32, copy=False)
            vb = f32b[s:e].astype(np.float32, copy=False)
            fin = np.isfinite(va) & np.isfinite(vb)
            df = va.astype(np.float64) - vb.astype(np.float64)
            for target, name, tol in ((dcs / 100.0, "f4_s", 0.4), (dcs / 10.0, "f4_ds", 4.0)):
                m = fin & (np.abs(df - target) <= tol) & (np.abs(vb) < 1e6)
                if m.any():
                    for k in np.nonzero(m)[0]:
                        cand.append((lo + (s + int(k)) * 4, float(va[k]), float(vb[k]), name))
        if rss_mb() > LIMIT_MB:
            print("  ⚠️ RSS %.0fMB 触顶，中止比较" % rss_mb())
            break
    print("  比较完成 %d 区 / RSS %.0fMB / 候选 %d 条" % (nreg, rss_mb(), len(cand)))
    return cand


def report(cand, dcs):
    print("\n=== Δ游戏时钟 = %d 厘秒（%.2f 秒）===" % (dcs, dcs / 100.0))
    by = {}
    for a, va, vb, axis in cand:
        by.setdefault(axis, []).append((a, va, vb))
    for axis in sorted(by):
        rows = by[axis]
        print("--- %s：%d 条 ---" % (axis, len(rows)))
        # 优先显示「值域像倒计时」的（1..65 秒 / 10..650 十分秒）
        def key(r):
            v = r[2]
            return (0 if 0 < abs(v) <= 700 else 1, -abs(v))
        for a, va, vb in sorted(rows, key=key)[:80]:
            print("    0x%-11X %14.4f → %14.4f" % (a, va, vb))
    json.dump([{"addr": "0x%X" % a, "va": va, "vb": vb, "axis": ax}
               for a, va, vb, ax in cand],
              open(OUT + "/pd_cand.json", "w"), indent=1)


def do_snap():
    pid = find_pid()
    if pid is None:
        print("  ❌ 游戏没在跑")
        return
    regs = regions(pid)
    print("PID=%d 区 %d 个 / %.0f MB（RSS 起始 %.0fMB）"
          % (pid, len(regs), sum(h - l for l, h in regs) / 1048576, rss_mb()))
    c, s = clock(pid)
    st = snapshot_a(pid, regs)
    if st is None:
        return
    json.dump({"cA": c, "sA": s, "regs": len(regs)}, open(META, "w"))
    print("  时钟 cs=%s s=%s（快照A）" % (c, s))
    shot(OUT + "/pd_A.png", crop=True)


def do_cmp():
    pid = find_pid()
    meta = json.load(open(META))
    cB, sB = clock(pid)
    dcs = cB - meta["cA"]
    print("时钟 A cs=%s → B cs=%s   Δ=%d cs" % (meta["cA"], cB, dcs))
    shot(OUT + "/pd_B.png", crop=True)
    store = None
    cand = compare(pid, store, dcs)
    report(cand, dcs)


def do_run(gap):
    pid = find_pid()
    if pid is None:
        print("  ❌ 游戏没在跑")
        return
    print("[1] 进局")
    click((628, 739), 1.6)
    print("[2] 暂停（点左下「菜单」→选项覆盖层，游戏逻辑冻结）")
    click(MENU, 1.0)
    shot(OUT + "/pd_pauseA.png", crop=True)
    do_snap()
    print("[3] 返回继续 %.1fs" % gap)
    click(BACK, gap)
    print("[4] 再暂停")
    click(MENU, 1.0)
    shot(OUT + "/pd_pauseB.png", crop=True)
    do_cmp()


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "run"
    if cmd == "snap":
        do_snap()
    elif cmd == "cmp":
        do_cmp()
    elif cmd == "run":
        do_run(float(sys.argv[2]) if len(sys.argv) > 2 else 3.0)
    else:
        print(__doc__)
