#!/usr/bin/env python3
"""倒计时定位 v4 —— 只找「下降者」。

v3 教训：
  ① 率判据不分升降 → Board 里那组「游戏时钟」(每秒+1) 全程存活，全是噪声；
  ② 冻结/相关性用的裁剪框 (495..625,15..85) 是顶部中间的错误部件，
     真倒计时在右上角 (1025,18)~(1140,78)（修改器会话已验证）。
v4：活跃对局内 6 秒间隔三遍全扫，只要「严格下降且速率 ∈ {1,10,100,1000}/s」
  的地址 —— 时钟(上升)直接出局。对局中自动点续局，从 60 秒头部开始扫。
"""
import ctypes
import json
import os
import re
import sys
import time

import numpy as np

sys.path.insert(0, "/home/deck")
from reader_mem import _IOV, _libc, find_pid, GAPP_ADDR  # noqa: E402
from cap2 import Cap  # noqa: E402
from PIL import Image  # noqa: E402

_libc.process_vm_writev.restype = ctypes.c_ssize_t

CHUNK = 16 * 1024 * 1024
BOX = (1010, 10, 1155, 90)        # ★ 右上角倒计时框（修正）
GAP = 6.0                         # 扫描间隔

RATE_TOL = {1.0: 0.3, 10.0: 3.0, 100.0: 30.0, 1000.0: 300.0}
CLASSES = (
    ("s",   "<i4", 4, 1, 61),
    ("ms",  "<i4", 4, 100, 61000),
    ("f4",  "<f4", 4, 0.2, 65.0),
    ("f8",  "<f8", 8, 0.2, 65.0),
    ("f4b", "<f4", 4, 500.0, 65000.0),
    ("f8b", "<f8", 8, 500.0, 65000.0),
)
DT = {c[0]: (c[1], c[2]) for c in CLASSES}

WBUF = ctypes.create_string_buffer(8)


def raw_read(pid, addr, size):
    buf = ctypes.create_string_buffer(size)
    local = _IOV(ctypes.cast(buf, ctypes.c_void_p), size)
    remote = _IOV(ctypes.c_void_p(addr), size)
    n = _libc.process_vm_readv(pid, ctypes.byref(local), 1,
                               ctypes.byref(remote), 1, 0)
    return buf.raw[:n] if n == size else None


def read_val(pid, addr, kind):
    dt, step = DT[kind]
    raw = raw_read(pid, addr, step)
    if raw is None:
        return None
    return float(np.frombuffer(raw, dtype=dt)[0])


def rw_regions(pid):
    out = []
    with open("/proc/%d/maps" % pid) as f:
        for line in f:
            m = re.match(r"^([0-9a-f]+)-([0-9a-f]+)\s+(\S+)\s+(\S+)?", line)
            if not m:
                continue
            lo, hi, perm = int(m.group(1), 16), int(m.group(2), 16), m.group(3)
            path = m.group(4) or ""
            if "w" not in perm or hi - lo <= 0:
                continue
            if "/dev/" in path or ".pak" in path or ".so" in path:
                continue
            out.append((lo, hi))
    return out


def scan_once(pid, regs):
    acc = {c[0]: ([], []) for c in CLASSES}
    for lo, hi in regs:
        off0 = 0
        while off0 < hi - lo:
            size = min(CHUNK, hi - lo - off0)
            size -= size % 8
            if size <= 0:
                break
            raw = raw_read(pid, lo + off0, size)
            if raw is None:
                off0 += size
                continue
            base = lo + off0
            for kind, dt, step, vlo, vhi in CLASSES:
                n = len(raw) // step
                arr = np.frombuffer(raw[:n * step], dtype=dt)
                mask = (arr >= vlo) & (arr <= vhi)
                idx = np.nonzero(mask)[0]
                if len(idx):
                    acc[kind][0].append(base + idx.astype(np.uint64) * step)
                    acc[kind][1].append(arr[idx].astype(np.float64))
            off0 += size
    out = {}
    for kind, (aa, vv) in acc.items():
        if aa:
            out[kind] = (np.concatenate(aa), np.concatenate(vv))
    return out


