#!/usr/bin/env python3
"""暂停态扫描 v2 —— 扩展表示类：十分秒/负数/文本 "0:56"。

用法：
  python3 scan_paused2.py 51          # 第一次
  python3 scan_paused2.py 48 51       # 第二次 + 交集
"""
import ctypes, os, re, sys, time
import numpy as np
sys.path.insert(0, "/home/deck")
from reader_mem import _IOV, _libc, find_pid, GAPP_ADDR

CHUNK = 16 * 1024 * 1024

def raw_read(pid, addr, size):
    buf = ctypes.create_string_buffer(size)
    local = _IOV(ctypes.cast(buf, ctypes.c_void_p), size)
    remote = _IOV(ctypes.c_void_p(addr), size)
    n = _libc.process_vm_readv(pid, ctypes.byref(local), 1, ctypes.byref(remote), 1, 0)
    return buf.raw[:n] if n == size else None

def rw_regions(pid):
    out = []
    with open("/proc/%d/maps" % pid) as f:
        for line in f:
            m = re.match(r"^([0-9a-f]+)-([0-9a-f]+)\s+(\S+)\s+(\S+)?", line)
            if not m: continue
            lo, hi, perm = int(m.group(1), 16), int(m.group(2), 16), m.group(3)
            path = m.group(4) or ""
            if "w" not in perm or hi - lo <= 0: continue
            if "/dev/" in path or ".pak" in path or ".so" in path: continue
            out.append((lo, hi))
    return out

def windows_for(n):
    u = float(n)
    return [
        ("s",   "<i4", 4, n, n),
        ("t",   "<i4", 4, n*10, (n+1)*10 - 1),
        ("cs",  "<i4", 4, n*100, (n+1)*100 - 1),
        ("ms",  "<i4", 4, n*1000, (n+1)*1000 - 1),
        ("f4s", "<f4", 4, u, u+1.0),
        ("f8s", "<f8", 8, u, u+1.0),
        ("f4t", "<f4", 4, n*10.0, (n+1)*10.0),
        ("f8t", "<f8", 8, n*10.0, (n+1)*10.0),
        ("f4c", "<f4", 4, n*100.0, (n+1)*100.0),
        ("f8c", "<f8", 8, n*100.0, (n+1)*100.0),
        ("f4m", "<f4", 4, n*1000.0, (n+1)*1000.0),
        ("f8m", "<f8", 8, n*1000.0, (n+1)*1000.0),
        ("ns",  "<i4", 4, -n, -n),
        ("nt",  "<i4", 4, -(n+1)*10+1, -n*10),
        ("ncs", "<i4", 4, -(n+1)*100+1, -n*100),
        ("nms", "<i4", 4, -(n+1)*1000+1, -n*1000),
        ("nf4s","<f4", 4, -(n+1.0), -u),
        ("nf8s","<f8", 8, -(n+1.0), -u),
        ("nf4t","<f4", 4, -(n+1)*10.0, -n*10.0),
        ("nf8t","<f8", 8, -(n+1)*10.0, -n*10.0),
    ]

