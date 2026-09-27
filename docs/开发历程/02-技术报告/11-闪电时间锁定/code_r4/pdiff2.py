#!/usr/bin/env python3
"""pdiff2.py —— 内存安全版「暂停态快照差分」v2（memmap 流式）。

设计目标：把峰值内存从 pclock.py 的 ~8.6GB（触发 earlyoom 杀进程 + 游戏退出）
        压到 **几十 MB**，彻底规避事故。

做法：
  · 快照A 逐区读取 → 直接写进磁盘文件（np.memmap，int32 原样位），
    峰值 = 单个最大区（约 64MB）。
  · 快照B 逐区读取 → 从 memmap 取回对应 A 区 → 分片比较 → 只留候选。
    峰值 = 单区 + 2M 槽分片（约 80MB）。
  · 每区检查 RSS，超 1200MB 立即中止（保险丝）。

Δt 来源：**游戏自己的时钟** Board+0x38（厘秒）。暂停时它冻结，
        于是「两次暂停的时钟差 Δcs」= 倒计时真实减少量 × 100，精确到 10ms。

用法：
  python3 pdiff2.py run [间隔秒]   # 进局→暂停→A→返回→等待→暂停→比B
  python3 pdiff2.py snap          # 当前（暂停态）做快照A
  python3 pdiff2.py cmp           # 当前状态做快照B并与A比较
"""
import ctypes, json, os, re, subprocess, sys, time
sys.path.insert(0, "/home/deck")
import numpy as np
from reader_mem import _IOV, _libc, find_pid, GAPP_ADDR, OFF_BOARD

CHUNK = 512 * 1024
SLICE = 2_000_000          # 比较分片（2M 槽 = 8MB）
W, H = 1280, 800
OUT = "/tmp/tlock"
A_BIN = "/home/deck/pd2_A.bin"
A_IDX = "/home/deck/pd2_A.idx.json"
META = "/home/deck/pd2_meta.json"
LIMIT_MB = 1200
MENU = (215, 730)
BACK = (889, 598)


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


def read_region(pid, lo, hi):
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
        # 倒计时框实测：x∈[1010,1160] y∈[10,90]
        cmd += ["videocrop", "left=1000", "right=%d" % (W - 1170),
                "top=0", "bottom=%d" % (H - 100), "!",
                "videoscale", "!", "video/x-raw,width=1360", "!"]
    cmd += ["pngenc", "!", "filesink", "location=" + path]
    subprocess.run(cmd, capture_output=True)


def snap_a(pid, regs):
    idx = []
    pos = 0
    total = 0
    for lo, hi in regs:
        total += (hi - lo) // 4
    mm = np.memmap(A_BIN, dtype="<i4", mode="w+", shape=(total,))
    for lo, hi in regs:
        a = read_region(pid, lo, hi)
        if a is None:
            idx.append([lo, -1, 0])
            continue
        mm[pos:pos + len(a)] = a
        idx.append([lo, pos, len(a)])
        pos += len(a)
        if rss_mb() > LIMIT_MB:
            print("  ⚠️ RSS %.0fMB 触顶，中止快照A" % rss_mb())
            break
    mm.flush()
    del mm
    json.dump(idx, open(A_IDX, "w"))
    print("  快照A：%d 区 / %d 槽 / 文件 %.0fMB / RSS %.0fMB"
          % (len(idx), total, os.path.getsize(A_BIN) / 1048576.0, rss_mb()))


