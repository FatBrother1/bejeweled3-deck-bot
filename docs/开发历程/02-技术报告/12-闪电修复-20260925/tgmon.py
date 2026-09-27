#!/usr/bin/env python3
"""被动时间宝石监测：每 0.3s 读一次内存，记录宝石出现/消失时间线。"""
import sys, time, json
sys.path.insert(0, "/home/deck")
from reader_mem import _Proc, find_pid, GAPP_ADDR
DUR = float(sys.argv[1]) if len(sys.argv) > 1 else 90.0
pid = find_pid()
pr = _Proc(pid)
g = pr.u32(GAPP_ADDR)
events = []
seen = {}
t0 = time.time()
while time.time() - t0 < DUR:
    b = pr.u32(g + 0xBE8)
    if not b:
        time.sleep(0.3); continue
    tg = []
    for i in range(8):
        for j in range(8):
            piece = pr.u32(b + 0xF8 + 4*j + 32*i)
            if not piece: continue
            f = pr.i32(piece + 0x228)
            if f is not None and (f & 131072):
                tg.append((i, j, pr.i32(piece + 0x244)))
    key = tuple(sorted(tg))
    if key != seen.get("k"):
        events.append({"t": round(time.time()-t0, 1), "gems": tg})
        seen["k"] = key
    time.sleep(0.3)
json.dump(events, open("/home/deck/tgmon.json", "w"), ensure_ascii=False, indent=1)
print("事件 %d 次" % len(events))
for e in events[:20]:
    print(e)
