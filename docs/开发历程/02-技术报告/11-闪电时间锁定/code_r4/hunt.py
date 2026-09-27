#!/usr/bin/env python3
"""hunt.py —— 暂停态「边读边搜、只留命中」倒计时定位（零内存风险）。

为什么换这个方法（本轮事故教训）：
  · 全量快照差分要存 1.1GB×N 份 → 两次触发 earlyoom 杀进程 + 游戏退出。
  · 恢复上一轮验证过的思路：暂停时画面上的秒数 N 就是内存里的值，
    全内存搜 N 的所有表示，**只保留命中地址**（几千条），内存占用 O(命中数)。
  · 多拍几次、取交集，即可把「主控」与「每帧被覆写的副本」区分开。

配套流程（脚本只负责搜，N 由读图得到）：
  python3 hunt.py pause              # 自愈暂停 + 抓全屏图（供读 N）
  python3 hunt.py find N tag         # 边读边搜 N 的所有表示，存命中
  python3 hunt.py inter tag1 tag2 …  # 多个 tag 求交
"""
import ctypes, json, os, re, subprocess, sys, time
sys.path.insert(0, "/home/deck")
import numpy as np
from reader_mem import _IOV, _libc, find_pid, GAPP_ADDR, OFF_BOARD

CHUNK = 256 * 1024
DIR = "/home/deck/hunt"
W, H = 1280, 800
MENU = (215, 730)
BACK = (882, 597)


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


def board_of(pid):
    g = ru32(pid, GAPP_ADDR)
    return ru32(pid, g + OFF_BOARD) if g else None


def clock(pid):
    b = board_of(pid)
    if not b:
        return None, None
    return ru32(pid, b + 0x38), ru32(pid, b + 0xC84)


def is_paused(pid):
    c1, _ = clock(pid)
    if c1 is None:
        return None
    time.sleep(0.3)
    c2, _ = clock(pid)
    time.sleep(0.3)
    c3, _ = clock(pid)
    if c2 is None or c3 is None:
        return None
    return c1 == c2 == c3


def click(pt):
    from vmouse2 import VMouse2
    m = VMouse2()
    m.click(pt[0], pt[1])
    m.close()


def shot(path):
    subprocess.run(["timeout", "20", "gst-launch-1.0", "-q", "pipewiresrc",
                    "path=93", "num-buffers=1", "!", "videoconvert", "!",
                    "pngenc", "!", "filesink", "location=" + path],
                   capture_output=True)
    return path


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


def windows(n):
    """N 的所有可能表示。注意窗口永不包含 0。"""
    u = float(n)
    return [
        ("i4",     "<i4", 4, n - 1, n + 1),
        ("i4x10",  "<i4", 4, n * 10 - 5, n * 10 + 9),
        ("i4x100", "<i4", 4, n * 100 - 50, n * 100 + 99),
        ("i4x1000","<i4", 4, n * 1000 - 500, n * 1000 + 999),
        ("f4",     "<f4", 4, u - 1.0, u + 1.0),
        ("f4x10",  "<f4", 4, (n - 1) * 10.0, (n + 1) * 10.0),
        ("f4x100", "<f4", 4, (n - 1) * 100.0, (n + 1) * 100.0),
        ("f4x1000","<f4", 4, (n - 1) * 1000.0, (n + 1) * 1000.0),
        ("f8",     "<f8", 8, u - 1.0, u + 1.0),
        ("f8x10",  "<f8", 8, (n - 1) * 10.0, (n + 1) * 10.0),
    ]


def do_pause():
    pid = find_pid()
    if pid is None:
        print("❌ 游戏没在跑")
        return
    for i in range(4):
        st = is_paused(pid)
        if st is True:
            break
        click(MENU)
        time.sleep(1.0)
    else:
        st = is_paused(pid)
    cs, s = clock(pid)
    print("暂停状态=%s  Board=%s  cs=%s s=%s"
          % (st, hex(board_of(pid) or 0), cs, s))
    p = shot("%s/full.png" % DIR)
    print("全屏图：%s（请读倒计时秒数）" % p)


