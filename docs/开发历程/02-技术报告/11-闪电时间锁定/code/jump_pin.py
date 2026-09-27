#!/usr/bin/env python3
"""跳变+冻结二连：对指定地址写 +DELTA，等 1.5s 后连续写回钉住 HOLD 秒。"""
import ctypes, sys, time
import numpy as np
sys.path.insert(0, "/home/deck")
from reader_mem import _IOV, _libc, find_pid
_libc.process_vm_writev.restype = ctypes.c_ssize_t

DT = {"s": ("<i4", 4), "ms": ("<i4", 4), "f4": ("<f4", 4), "f8": ("<f8", 8),
      "f4t": ("<f4", 4), "f8t": ("<f8", 8), "f4m": ("<f4", 4)}
WBUF = ctypes.create_string_buffer(8)

def raw_write(pid, addr, data):
    WBUF.raw = data
    local = _IOV(ctypes.cast(WBUF, ctypes.c_void_p), len(data))
    remote = _IOV(ctypes.c_void_p(addr), len(data))
    return _libc.process_vm_writev(pid, ctypes.byref(local), 1, ctypes.byref(remote), 1, 0)

def read_val(pid, addr, kind):
    dt, step = DT[kind]
    buf = ctypes.create_string_buffer(step)
    local = _IOV(ctypes.cast(buf, ctypes.c_void_p), step)
    remote = _IOV(ctypes.c_void_p(addr), step)
    n = _libc.process_vm_readv(pid, ctypes.byref(local), 1, ctypes.byref(remote), 1, 0)
    return float(np.frombuffer(buf.raw[:step], dtype=dt)[0]) if n == step else None

addr = int(sys.argv[1], 16); kind = sys.argv[2]; delta = float(sys.argv[3]); hold = float(sys.argv[4])
delay = float(sys.argv[5]) if len(sys.argv) > 5 else 0.0
pid = find_pid()
dt, _ = DT[kind]
time.sleep(delay)
v0 = read_val(pid, addr, kind)
tgt = v0 + delta
print("0x%X [%s] 当前=%.3f → 写 %.3f（+%.1f）" % (addr, kind, v0, tgt, delta), flush=True)
raw_write(pid, addr, np.array(tgt, dtype=dt).tobytes())
time.sleep(1.5)
v1 = read_val(pid, addr, kind)
print("1.5秒后回读 = %.3f %s" % (v1, "(写入被保持)" if abs(v1-tgt) < 0.5*abs(delta)+1 else "(已被游戏改写!)"), flush=True)
t0 = time.time(); n_ok = 0
payload = np.array(tgt, dtype=dt).tobytes()
while time.time() - t0 < hold:
    if raw_write(pid, addr, payload) == len(payload): n_ok += 1
    time.sleep(0.05)
vend = read_val(pid, addr, kind)
print("钉住 %.0f 秒（写 %d 次），结束时值 = %.3f" % (hold, n_ok, vend), flush=True)