def scan_for(pid, regs, n):
    W = windows_for(n)
    acc = {w[0]: ([], []) for w in W}
    pats = [("%d:%02d" % (n // 60, n % 60)).encode(),
            ("%d:%d" % (n // 60, n % 60)).encode()]
    str_hits = []
    for lo, hi in regs:
        off0 = 0
        while off0 < hi - lo:
            size = min(CHUNK, hi - lo - off0)
            size -= size % 8
            if size <= 0: break
            raw = raw_read(pid, lo + off0, size)
            if raw is None:
                off0 += size; continue
            base = lo + off0
            for p in pats:
                start = 0
                while True:
                    i = raw.find(p, start)
                    if i < 0: break
                    str_hits.append((base + i, p.decode()))
                    start = i + 1
            for kind, dt, step, vlo, vhi in W:
                cnt = len(raw) // step
                arr = np.frombuffer(raw[:cnt*step], dtype=dt)
                mask = (arr >= vlo) & (arr <= vhi)
                idx = np.nonzero(mask)[0]
                if len(idx):
                    acc[kind][0].append(base + idx.astype(np.uint64) * step)
                    acc[kind][1].append(arr[idx].astype(np.float64))
            off0 += size
    out = {k: (np.concatenate(v[0]), np.concatenate(v[1])) for k, v in acc.items() if v[0]}
    return out, str_hits

def rel_of(addr, board, g):
    if board and board <= addr < board + 0x4000: return "Board+0x%X" % (addr - board)
    if g and g <= addr < g + 0x20000: return "gApp+0x%X" % (addr - g)
    return ""

def main():
    n2 = int(sys.argv[1]); n1 = int(sys.argv[2]) if len(sys.argv) > 2 else None
    pid = find_pid()
    if pid is None:
        print("  ❌ 游戏没在跑"); return
    g = board = None
    raw = raw_read(pid, GAPP_ADDR, 4)
    if raw:
        g = int(np.frombuffer(raw, dtype="<u4")[0])
        rb = raw_read(pid, g + 0xBE8, 4)
        if rb: board = int(np.frombuffer(rb, dtype="<u4")[0])
    print("  PID=%d Board=%s 值=%d" % (pid, hex(board) if board else "?", n2), flush=True)
    regs = rw_regions(pid)
    t0 = time.perf_counter()
    cur, shits = scan_for(pid, regs, n2)
    print("  命中: " + ", ".join("%s=%d" % (k, len(v[0])) for k, v in sorted(cur.items()))
          + "  文本=%d  (%.1fs)" % (len(shits), time.perf_counter()-t0), flush=True)
    for a, s in shits[:20]:
        print("    [文本] 0x%-11X %r %s" % (a, s, rel_of(a, board, g)))
    if n1 is None:
        np.savez("/home/deck/pause2_%d.npz" % n2,
                 **{k+"_a": v[0] for k, v in cur.items()},
                 **{k+"_v": v[1] for k, v in cur.items()})
        with open("/home/deck/pause2_%d_str.txt" % n2, "w") as f:
            for a, s in shits: f.write("0x%X %s\n" % (a, s))
        shown = 0
        for kind, (aa, vv) in sorted(cur.items()):
            for i in range(len(aa)):
                if shown >= 30: break
                a = int(aa[i])
                print("    0x%-11X [%s] %.3f %s" % (a, kind, vv[i], rel_of(a, board, g)))
                shown += 1
        print("  已存 pause2_%d.npz（%d 个）" % (n2, sum(len(v[0]) for v in cur.values())))
        return
    old = np.load("/home/deck/pause2_%d.npz" % n1)
    try:
        olds = dict(l.split(None, 1) for l in open("/home/deck/pause2_%d_str.txt" % n1).read().splitlines() and
                    [("0x%X" % int(l.split()[0], 16), l.split()[1]) for l in open("/home/deck/pause2_%d_str.txt" % n1)])
    except Exception:
        olds = {}
    total = 0
    for a, s in shits:
        key = "0x%X" % a
        if key in olds:
            print("  ★[文本] 0x%X %r → %r %s" % (a, olds[key], s, rel_of(a, board, g)))
            total += 1
    for kind, (aa, vv) in sorted(cur.items()):
        key = kind + "_a"
        if key not in old: continue
        oa, ov = old[key], old[kind+"_v"]
        if not len(oa): continue
        pos = {int(a): float(v) for a, v in zip(oa, ov)}
        s1 = set(pos)
        both = [(int(a), float(v)) for a, v in zip(aa, vv) if int(a) in s1]
        if not both: continue
        print("  [%s] %d 个:" % (kind, len(both)))
        for a, v in both[:60]:
            total += 1
            print("    0x%-11X  %d时=%-11.3f 现在=%.3f  %s" % (a, n1, pos[a], v, rel_of(a, board, g)))
    print("  交集合计 %d 个" % total)

if __name__ == "__main__":
    main()
