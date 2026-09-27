#!/usr/bin/env python3
"""定向冻结甄别：对上一轮幸存者里的高价值子集做冻结测试。

判据修正：命中 = 冻结期框内像素帧间差 < 1.5（绝对值，框真的不动），
不再用相对阈值（上轮 基线27.67/冻结5.95 被误判命中是错的）。

附带诊断：冻结期间同时回读该地址 —— 若值在我们反复写原值的情况下
仍被改写，说明它是"被权威源刷新的副本"（或写没生效）。
"""
import ctypes
import sys
import time

import numpy as np

sys.path.insert(0, "/home/deck")
from reader_mem import _IOV, _libc, find_pid, GAPP_ADDR  # noqa: E402
from cap2 import Cap  # noqa: E402
from PIL import Image  # noqa: E402

_libc.process_vm_writev.restype = ctypes.c_ssize_t
BOX = (495, 15, 625, 85)
WBUF = ctypes.create_string_buffer(8)

# (地址, 类型) —— 来自 tscan2 幸存者清单；最后一个是对照组(预期否)
CANDS = [
    (0xF3A1DDC, "s"),     # Board+0xC84  int 秒 ★ 头号嫌疑
    (0xF3A1190, "ms"),    # Board+0x38
    (0xF3A1F90, "ms"),    # Board+0xE38
    (0xF3A1F94, "ms"),    # Board+0xE3C
    (0xF3A4200, "q"),     # Board+0x30A8
    (0xA1F0358, "ms"),
    (0x1E3F8D04, "f4b"),  # 对照组：f4b 噪声簇代表
]

DT = {"s": ("<i4", 4), "ms": ("<i4", 4), "q": ("<i8", 8),
      "f4": ("<f4", 4), "f8": ("<f8", 8), "f4b": ("<f4", 4), "f8b": ("<f8", 8)}


def raw_read(pid, addr, size):
    buf = ctypes.create_string_buffer(size)
    local = _IOV(ctypes.cast(buf, ctypes.c_void_p), size)
    remote = _IOV(ctypes.c_void_p(addr), size)
    n = _libc.process_vm_readv(pid, ctypes.byref(local), 1,
                               ctypes.byref(remote), 1, 0)
    return buf.raw[:n] if n == size else None


def raw_write(pid, addr, data):
    WBUF.raw = data
    local = _IOV(ctypes.cast(WBUF, ctypes.c_void_p), len(data))
    remote = _IOV(ctypes.c_void_p(addr), len(data))
    return _libc.process_vm_writev(pid, ctypes.byref(local), 1,
                                   ctypes.byref(remote), 1, 0)


def read_val(pid, addr, kind):
    dt, step = DT[kind]
    raw = raw_read(pid, addr, step)
    if raw is None:
        return None
    return float(np.frombuffer(raw, dtype=dt)[0])


def encode(kind, v):
    dt, _ = DT[kind]
    return np.array(v, dtype=dt).tobytes()


def grab(cap):
    for _ in range(12):
        a = cap.get(timeout=0.5)
        if a is not None:
            return a
    return None


def crops_mean_diff(crops):
    if len(crops) < 2:
        return 99.0
    return float(np.mean([np.abs(crops[i] - crops[i + 1]).mean()
                          for i in range(len(crops) - 1)]))


def main():
    pid = find_pid()
    board = None
    g = None
    raw = raw_read(pid, GAPP_ADDR, 4)
    if raw:
        g = int(np.frombuffer(raw, dtype="<u4")[0])
        rb = raw_read(pid, g + 0xBE8, 4)
        if rb:
            board = int(np.frombuffer(rb, dtype="<u4")[0])
    print("  PID=%d gApp=%s Board=%s" % (pid, hex(g) if g else "?",
                                         hex(board) if board else "?"))
    cap = Cap()
    winner = None
    for addr, kind in CANDS:
        v0 = read_val(pid, addr, kind)
        if v0 is None:
            print("  0x%-11X [%s] 读不到" % (addr, kind))
            continue
        rel = ""
        if board and board <= addr < board + 0x4000:
            rel = "Board+0x%X" % (addr - board)
        elif g and g <= addr < g + 0x20000:
            rel = "gApp+0x%X" % (addr - g)
        # 基线 3.2s
        crops = []
        t_end = time.perf_counter() + 3.2
        while time.perf_counter() < t_end:
            f = grab(cap)
            if f is not None:
                crops.append(np.asarray(Image.fromarray(f).crop(BOX),
                                        dtype=np.int16))
            time.sleep(0.3)
        d_tick = crops_mean_diff(crops)
        # 冻结 4.5s：写回原值 + 同步回读看是否被覆盖
        payload = encode(kind, v0)
        t_end = time.perf_counter() + 4.5
        nw = n_ok = 0
        lo_v = hi_v = v0
        crops = []
        while time.perf_counter() < t_end:
            nw += 1
            if raw_write(pid, addr, payload) == len(payload):
                n_ok += 1
            v = read_val(pid, addr, kind)
            if v is not None:
                lo_v, hi_v = min(lo_v, v), max(hi_v, v)
            f = grab(cap)
            if f is not None:
                crops.append(np.asarray(Image.fromarray(f).crop(BOX),
                                        dtype=np.int16))
            time.sleep(0.15)
        d_frz = crops_mean_diff(crops)
        hit = d_tick > 1.0 and d_frz < 1.5
        stayed = abs(hi_v - lo_v) < 1e-3
        print("  0x%-11X [%s] %-14s 值=%-9.3f 基线=%6.2f 冻结=%6.2f "
              "写%d/%d 冻结期值漂移=%.3f → %s%s"
              % (addr, kind, rel, v0, d_tick, d_frz, n_ok, nw,
                 hi_v - lo_v,
                 "★命中" if hit else "否",
                 "  (值被钉住)" if stayed else "  (值仍在变→副本/写失败)"))
        if hit and winner is None:
            winner = (addr, kind, v0)
        time.sleep(1.2)
    cap.stop()
    print()
    if winner:
        addr, kind, v0 = winner
        print("  ★★★ 倒计时字段 = 0x%X [%s]（测试钉在 %.0f）★★★" % (addr, kind, v0))
        print("  锁定：python3 tscan2.py hold 300 0x%X %s" % (addr, kind))
        with open("/home/deck/timer_winner.txt", "w") as f:
            f.write("0x%X %s\n" % (addr, kind))
    else:
        print("  ❌ 本组全否 —— 把冻结差最小的当线索继续查")


if __name__ == "__main__":
    main()