def fallers(prev, cur, dt):
    """按(地址,kind)求交，只要严格下降且速率匹配。"""
    out = {}
    for kind in prev:
        if kind not in cur:
            continue
        pa, pv = prev[kind]
        ca, cv = cur[kind]
        order = np.argsort(ca)
        ca, cv = ca[order], cv[order]
        lo = np.searchsorted(ca, pa)
        hi = np.searchsorted(ca, pa, side="right")
        hit = np.nonzero(hi > lo)[0]
        if not len(hit):
            continue
        rate = (pv[hit] - cv[lo[hit]]) / dt
        good = np.zeros(len(hit), dtype=bool)
        for k, tol in RATE_TOL.items():
            good |= np.abs(rate - k) < tol          # 只要下降
        if good.any():
            out[kind] = (pa[hit][good], cv[lo[hit]][good])
    return out


def grab(cap):
    for _ in range(12):
        a = cap.get(timeout=0.5)
        if a is not None:
            return a
    return None


def main():
    import bot_v6
    from vmouse2 import VMouse2
    os.makedirs("/home/deck/tcap", exist_ok=True)
    pid = find_pid()
    g = board = None
    raw = raw_read(pid, GAPP_ADDR, 4)
    if raw:
        g = int(np.frombuffer(raw, dtype="<u4")[0])
        rb = raw_read(pid, g + 0xBE8, 4)
        if rb:
            board = int(np.frombuffer(rb, dtype="<u4")[0])
    regs = rw_regions(pid)
    print("  PID=%d Board=%s 可写 %.0f MB"
          % (pid, hex(board) if board else "?",
             sum(h - l for l, h in regs) / 1e6), flush=True)

    cap = Cap()
    vm = VMouse2()

    def fresh_round():
        """结算就点续局；点完等 4.5s（等『开始!』过、倒计时接近满）。"""
        f = grab(cap)
        if f is not None and bot_v6.screen_is_gameover(f):
            vm.click(640, 738)
            print("    （结算 → 点『再玩一次』）", flush=True)
            time.sleep(4.5)
            return True
        return False

    # 起点尽量在满时间附近：先续一局
    if not fresh_round():
        f = grab(cap)
        # 已经在对局里也行，但剩余时间未知 —— 照扫，6 秒窗口不会跨局
    print("  ═══ S0 → S1 → S2（间隔 %.0fs，只找下降者）═══" % GAP, flush=True)

    t0 = time.perf_counter()
    S0 = scan_once(pid, regs)
    Image.fromarray(grab(cap)).crop(BOX).save("/home/deck/tcap/s0.png")
    print("  S0: " + ", ".join("%s=%d" % (k, len(v[0])) for k, v in S0.items())
          + " (%.1fs)" % (time.perf_counter() - t0), flush=True)

    time.sleep(GAP)
    t1 = time.perf_counter()
    S1 = scan_once(pid, regs)
    dt1 = t1 - t0
    A = fallers(S0, S1, dt1)
    del S0
    print("  S1: 下降者 " + ", ".join("%s=%d" % (k, len(v[0])) for k, v in A.items())
          + " (%.1fs, dt=%.2f)" % (time.perf_counter() - t1, dt1), flush=True)

    time.sleep(GAP)
    t2 = time.perf_counter()
    # S2 前用幸存者值回读代替全扫（快 100 倍）
    surv = {}
    for kind, (aa, vv) in A.items():
        vals = np.array([read_val(pid, int(a), kind) or -1e9 for a in aa])
        rate = (vv - vals) / (t2 - t1)
        good = np.zeros(len(aa), dtype=bool)
        for k, tol in RATE_TOL.items():
            good |= np.abs(rate - k) < tol
        if good.any():
            surv[kind] = (aa[good], vals[good])
    del S1, A
    n = sum(len(v[0]) for v in surv.values())
    print("  S2 回读: 下降者 %d" % n, flush=True)

    print()
    print("  ═══ 幸存下降者 ═══")
    rows = []
    for kind, (aa, vv) in surv.items():
        for i in range(len(aa)):
            addr = int(aa[i])
            v = float(vv[i])
            rel = ""
            if board and board <= addr < board + 0x4000:
                rel = "Board+0x%X" % (addr - board)
            elif g and g <= addr < g + 0x20000:
                rel = "gApp+0x%X" % (addr - g)
            elif 0x400000 <= addr < 0x940000:
                rel = "主模块数据段"
            rows.append((addr, kind, v, rel))
            print("    0x%-11X [%s] 值=%-12.2f %s" % (addr, kind, v, rel))
    with open("/home/deck/timer_fallers.txt", "w") as f:
        for addr, kind, v, rel in rows:
            f.write("0x%X %s %.4f %s\n" % (addr, kind, v, rel))
    print("  已存 /home/deck/timer_fallers.txt")
    cap.stop()
    vm.close()


if __name__ == "__main__":
    main()
