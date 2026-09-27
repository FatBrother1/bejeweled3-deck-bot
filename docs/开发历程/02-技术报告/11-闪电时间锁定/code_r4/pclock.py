#!/usr/bin/env python3
"""pclock.py —— 游戏时钟校准法定位倒计时（不依赖读画面）。

原理（本轮最重要的方法修正）：
  闪电局点「菜单」暂停后，游戏逻辑完全冻结（实测 Board+0x38 厘秒三次读数
  恒为 482），此时进程仍在跑，可自由读写内存。
  于是：暂停 → 快照A → 返回游戏走 3 秒 → 再暂停 → 快照B。
  Δt 不靠物理时间，而靠游戏自己的时钟（Board+0x38 厘秒），精确到 10ms。
  倒计时主控必然满足： vA - vB ≈ Δt（或 Δt*10 / Δt*1000 等刻度）。

用法：
  python3 pclock.py run       # 完整跑一轮（自动进局/暂停/两次快照）
  python3 pclock.py diff      # 用已有快照计算差值
"""
import ctypes, os, re, subprocess, sys, time
sys.path.insert(0, "/home/deck")
import numpy as np
from reader_mem import _IOV, _libc, find_pid, GAPP_ADDR, OFF_BOARD

CHUNK = 512 * 1024
W, H = 1280, 800
OUT = "/tmp/tlock"
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
        return (None, None, None)
    b = ru32(pid, g + OFF_BOARD)
    if not b:
        return (None, None, None)
    return (b, ru32(pid, b + 0x38), ru32(pid, b + 0xC84))


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


def shot(path, crop=True):
    cmd = ["timeout", "20", "gst-launch-1.0", "-q", "pipewiresrc", "path=93",
           "num-buffers=1", "!", "videoconvert", "!"]
    if crop:
        cmd += ["videocrop", "left=980", "right=%d" % (W - 1170),
                "top=5", "bottom=%d" % (H - 100), "!",
                "videoscale", "!", "video/x-raw,width=1140", "!"]
    cmd += ["pngenc", "!", "filesink", "location=" + path]
    subprocess.run(cmd, capture_output=True)


def dump(pid, regs, tag):
    """全量转储，返回 dict addr->值。i4 与 f4 两套。"""
    ai, vi, af, vf = [], [], [], []
    for lo, hi in regs:
        off = 0
        while off < hi - lo:
            sz = min(CHUNK, hi - lo - off)
            d = rd(pid, lo + off, sz)
            if d is None or len(d) != sz:
                off += sz
                continue
            base = lo + off
            c4 = len(d) // 4
            a4 = np.frombuffer(d[:c4 * 4], "<i4")
            ai.append(base + np.arange(c4, dtype=np.uint64) * 4)
            vi.append(a4.astype(np.int64))
            af.append(base + np.arange(c4, dtype=np.uint64) * 4)
            vf.append(a4.view("<f4").astype(np.float64))
            off += sz
    AI = np.concatenate(ai)
    VI = np.concatenate(vi)
    AF = np.concatenate(af)
    VF = np.concatenate(vf)
    np.savez("%s/pc_%s.npz" % (OUT, tag), AI=AI, VI=VI, AF=AF, VF=VF)
    print("  [%s] 转储 %d 个 4 字节槽" % (tag, len(AI)), flush=True)


def do_run():
    pid = find_pid()
    if pid is None:
        print("  ❌ 游戏没在跑")
        return
    regs = regions(pid)
    print("PID=%d 区 %d 个 / %.1f MB" % (pid, len(regs), sum(h - l for l, h in regs) / 1048576))
    print("[1] 进局")
    click((628, 739), 2.0)
    print("[2] 点菜单暂停")
    click(MENU, 1.0)
    _, cA, sA = clock(pid)
    print("    快照A 时钟 cs=%s s=%s" % (cA, sA))
    dump(pid, regs, "A")
    print("[3] 返回游戏，走 3 秒")
    click(BACK, 3.0)
    print("[4] 再点菜单暂停")
    click(MENU, 1.0)
    b, cB, sB = clock(pid)
    print("    快照B 时钟 cs=%s s=%s   Δcs=%s" % (cB, sB, (cB - cA) if (cB and cA) else None))
    dump(pid, regs, "B")
    import json
    json.dump({"b": b, "cA": cA, "sA": sA, "cB": cB, "sB": sB},
              open("%s/pc_meta.json" % OUT, "w"))
    print("完成。跑 python3 pclock.py diff 计算")


def do_diff():
    import json
    meta = json.load(open("%s/pc_meta.json" % OUT))
    dcs = meta["cB"] - meta["cA"]
    print("游戏时钟差 Δcs=%d（=%.2f 秒）" % (dcs, dcs / 100.0))
    a = np.load("%s/pc_A.npz" % OUT)
    b = np.load("%s/pc_B.npz" % OUT)
    # 用地址做键（两套视图地址一致）
    print("A 槽 %d，B 槽 %d" % (len(a["AI"]), len(b["AI"])))
    # 差值分析：只看「值在 0..3700 厘秒 或 0..370 十分秒 或 1..62 秒」
    dA = a["AF"]
    dB = b["AF"]
    VA = a["VF"]
    VB = b["VF"]
    assert np.array_equal(dA, dB), "地址不一致"
    # int 视图
    iA = a["VI"].astype(np.int64)
    iB = b["VI"].astype(np.int64)
    di = iA - iB
    # 候选：差值≈Δcs 的（厘秒刻度）
    m1 = np.abs(di - dcs) <= 2
    print("\n--- int32，差值≈%d（厘秒刻度）: %d 个 ---" % (dcs, m1.sum()))
    for k in np.nonzero(m1)[0][:40]:
        print("   0x%-10X %8d → %8d" % (dA[k], iA[k], iB[k]))
    # 差值≈Δcs/10 的（秒刻度）
    ds = dcs / 10.0
    m2 = np.abs((iA - iB) - ds) <= 2
    print("--- int32，差值≈%.1f（十分秒/秒刻度）: %d 个 ---" % (ds, m2.sum()))
    for k in np.nonzero(m2)[0][:40]:
        print("   0x%-10X %8d → %8d" % (dA[k], iA[k], iB[k]))
    # 秒刻度整数
    ds1 = dcs / 100.0
    m3 = np.abs((iA - iB) - ds1) <= 2
    print("--- int32，差值≈%.2f（秒刻度）: %d 个 ---" % (ds1, m3.sum()))
    for k in np.nonzero(m3)[0][:40]:
        print("   0x%-10X %8d → %8d" % (dA[k], iA[k], iB[k]))
    # float 视图
    fin = np.isfinite(VA) & np.isfinite(VB)
    df = VA - VB
    mf = fin & (np.abs(df - ds1) <= 0.35) & (np.abs(VB) < 400)
    print("--- float32，差值≈%.2f: %d 个 ---" % (ds1, mf.sum()))
    for k in np.nonzero(mf)[0][:40]:
        print("   0x%-10X %12.4f → %12.4f" % (dA[k], VA[k], VB[k]))


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "run"
    if cmd == "diff":
        do_diff()
    else:
        do_run()
