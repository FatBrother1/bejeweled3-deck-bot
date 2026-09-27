#!/usr/bin/env python3
"""pintest.py —— 决定性钉住实验（带同步截图）。

对候选地址写入 「当前值 + DELTA」，然后立刻持续保持，并在
写入前 / 写入后多个时刻各抓一帧，便于前后对照画面。

用法：
  python3 pintest.py 0xADDR f4 300 12
      地址     类型 增量  保持秒数
"""
import ctypes, subprocess, sys, time
sys.path.insert(0, "/home/deck")
import numpy as np
from reader_mem import _IOV, _libc, find_pid

DT = {"i4": "<i4", "f4": "<f4", "f8": "<f8", "i2": "<i2", "u4": "<u4"}
_libc.process_vm_writev.restype = ctypes.c_ssize_t
WBUF = ctypes.create_string_buffer(8)


def rd(pid, addr, dt, step):
    b = ctypes.create_string_buffer(step)
    lo = _IOV(ctypes.cast(b, ctypes.c_void_p), step)
    r = _IOV(ctypes.c_void_p(addr), step)
    n = _libc.process_vm_readv(pid, ctypes.byref(lo), 1, ctypes.byref(r), 1, 0)
    if n != step:
        return None
    return float(np.frombuffer(b.raw[:step], dtype=dt)[0])


def wr(pid, addr, data):
    WBUF.raw = data
    lo = _IOV(ctypes.cast(WBUF, ctypes.c_void_p), len(data))
    r = _IOV(ctypes.c_void_p(addr), len(data))
    return _libc.process_vm_writev(pid, ctypes.byref(lo), 1, ctypes.byref(r), 1, 0)


def shot(p):
    subprocess.run(["timeout", "20", "gst-launch-1.0", "-q", "pipewiresrc",
                    "path=93", "num-buffers=1", "!", "videoconvert", "!",
                    "pngenc", "!", "filesink", "location=" + p],
                   capture_output=True)


def main():
    addr = int(sys.argv[1], 16)
    kind = sys.argv[2]
    delta = float(sys.argv[3])
    hold = float(sys.argv[4])
    dt = DT[kind]
    step = 8 if dt == "<f8" else (2 if dt == "<i2" else 4)
    pid = find_pid()
    v0 = rd(pid, addr, dt, step)
    print("PID=%d  0x%X [%s] 当前=%.3f" % (pid, addr, kind, v0), flush=True)
    shot("/tmp/tlock/pin_before.png")
    tgt = v0 + delta
    payload = np.array(tgt, dtype=dt).tobytes()
    wr(pid, addr, payload)
    print("→ 已写入 %.3f（+%.1f）" % (tgt, delta), flush=True)
    t0 = time.time()
    marks = [0.0, 0.8, 2.0, 4.0, 7.0, 10.0]
    mi = 0
    n = 0
    while time.time() - t0 < hold:
        el = time.time() - t0
        if mi < len(marks) and el >= marks[mi]:
            v = rd(pid, addr, dt, step)
            shot("/tmp/tlock/pin_%04.1f.png" % marks[mi])
            print("  t=%5.1fs 回读=%-12.3f (帧 pin_%04.1f.png)" % (el, v, marks[mi]), flush=True)
            mi += 1
        wr(pid, addr, payload)
        n += 1
        time.sleep(0.03)
    v = rd(pid, addr, dt, step)
    print("结束：保持 %.1fs，写 %d 次，终值=%.3f" % (hold, n, v))


if __name__ == "__main__":
    main()
