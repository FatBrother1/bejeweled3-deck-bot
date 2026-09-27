#!/usr/bin/env python3
"""跳变测试：依次对 3 个候选写 +5，每次间隔 8 秒。用户肉眼判定哪次生效。"""
import ctypes, sys, time
import numpy as np
sys.path.insert(0, "/home/deck")
from reader_mem import _IOV, _libc, find_pid
_libc.process_vm_writev.restype = ctypes.c_ssize_t
WBUF = ctypes.create_string_buffer(8)
DT = {"f4": ("<f4", 4), "f8": ("<f8", 8), "ms": ("<i4", 4)}

def raw_read(pid, addr, size):
    buf = ctypes.create_string_buffer(size)
    local = _IOV(ctypes.cast(buf, ctypes.c_void_p), size)
    remote = _IOV(ctypes.c_void_p(addr), size)
    n = _libc.process_vm_readv(pid, ctypes.byref(local), 1, ctypes.byref(remote), 1, 0)
    return buf.raw[:n] if n == size else None

def raw_write(pid, addr, data):
    WBUF.raw = data
    local = _IOV(ctypes.cast(WBUF, ctypes.c_void_p), len(data))
    remote = _IOV(ctypes.c_void_p(addr), len(data))
    return _libc.process_vm_writev(pid, ctypes.byref(local), 1, ctypes.byref(remote), 1, 0)

def read_val(pid, addr, kind):
    dt, step = DT[kind]
    raw = raw_read(pid, addr, step)
    return float(np.frombuffer(raw, dtype=dt)[0]) if raw else None

pid = find_pid()
CANDS = [(0x3F497E04, "f4"), (0x3F49F95C, "f4"), (0x3F497D68, "f8")]
for i, (addr, kind) in enumerate(CANDS):
    v0 = read_val(pid, addr, kind)
    if v0 is None:
        print("第%d次目标 0x%X 读不到" % (i+1, addr), flush=True); continue
    dt, _ = DT[kind]
    payload = np.array(v0 + 5.0, dtype=dt).tobytes()
    t_mark = time.time()
    n = raw_write(pid, addr, payload)
    time.sleep(0.5)
    v1 = read_val(pid, addr, kind)
    time.sleep(1.5)
    v2 = read_val(pid, addr, kind)
    print("第%d次轻推 0x%X [%s]: %.2f → 写+5 → %.2f → 2秒后 %.2f  (写入%d字节)"
          % (i+1, addr, kind, v0, v1, v2, n), flush=True)
    if i < 2:
        time.sleep(6.5)
print("完成——三次轻推分别在 %.0f / %.0f / %.0f 秒时刻"
      % (0, 8, 16), flush=True)
