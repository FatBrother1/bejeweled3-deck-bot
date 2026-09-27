#!/usr/bin/env python3
"""autopin.py —— 全自动「进局 → 定位 → 钉住 → 读图验收」闭环。

步骤：
  1. 点「再玩一次」进局
  2. 等 1.5s，跑全内存差分扫（默认 3 趟），用瞬时速率筛 -1.0/s 附近的候选
  3. 对候选批量钉住（同写多地址），周期性抓倒计时框
  4. 输出帧序列目录，供模型/人判读

用法：
  python3 autopin.py            # 全自动
  python3 autopin.py 0xADDR     # 只钉指定地址
"""
import ctypes, json, os, re, subprocess, sys, time
sys.path.insert(0, "/home/deck")
import numpy as np
from reader_mem import _IOV, _libc, find_pid, GAPP_ADDR, OFF_BOARD

OUT = "/tmp/tlock/auto"
CHUNK = 512 * 1024
W, H = 1280, 800
DT = {"i4": "<i4", "u4": "<u4", "f4": "<f4", "f8": "<f8"}
_libc.process_vm_writev.restype = ctypes.c_ssize_t
WB = ctypes.create_string_buffer(8)


def rd(pid, addr, size):
    buf = ctypes.create_string_buffer(size)
    lo = _IOV(ctypes.cast(buf, ctypes.c_void_p), size)
    r = _IOV(ctypes.c_void_p(addr), size)
    n = _libc.process_vm_readv(pid, ctypes.byref(lo), 1, ctypes.byref(r), 1, 0)
    if n == size:
        return buf.raw
    return buf.raw[:n] if n and n > 0 else None


def rv(pid, addr, dt="i4"):
    step = 8 if dt == "f8" else 4
    d = rd(pid, addr, step)
    return float(np.frombuffer(d, DT[dt])[0]) if d and len(d) == step else None


def wv(pid, addr, dt, val):
    step = 8 if dt == "f8" else 4
    WB.raw = np.array(val, dtype=DT[dt]).tobytes()
    lo = _IOV(ctypes.cast(WB, ctypes.c_void_p), step)
    r = _IOV(ctypes.c_void_p(addr), step)
    return _libc.process_vm_writev(pid, ctypes.byref(lo), 1, ctypes.byref(r), 1, 0) == step


def shot(path, crop_timer=True):
    cmd = ["timeout", "20", "gst-launch-1.0", "-q", "pipewiresrc", "path=93",
           "num-buffers=1", "!", "videoconvert", "!"]
    if crop_timer:
        cmd += ["videocrop", "left=1010", "right=%d" % (W - 1150),
                "top=15", "bottom=%d" % (H - 85), "!",
                "videoscale", "!", "video/x-raw,width=560", "!"]
    cmd += ["pngenc", "!", "filesink", "location=" + path]
    subprocess.run(cmd, capture_output=True)


def click(x, y, wait=2.5):
    from vmouse2 import VMouse2
    m = VMouse2()
    m.click(x, y)
    m.close()
    time.sleep(wait)


def all_regions(pid):
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


def read_all(pid, regs):
    out = []
    for lo, hi in regs:
        n = hi - lo
        arr = np.zeros((n + 3) // 4, dtype="<i4")
        off, bad = 0, False
        while off < n:
            sz = min(CHUNK, n - off)
            d = rd(pid, lo + off, sz)
            if d is None or len(d) != sz:
                bad = True
                break
            m = len(d) - (len(d) % 4)
            if m:
                arr[off // 4:off // 4 + m // 4] = np.frombuffer(d[:m], "<i4")
            off += sz
        if not bad:
            out.append((lo, arr))
    return out


def find_rate(pid, npass=3, tol=0.35):
    regs = all_regions(pid)
    print("  区域 %d 个 / %.0f MB" % (len(regs), sum(h - l for l, h in regs) / 1048576))
    prev = read_all(pid, regs)
    tp = time.perf_counter()
    acc = {}
    for p in range(2, npass + 1):
        cur = read_all(pid, regs)
        tc = time.perf_counter()
        dt = tc - tp
        for (lo, pv), (lo2, cv) in zip(prev, cur):
            n = min(len(pv), len(cv))
            pi, ci = pv.astype(np.int64), cv.astype(np.int64)
            rate = (ci - pi) / dt
            ok = (rate < 0) & (rate > -1.6) & (rate < -0.5) & (ci >= 0) & (ci <= 70)
            for k in np.nonzero(ok)[0]:
                acc.setdefault(lo + int(k) * 4, []).append(float(rate[k]))
        print("    第%d趟 dt=%.3fs 累计 %d" % (p, dt, len(acc)), flush=True)
        prev = cur
        tp = tc
    fin = {a: rs for a, rs in acc.items() if len(rs) == npass - 1}
    print("  速率≈-1/s 候选 %d 个" % len(fin))
    return fin


def main():
    os.makedirs(OUT, exist_ok=True)
    pid = find_pid()
    manual = sys.argv[1] if len(sys.argv) > 1 else None

    if not manual:
        print("[1] 点「再玩一次」进局")
        shot(OUT + "/00_before.png", crop_timer=False)
        click(628, 739, 2.0)
        shot(OUT + "/01_ingame.png")

    if manual:
        cands = {int(manual, 16): []}
    else:
        print("[2] 全内存差分扫描")
        cands = find_rate(pid, 3)
        if not cands:
            print("  ❌ 没找到候选，收工")
            return
        v0s = {a: rv(pid, a, "i4") for a in cands}
        cands = {a: v for a, v in v0s.items() if v is not None and 3 <= v <= 65}
        print("  值域过滤后 %d 个:" % len(cands))
        for a, v in sorted(cands.items(), key=lambda kv: kv[1])[:40]:
            print("     0x%-9X = %.0f" % (a, v))

    print("[3] 钉住候选（+300，保持 12 秒），期间抓帧")
    vals = {a: rv(pid, a, "i4") for a in cands}
    shot(OUT + "/02_pin_before.png")
    t0 = time.time()
    marks = [0.0, 1.0, 2.5, 5.0, 8.0]
    mi = 0
    nw = 0
    while time.time() - t0 < 12.0:
        el = time.time() - t0
        if mi < len(marks) and el >= marks[mi]:
            shot(OUT + "/03_pin_%04.1f.png" % marks[mi])
            print("     t=%4.1fs 帧已抓  回读: %s"
                  % (el, " ".join("0x%X=%.0f" % (a, rv(pid, a, "i4") or -1)
                                  for a in list(cands)[:6])), flush=True)
            mi += 1
        for a, v in vals.items():
            if v is not None:
                wv(pid, a, "i4", v + 300.0)
                nw += 1
        time.sleep(0.03)
    shot(OUT + "/04_pin_end.png")
    print("  完成：%d 个地址，写 %d 次" % (len(cands), nw))
    json.dump({"cands": {"0x%X" % a: v for a, v in vals.items()}},
              open(OUT + "/cands.json", "w"))


if __name__ == "__main__":
    main()