def do_find(n, tag):
    pid = find_pid()
    if pid is None:
        print("❌ 游戏没在跑")
        return
    st = is_paused(pid)
    if st is not True:
        print("⚠️ 当前不是暂停态（%s），结果可能不准" % st)
    cs, s = clock(pid)
    W_list = windows(n)
    hits = {k[0]: ([], []) for k in W_list}
    strs = []
    pats = [("%d:%02d" % (n // 60, n % 60)).encode(),
            ("%d:%d" % (n // 60, n % 60)).encode()]
    t0 = time.perf_counter()
    for lo, hi in regions(pid):
        off = 0
        while off < hi - lo:
            sz = min(CHUNK, hi - lo - off)
            d = rd(pid, lo + off, sz)
            if d is None or len(d) != sz:
                off += sz
                continue
            base = lo + off
            for p in pats:
                stt = 0
                while True:
                    i = d.find(p, stt)
                    if i < 0:
                        break
                    strs.append(base + i)
                    stt = i + 1
            c4 = len(d) // 4
            a4 = np.frombuffer(d[:c4 * 4], "<i4")
            f4v = a4.view("<f4")
            for name, dt, step, vlo, vhi in W_list:
                if dt == "<i4":
                    m = (a4 >= vlo) & (a4 <= vhi)
                    if m.any():
                        idx = np.nonzero(m)[0]
                        hits[name][0].append(base + idx.astype(np.uint64) * 4)
                        hits[name][1].append(a4[idx])
                elif dt == "<f4":
                    m = np.isfinite(f4v) & (f4v >= vlo) & (f4v <= vhi)
                    if m.any():
                        idx = np.nonzero(m)[0]
                        hits[name][0].append(base + idx.astype(np.uint64) * 4)
                        hits[name][1].append(f4v[idx])
            c8 = len(d) // 8
            f8v = np.frombuffer(d[:c8 * 8], "<f8")
            for name, dt, step, vlo, vhi in W_list:
                if dt != "<f8":
                    continue
                m = np.isfinite(f8v) & (f8v >= vlo) & (f8v <= vhi)
                if m.any():
                    idx = np.nonzero(m)[0]
                    hits[name][0].append(base + idx.astype(np.uint64) * 8)
                    hits[name][1].append(f8v[idx])
            off += sz
    el = time.perf_counter() - t0
    os.makedirs(DIR, exist_ok=True)
    out = {}
    tot = 0
    print("N=%d  cs=%s  扫描 %.2fs" % (n, cs, el))
    for name, _, _, _, _ in W_list:
        aa, vv = hits[name]
        A = np.concatenate(aa) if aa else np.zeros(0, np.uint64)
        V = np.concatenate(vv) if vv else np.zeros(0)
        out[name + "_a"] = A
        out[name + "_v"] = V.astype(np.float64)
        tot += len(A)
        if len(A):
            print("   [%-8s] %d" % (name, len(A)))
    np.savez("%s/%s.npz" % (DIR, tag), **out)
    if strs:
        print("   [str     ] %d" % len(strs))
        open("%s/%s_str.txt" % (DIR, tag), "w").write(
            "\n".join("0x%X" % x for x in strs))
    json.dump({"n": n, "cs": cs}, open("%s/%s.json" % (DIR, tag), "w"))
    print("   合计 %d 条 → %s/%s.npz" % (tot, DIR, tag))


def do_inter(tags):
    sets = []
    for t in tags:
        z = np.load("%s/%s.npz" % (DIR, t))
        d = {}
        for k in z.files:
            if k.endswith("_a"):
                name = k[:-2]
                for a in z[k]:
                    d[(name, int(a))] = None
        meta = json.load(open("%s/%s.json" % (DIR, t)))
        sets.append((t, meta["n"], d))
    print("各次命中：" + "  ".join("%s(N=%d)=%d" % (t, n, len(d)) for t, n, d in sets))
    keys = set(sets[0][2])
    for _, _, d in sets[1:]:
        keys &= set(d)
    print("\n★ 交集 %d 个：" % len(keys))
    for name, a in sorted(keys)[:200]:
        print("   0x%-11X [%s]" % (a, name))
    np.savez("%s/hit.npz" % DIR,
             A=np.array([a for _, a in sorted(keys)], dtype=np.uint64),
             N=np.array([n for n, _ in sorted(keys)]))


if __name__ == "__main__":
    os.makedirs(DIR, exist_ok=True)
    c = sys.argv[1] if len(sys.argv) > 1 else "pause"
    if c == "pause":
        do_pause()
    elif c == "find":
        do_find(int(sys.argv[2]), sys.argv[3])
    elif c == "inter":
        do_inter(sys.argv[2:])
    else:
        print(__doc__)
