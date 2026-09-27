#!/usr/bin/env python3
"""pauto.py —— 全自动暂停法定位倒计时。

关键机制（2026-09-25 实测发现）：
  闪电局中点左下「菜单」会弹出【选项】覆盖层，此时**游戏逻辑暂停**、
  倒计时定在画面上不动，但进程仍在运行 —— 可以随时读内存、抓帧。
  这就是上一轮「用户暂停报数」法的机制，且现在可以全自动。

流程：
  1. 进局，等 1.2s，点「菜单」暂停
  2. 冻结抓帧读秒 N1 + 转储 N1 的所有表示
  3. 点「返回」继续 2.5s，再点「菜单」暂停
  4. 转储 N2，求交 → 母本候选
"""
import ctypes, os, re, signal, subprocess, sys, time
sys.path.insert(0, "/home/deck")
import numpy as np
from reader_mem import _IOV, _libc, find_pid, GAPP_ADDR, OFF_BOARD

CHUNK = 512 * 1024
W, H = 1280, 800
OUT = "/tmp/tlock"
MENU = (215, 730)      # 游戏内左下「菜单」
BACK = (889, 598)      # 选项面板「返回」

KINDS = [
    ("i4s", "<i4", 4, lambda n: (n, n)),
    ("i4t", "<i4", 4, lambda n: (n * 10, n * 10 + 9)),
    ("i4c", "<i4", 4, lambda n: (n * 100, n * 100 + 99)),
    ("i4m", "<i4", 4, lambda n: (n * 1000, n * 1000 + 999)),
    ("f4s", "<f4", 4, lambda n: (n, n + 1.0)),
    ("f4t", "<f4", 4, lambda n: (n * 10.0, (n + 1) * 10.0)),
    ("f4c", "<f4", 4, lambda n: (n * 100.0, (n + 1) * 100.0)),
    ("f4m", "<f4", 4, lambda n: (n * 1000.0, (n + 1) * 1000.0)),
    ("f8s", "<f8", 8, lambda n: (n, n + 1.0)),
    ("f8t", "<f8", 8, lambda n: (n * 10.0, (n + 1) * 10.0)),
]


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


def shot(path, crop_top=True):
    cmd = ["timeout", "20", "gst-launch-1.0", "-q", "pipewiresrc", "path=93",
           "num-buffers=1", "!", "videoconvert", "!"]
    if crop_top:
        cmd += ["videocrop", "left=980", "right=%d" % (W - 1170),
                "top=5", "bottom=%d" % (H - 100), "!",
                "videoscale", "!", "video/x-raw,width=1140", "!"]
    cmd += ["pngenc", "!", "filesink", "location=" + path]
    subprocess.run(cmd, capture_output=True)
    return path


def dump(pid, regs, n, tag):
    res = {}
    for name, _, _, _ in KINDS:
        res[name] = [[], []]
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
            f4v = a4.view("<f4")
            c8 = len(d) // 8
            f8v = np.frombuffer(d[:c8 * 8], "<f8")
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
    for name, _, _, _ in KINDS:
        aa, vv = res[name]
        npz[name + "_a"] = np.concatenate(aa) if aa else np.zeros(0, np.uint64)
        npz[name + "_v"] = np.concatenate(vv) if vv else np.zeros(0, np.float64)
    np.savez("%s/pa_%s.npz" % (OUT, tag), **npz)
    cnt = {name: len(npz[name + "_a"]) for name, _, _, _ in KINDS}
    print("  [%s] 命中 %s" % (tag, " ".join("%s=%d" % kv for kv in cnt.items() if kv[1])), flush=True)


def inter(t1, n1, t2, n2):
    a = np.load("%s/pa_%s.npz" % (OUT, t1))
    b = np.load("%s/pa_%s.npz" % (OUT, t2))
    da = {}
    db = {}
    for name, _, _, _ in KINDS:
        for x, v in zip(a[name + "_a"], a[name + "_v"]):
            da[(name, int(x))] = float(v)
        for x, v in zip(b[name + "_a"], b[name + "_v"]):
            db[(name, int(x))] = float(v)
    print("快照 %s(%d) %d 个，快照 %s(%d) %d 个" % (t1, n1, len(da), t2, n2, len(db)))
    keys = set(da) & set(db)
    print("★ 交集 %d 个：" % len(keys))
    drop = n1 - n2
    rows = []
    for k in keys:
        v1, v2 = da[k], db[k]
        if abs((v1 - v2) - drop) > 1.2:
            continue
        rows.append((k[1], k[0], v1, v2))
    rows.sort()
    for x, name, v1, v2 in rows[:150]:
        print("   0x%-11X [%-5s] %14.4f → %14.4f" % (x, name, v1, v2))
    print("  （同向且落差匹配的共 %d 个）" % len(rows))
    np.savez("%s/pa_hit.npz" % OUT, A=np.array([r[0] for r in rows], dtype=np.uint64))


def main():
    pid = find_pid()
    if pid is None:
        print("  ❌ 游戏没在跑")
        return
    if sys.argv[1] == "inter":
        inter(sys.argv[2], int(sys.argv[3]), sys.argv[4], int(sys.argv[5]))
        return
    n1 = int(sys.argv[1])
    n2 = int(sys.argv[2])
    regs = regions(pid)
    print("PID=%d 区 %d 个 / %.1f MB" % (pid, len(regs), sum(h - l for l, h in regs) / 1048576))
    print("[1] 暂停态转储 N=%d" % n1)
    dump(pid, regs, n1, "1")
    print("[2] 恢复 3s 后再次暂停转储 N=%d" % n2)
    click(BACK, 3.0)
    click(MENU, 1.2)
    shot("%s/pa_check2.png" % OUT)
    dump(pid, regs, n2, "2")
    print("完成。请核对 %s/pa_check2.png 上的秒数是否为 %d" % (OUT, n2))


if __name__ == "__main__":
    main()