def cmp_b(pid, dcs):
    idx = json.load(open(A_IDX))
    total = sum(e[2] for e in idx)
    mm = np.memmap(A_BIN, dtype="<i4", mode="r", shape=(total,))
    cand = []
    nreg = 0
    for lo, pos, n in idx:
        if n <= 0:
            continue
        hi = lo + n * 4
        b = read_region(pid, lo, hi)
        nreg += 1
        if b is None or len(b) < n:
            continue
        a_full = mm[pos:pos + n]
        for s in range(0, n, SLICE):
            e = min(s + SLICE, n)
            va_i = a_full[s:e]
            vb_i = b[s:e]
            df = va_i.astype(np.float64) - vb_i.astype(np.float64)
            # 三种刻度
            for target, name, tol, lo_rng, hi_rng in (
                    (dcs / 100.0, "秒", 0.35, -1.0, 300.0),
                    (dcs / 10.0, "十分秒", 3.5, -10.0, 3000.0),
                    (float(dcs), "厘秒", 35.0, -100.0, 30000.0)):
                m = (np.abs(df - target) <= tol)
                if m.any():
                    # 只保留「A 值在该刻度合理范围」的
                    keep = m & (va_i.astype(np.float64) >= lo_rng) & (va_i.astype(np.float64) <= hi_rng)
                    for k in np.nonzero(keep)[0]:
                        cand.append((lo + (s + int(k)) * 4, float(va_i[k]), float(vb_i[k]), "f_" + name))
            # int32 视图（值本身是整数）
            di = va_i.astype(np.int64) - vb_i.astype(np.int64)
            for target, name, tol, lo_rng, hi_rng in (
                    (dcs / 100.0, "秒i", 1.5, 0, 300),
                    (dcs / 10.0, "十分秒i", 1.5, 0, 3000),
                    (float(dcs), "厘秒i", 1.5, 0, 30000)):
                m = (np.abs(di - target) <= tol)
                if m.any():
                    keep = m & (va_i.astype(np.int64) >= lo_rng) & (va_i.astype(np.int64) <= hi_rng)
                    for k in np.nonzero(keep)[0]:
                        cand.append((lo + (s + int(k)) * 4, float(va_i[k]), float(vb_i[k]), "i_" + name))
        if rss_mb() > LIMIT_MB:
            print("  ⚠️ RSS %.0fMB 触顶，中止比较" % rss_mb())
            break
    print("  比较 %d 区 / RSS %.0fMB / 候选 %d" % (nreg, rss_mb(), len(cand)))
    return cand


def report(cand, dcs):
    print("\n=== Δ游戏时钟 = %d 厘秒 = %.2f 秒 ===" % (dcs, dcs / 100.0))
    by = {}
    for a, va, vb, axis in cand:
        by.setdefault(axis, []).append((a, va, vb))
    for axis in sorted(by):
        rows = by[axis]
        print("--- [%s] %d 条 ---" % (axis, len(rows)))
        for a, va, vb in sorted(rows, key=lambda r: -abs(r[1]))[:60]:
            print("    0x%-11X %14.4f → %14.4f" % (a, va, vb))
    json.dump([{"addr": "0x%X" % a, "va": va, "vb": vb, "axis": ax}
               for a, va, vb, ax in cand], open(OUT + "/pd2_cand.json", "w"), indent=1)


def do_snap():
    pid = find_pid()
    if pid is None:
        print("  ❌ 游戏没在跑")
        return
    regs = regions(pid)
    print("PID=%d 区 %d 个 / %.0fMB" % (pid, len(regs), sum(h - l for l, h in regs) / 1048576))
    c, s = clock(pid)
    shot(OUT + "/pd2_A.png", crop=True)
    snap_a(pid, regs)
    json.dump({"cA": c, "sA": s}, open(META, "w"))
    print("  时钟 A：cs=%s  s=%s" % (c, s))


def do_cmp():
    pid = find_pid()
    meta = json.load(open(META))
    shot(OUT + "/pd2_B.png", crop=True)
    cB, sB = clock(pid)
    if cB is None or meta.get("cA") is None:
        print("  ❌ 时钟读取失败（可能不在局中）：A=%s B=%s" % (meta.get("cA"), cB))
        return
    dcs = cB - meta["cA"]
    print("  时钟 A cs=%s → B cs=%s   Δ=%d cs" % (meta["cA"], cB, dcs))
    cand = cmp_b(pid, dcs)
    report(cand, dcs)


def do_run(gap):
    pid = find_pid()
    if pid is None:
        print("  ❌ 游戏没在跑")
        return
    print("[2] 暂停（点「菜单」→选项覆盖层，游戏逻辑冻结）")
    click(MENU, 1.0)
    do_snap()
    print("[3] 返回继续 %.1fs" % gap)
    click(BACK, gap)
    print("[4] 再暂停")
    click(MENU, 1.0)
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
