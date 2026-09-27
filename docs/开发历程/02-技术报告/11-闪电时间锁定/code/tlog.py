#!/usr/bin/env python3
"""连续记录全部候选值 120 秒（0.25s 间隔），供与用户报数交叉定位。"""
import ctypes, sys, time, json
import numpy as np
sys.path.insert(0, "/home/deck")
from reader_mem import _IOV, _libc, find_pid, GAPP_ADDR

def raw_read(pid, addr, size):
    buf = ctypes.create_string_buffer(size)
    local = _IOV(ctypes.cast(buf, ctypes.c_void_p), size)
    remote = _IOV(ctypes.c_void_p(addr), size)
    n = _libc.process_vm_readv(pid, ctypes.byref(local), 1, ctypes.byref(remote), 1, 0)
    return buf.raw[:n] if n == size else None

def rd(pid, addr, dt, step):
    raw = raw_read(pid, addr, step)
    return round(float(np.frombuffer(raw, dtype=dt)[0]), 3) if raw else None

pid = find_pid()
STATIC = [("A057EA4", 0xA057EA4, "<f4", 4), ("3F497E04", 0x3F497E04, "<f4", 4),
          ("3F49F95C", 0x3F49F95C, "<f4", 4), ("3F497D68", 0x3F497D68, "<f8", 8),
          ("3F498308", 0x3F498308, "<f8", 8), ("2ACC1D60", 0x2ACC1D60, "<f8", 8),
          ("F6F6F00", 0xF6F6F00, "<i4", 4)]
t0 = time.time()
out = open("/home/deck/tlog.jsonl", "w")
print("LOGGING_START", flush=True)
while time.time() - t0 < 120:
    g_raw = rd(pid, GAPP_ADDR, "<u4", 4)
    g = int(g_raw) if g_raw else None
    rec = {"t": round(time.time() - t0, 2)}
    if g:
        b_raw = rd(pid, g + 0xBE8, "<u4", 4)
        b = int(b_raw) if b_raw else None
        if b:
            rec["clk_s"] = rd(pid, b + 0xC84, "<i4", 4)
            rec["clk_cs"] = rd(pid, b + 0x38, "<i4", 4)
            rec["E38"] = rd(pid, b + 0xE38, "<i4", 4)
            rec["E3C"] = rd(pid, b + 0xE3C, "<i4", 4)
            rec["g680"] = rd(pid, g + 0x680, "<i4", 4)
            rec["g6F4"] = rd(pid, g + 0x6F4, "<i4", 4)
            rec["g6F8"] = rd(pid, g + 0x6F8, "<i4", 4)
    for name, addr, dt, step in STATIC:
        rec[name] = rd(pid, addr, dt, step)
    out.write(json.dumps(rec) + "\n")
    out.flush()
    time.sleep(0.25)
out.close()
print("LOGGING_DONE", flush=True)
