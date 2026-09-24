#!/usr/bin/env python3
"""干净测量动画时长：设备常驻（避免 0.4s 创建开销）+ 纯像素差轮询。
   ★ 这给出目标的诚实上限。"""
import sys, time, os
sys.path.insert(0,"/home/deck")
import numpy as np
from cap2 import Cap
from reader_fast import FastReader
from vmouse2 import VMouse2
from vision_np import BOARD
import solver_pro

cap=Cap(); rd=FastReader(cap, downsample=4)
m=VMouse2()                      # ★ 常驻，只创建一次
def cxy(i,j): return (int(round(BOARD["x0"]+j*BOARD["pitch_x"])),
                      int(round(BOARD["y0"]+i*BOARD["pitch_y"])))

def anim_duration(mv):
    (i1,j1),(i2,j2)=mv
    # 预稳
    rd.wait_still_and_read(min_still_ms=250)
    # 基线帧
    base=None
    for _ in range(10):
        a,d=rd.frame_diff()
        if a is not None: base=a.copy(); break
    t0=time.perf_counter()
    m.drag(*cxy(i1,j1),*cxy(i2,j2))
    t_drag=time.perf_counter()
    # 开始轮询（记录每个时刻的差异）
    first_motion=None; last_motion=None; quiet_since=None; n=0
    while time.perf_counter()-t_drag < 4.0:
        a,d=rd.frame_diff(); n+=1
        if a is None or base is None: continue
        dd=float(np.abs(a.astype(np.int16)-base.astype(np.int16)).mean())
        t=time.perf_counter()-t_drag
        if dd>=2.0:
            if first_motion is None: first_motion=t
            last_motion=t; quiet_since=None
        elif last_motion is not None:
            if quiet_since is None: quiet_since=t
            if t-quiet_since>=0.20: break
    return {"drag_ms":(t_drag-t0)*1000,
            "first_motion_ms":first_motion*1000 if first_motion else None,
            "last_motion_ms":last_motion*1000 if last_motion else None,
            "end_ms":(time.perf_counter()-t_drag)*1000,"frames":n}

time.sleep(4)
print("=== 动画时长干净测量（设备常驻）===",flush=True)
res=[]
for k in range(6):
    g,bad,w,v=rd.wait_still_and_read(min_still_ms=250)
    if g is None: print("  #%d 读不到棋盘"%(k+1)); continue
    rk=solver_pro.rank_moves(g)
    if not rk: print("  #%d 无可走步"%(k+1)); continue
    t=rk[0]
    r=anim_duration((t[6],t[7]))
    r["mv"]="%s<->%s"%(t[6],t[7])
    res.append(r)
    print("  %s: 拖动%.0fms 首次运动%.0fms 末次运动%.0fms 结束%.0fms (%d帧)"%(
        r["mv"],r["drag_ms"],r["first_motion_ms"] or -1,
        r["last_motion_ms"] or -1,r["end_ms"],r["frames"]),flush=True)
m.close(); cap.stop()
if res:
    lm=[r["last_motion_ms"] for r in res if r["last_motion_ms"]]
    fm=[r["first_motion_ms"] for r in res if r["first_motion_ms"]]
    dm=[r["drag_ms"] for r in res]
    print("\n=== 汇总（%d 次）==="%len(res),flush=True)
    print("  拖动耗时      中位 %.0f ms"%np.median(dm),flush=True)
    if fm: print("  首次运动      中位 %.0f ms  ← 游戏响应延迟"%np.median(fm),flush=True)
    if lm: print("  末次运动      中位 %.0f ms  ← ★动画真实时长"%np.median(lm),flush=True)
    if lm and fm:
        print("  ★ 动画净时长 ≈ %.0f ms（末次-首次运动）"%(np.median(lm)-np.median(fm)),flush=True)
        print("  ★ 单步理论下限 ≈ 拖动%.0f + 动画%.0f = %.0f ms ⇒ 上限 %.2f 步/秒"%(
            np.median(dm),np.median(lm),np.median(dm)+np.median(lm),
            1000/(np.median(dm)+np.median(lm))),flush=True)
