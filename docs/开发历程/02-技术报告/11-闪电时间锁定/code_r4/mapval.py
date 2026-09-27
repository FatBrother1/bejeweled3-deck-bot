#!/usr/bin/env python3
"""倒计时值映射 —— 把画面读到的秒数 N 在所有表示形式下映射到内存槽。

比上一轮 scan_paused2.py 更全的表示类，且只扫「游戏数据段」（默认）或全内存（--all）。

用法：
  python3 mapval.py 47                 # 扫数据段，存 tag=47
  python3 mapval.py 43 --all           # 扫全部可写内存
  python3 mapval.py inter 47 43        # 求交集
"""
import ctypes, json, os, re, sys, time
sys.path.insert(0, "/home/deck")
import numpy as np
from reader_mem import _IOV, _libc, find_pid, GAPP_ADDR

CHUNK = 8 * 1024 * 1024


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


def data_regions(pid):
    r = region_of(pid, GAPP_ADDR)
    if r and "w" in r[2] and "/" not in r[3]:
        return [(r[0], r[1])]
    return []


def all_regions(pid):
    out = []
    for l in open("/proc/%d/maps" % pid):
        m = re.match(r"^([0-9a-f]+)-([0-9a-f]+)\s+(\S+)\s+\S+\s+\S+\s*\S*\s*(.*)", l)
        if not m:
            continue
        lo, hi = int(m.group(1), 16), int(m.group(2), 16)
        perm, path = m.group(3), m.group(4).strip()
        if "w" not in perm:
            continue
        if "/dev/" in path or ".so" in path or ".pak" in path or ".dll" in path:
            continue
        if hi - lo <= 0:
            continue
        out.append((lo, hi))
    return out


def windows_for(n):
    u = float(n)
    # 注意：窗口永不包含 0（2026-09-25 事故教训：曾因此 1.33 亿命中爆内存）
    return [
        ("i4",      "<i4", 4, n, n),
        ("i4x10",   "<i4", 4, n * 10, n * 10 + 9),
        ("i4x100",  "<i4", 4, n * 100, n * 100 + 99),
        ("i4x1000", "<i4", 4, n * 1000, n * 1000 + 999),
        ("i2",      "<i2", 2, n, n),
        ("f4",      "<f4", 4, u, u + 1.0),
        ("f8",      "<f8", 8, u, u + 1.0),
        ("f4x10",   "<f4", 4, n * 10.0, (n + 1) * 10.0),
        ("f8x10",   "<f8", 8, n * 10.0, (n + 1) * 10.0),
        ("f4x100",  "<f4", 4, n * 100.0, (n + 1) * 100.0),
        ("f4x1000", "<f4", 4, n * 1000.0, (n + 1) * 1000.0),
        ("ni4",     "<i4", 4, -n, -n),
        ("nf4",     "<f4", 4, -u - 1.0, -u),
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
            if size <= 0:
                break
            raw = rd(pid, lo + off0, size)
            if raw is None:
                off0 += size
                continue
            base = lo + off0
            for p in pats:
                st = 0
                while True:
                    i = raw.find(p, st)
                    if i < 0:
                        break
                    str_hits.append((base + i, p.decode()))
                    st = i + 1
            for kind, dt, step, vlo, vhi in W:
                cnt = len(raw) // step
                arr = np.frombuffer(raw[:cnt * step], dtype=dt)
                if dt == "<f8":
                    arr = arr.astype(np.float64)
                mask = (arr >= vlo) & (arr <= vhi)
                if dt in ("<f4", "<f8"):
                    mask &= np.isfinite(arr)
                idx = np.nonzero(mask)[0]
                if len(idx):
                    acc[kind][0].append(base + idx.astype(np.uint64) * step)
                    acc[kind][1].append(arr[idx].astype(np.float64))
            off0 += size
    out = {k: (np.concatenate(v[0]), np.concatenate(v[1])) for k, v in acc.items() if len(v[0])}
    return out, str_hits


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return
    pid = find_pid()
    if pid is None:
        print("  ❌ 游戏没在跑")
        return

    if sys.argv[1] == "inter":
        tags = sys.argv[2:]
        sets = []
        for t in tags:
            p = "/home/deck/map_%s.json" % t
            if not os.path.exists(p):
                print("  缺 %s" % p)
                return
            sets.append(json.load(open(p)))
        key = sets[0]["hits"] if "hits" in sets[0] else None
        # 交集：按 (kind, addr)
        acc = {}
        for s in sets:
            d = {(h["kind"], h["addr"]) for h in s["hits"]}
            acc = d if not acc else (acc & d)
        print("交集 %d 个（%s）" % (len(acc), " ∩ ".join(tags)))
        detail = {h["kind"] + "|" + h["addr"]: h for h in sets[-1]["hits"]}
        for k in sorted(acc)[:120]:
            h = detail.get(k[0] + "|" + k[1])
            print("   0x%-11s [%s] %.3f" % (k[1], k[0], h["val"] if h else 0))
        return

    n = int(sys.argv[1])
    use_all = "--all" in sys.argv
    tag = sys.argv[sys.argv.index("--tag") + 1] if "--tag" in sys.argv else str(n)
    regs = all_regions(pid) if use_all else data_regions(pid)
    tot = sum(b - a for a, b in regs) / 1048576.0
    print("N=%d  区域 %d 个 / %.1f MB  (%s)" % (n, len(regs), tot, "全内存" if use_all else "数据段"))
    t0 = time.perf_counter()
    cur, shits = scan_for(pid, regs, n)
    print("  耗时 %.2fs" % (time.perf_counter() - t0))
    hits = []
    for kind, (aa, vv) in sorted(cur.items()):
        print("  [%-7s] %d 个" % (kind, len(aa)))
        for a, v in zip(aa, vv):
            hits.append({"kind": kind, "addr": "0x%X" % int(a), "val": float(v)})
    for a, s in shits[:20]:
        print("    [文本] 0x%-11X %r" % (a, s))
        hits.append({"kind": "str", "addr": "0x%X" % a, "val": s})
    json.dump({"n": n, "hits": hits}, open("/home/deck/map_%s.json" % tag, "w"))
    print("  已存 /home/deck/map_%s.json（%d 条）" % (tag, len(hits)))


if __name__ == "__main__":
    main()
