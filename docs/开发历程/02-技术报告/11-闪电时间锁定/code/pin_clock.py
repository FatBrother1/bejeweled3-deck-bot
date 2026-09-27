#!/usr/bin/env python3
"""钉住游戏时钟 Board+0x38（厘秒）：先 +500（时钟快5秒→倒计时少5秒），再钉 HOLD 秒。"""
import ctypes, sys, time
import numpy as np
sys.path.insert(0, "/home/deck")
from reader_mem import _IOV, _libc, find_pid, GAPP_ADDR
_libc.process_vm_writev.restype = ctypes.c_ssize_t
WBUF = ctypes.create_string_buffer(8)

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

def r_i32(pid, addr):
    raw = raw_read(pid, addr, 4)
    return int(np.frombuffer(raw, "<i4")[0]) if raw else None

pid = find_pid()
g = int(np.frombuffer(raw_read(pid, GAPP_ADDR, 4), "<u4")[0])
board = int(np.frombuffer(raw_read(pid, g + 0xBE8, 4), "<u4")[0])
addr = board + 0x38
delay = float(sys.argv[1]) if len(sys.argv) > 1 else 10.0
hold = float(sys.argv[2]) if len(sys.argv) > 2 else 25.0
print("Board=0x%X 时钟addr=0x%X，%.0f秒后开始" % (board, addr, delay), flush=True)
time.sleep(delay)
v0 = r_i32(pid, addr)
tgt = v0 + 500
print("时钟当前=%d cs → 写 %d（+500=快5秒）" % (v0, tgt), flush=True)
raw_write(pid, addr, np.array(tgt, dtype="<i4").tobytes())
time.sleep(1.5)
v1 = r_i32(pid, addr)
print("1.5秒后回读 = %d %s" % (v1, "被游戏改写" if abs(v1 - tgt) > 300 else "保持"), flush=True)
t0 = time.time(); n_ok = 0
payload = np.array(tgt, dtype="<i4").tobytes()
while time.time() - t0 < hold:
    if raw_write(pid, addr, payload) == len(payload): n_ok += 1
    time.sleep(0.05)
print("钉住 %.0f 秒（写 %d 次），结束值 = %d" % (hold, n_ok, r_i32(pid, addr)), flush=True)
