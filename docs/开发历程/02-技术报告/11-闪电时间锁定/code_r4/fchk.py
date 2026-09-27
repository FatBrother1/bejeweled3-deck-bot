#!/usr/bin/env python3
"""fchk.py —— 冻结同步校验：冻结瞬间同时读内存候选 + 抓帧。

冻结时游戏完全静止，因此「帧上的秒数」与「内存里的值」严格同一时刻，
彻底消除 PipeWire 抓帧延迟带来的读数偏差。

用法：
  python3 fchk.py 0x3936BD78 i4 0x.... f4 ...
  或
  python3 fchk.py auto 0x3936BD78     # 自动补上 Board 时钟等
"""
import ctypes, os, re, signal, subprocess, sys, time
sys.path.insert(0, "/home/deck")
import numpy as np
from reader_mem import _IOV, _libc, find_pid, GAPP_ADDR, OFF_BOARD

W, H = 1280, 800
DT = {"i4": "<i4", "u4": "<u4", "f4": "<f4", "f8": "<f8", "i2": "<i2"}


def rd(pid, addr, size):
    buf = ctypes.create_string_buffer(size)
    lo = _IOV(ctypes.cast(buf, ctypes.c_void_p), size)
    r = _IOV(ctypes.c_void_p(addr), size)
    n = _libc.process_vm_readv(pid, ctypes.byref(lo), 1, ctypes.byref(r), 1, 0)
    return buf.raw[:n] if n == size else None


def val(pid, addr, kind):
    dt = DT[kind]
    step = 8 if dt == "<f8" else (2 if dt == "<i2" else 4)
    d = rd(pid, addr, step)
    if not d or len(d) != step:
        return None
    return float(np.frombuffer(d, dt)[0])


def crop(path):
    subprocess.run(
        ["timeout", "20", "gst-launch-1.0", "-q", "pipewiresrc", "path=93",
         "num-buffers=1", "!", "videoconvert", "!", "videocrop",
         "left=980", "right=%d" % (W - 1170), "top=5", "bottom=%d" % (H - 100),
         "!", "videoscale", "!", "video/x-raw,width=1140", "!",
         "pngenc", "!", "filesink", "location=" + path], capture_output=True)


def main():
    pairs = []
    args = sys.argv[1:]
    for i in range(0, len(args) - 1, 2):
        try:
            a = int(args[i], 16)
        except ValueError:
            continue
        pairs.append((a, args[i + 1]))
    pid = find_pid()
    if pid is None:
        print("  ❌ 游戏没在跑")
        return
    # Board 时钟
    g = int(np.frombuffer(rd(pid, GAPP_ADDR, 4), "<u4")[0])
    b = int(np.frombuffer(rd(pid, g + OFF_BOARD, 4), "<u4")[0]) if g else 0
    if b:
        pairs = [(b + 0x38, "i4"), (b + 0xC84, "i4")] + pairs

    os.kill(pid, signal.SIGSTOP)
    t0 = time.perf_counter()
    try:
        crop("/tmp/tlock/sync.png")
        tf = time.perf_counter()
        print("冻结中（帧已抓 %.2fs），内存读数：" % (tf - t0))
        for a, k in pairs:
            v = val(pid, a, k)
            print("   0x%-10X [%s] = %s" % (a, k, ("%.4f" % v) if v is not None else "读取失败"))
        tm = time.perf_counter()
        print("  内存读完 %.2fs" % (tm - t0))
    finally:
        os.kill(pid, signal.SIGCONT)
    print("已解冻。帧：/tmp/tlock/sync.png")


if __name__ == "__main__":
    main()
