#!/usr/bin/env python3
"""暂停态 dump 渲染属性结构体邻域，找所有 = N 的表示。"""
import ctypes, sys, time
import numpy as np
sys.path.insert(0, "/home/deck")
from reader_mem import _IOV, _libc, find_pid

def raw_read(pid, addr, size):
    buf = ctypes.create_string_buffer(size)
    local = _IOV(ctypes.cast(buf, ctypes.c_void_p), size)
    remote = _IOV(ctypes.c_void_p(addr), size)
    n = _libc.process_vm_readv(pid, ctypes.byref(local), 1, ctypes.byref(remote), 1, 0)
    return buf.raw[:n] if n == size else None

pid = find_pid()
N = int(sys.argv[1])
BASE = 0x1098000
SIZE = 0x10000      # 64KB 窗口 0x1098000-0x10A8000
raw = raw_read(pid, BASE, SIZE)
print("窗口 0x%X..0x%X  N=%d" % (BASE, BASE+SIZE, N))
i4 = np.frombuffer(raw, "<i4")
f4 = np.frombuffer(raw, "<f4")
f8 = np.frombuffer(raw[:len(raw)//8*8], "<f8")
hits = []
# 浮点秒制 [N, N+1)
for i in np.nonzero((f4 >= N) & (f4 < N+1) & np.isfinite(f4))[0]:
    hits.append((BASE + i*4, "f4", float(f4[i])))
# i4 == N
for i in np.nonzero(i4 == N)[0]:
    hits.append((BASE + i*4, "i4", float(i4[i])))
# 十分秒 [N*10, (N+1)*10)
for i in np.nonzero((f4 >= N*10) & (f4 < (N+1)*10) & np.isfinite(f4))[0]:
    hits.append((BASE + i*4, "f4t", float(f4[i])))
for a, k, v in hits:
    print("  0x%-9X [%s] %.4f  (窗口+%#x)" % (a, k, v, a-BASE))
print("共 %d 个" % len(hits))
