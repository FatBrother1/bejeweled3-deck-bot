#!/usr/bin/env python3
"""精确剖析单步耗时：把一步拆成各阶段计时，找出真正的时间去哪了。
   这直接检验目标的前提"动画占96.7%"是否还成立（Phase1 实测动画只有1.05s）。"""
import sys, time, os, ctypes, struct
import numpy as np
sys.path.insert(0,"/home/deck")
from cap2 import Cap
from vision_np2 import read_grid_np, is_board_like, fingerprint, BOARD
from solver_pro import rank_moves
from vmouse2 import VMouse2

BX0=int(BOARD["x0"])-44; BX1=int(BOARD["x0"]+7*BOARD["pitch_x"])+44
BY0=int(BOARD["y0"])-44; BY1=int(BOARD["y0"]+7*BOARD["pitch_y"])+44

cap=Cap()
def grab():
    for _ in range(12):
        a=cap.get(timeout=0.8)
        if a is not None: return a
    return None

# 阶段计时累加器
T={"grab":0.0,"pxl":0.0,"vision":0.0,"quiet_wait":0.0,"solve":0.0,
   "drag":0.0,"post_wait":0.0,"other":0.0}
C={"grab":0,"vision":0,"quiet_frames":0}

def cxy(i,j): return (int(round(BOARD["x0"]+j*BOARD["pitch_x"])),
                      int(round(BOARD["y0"]+i*BOARD["pitch_y"])))

def wait_quiet(thr=2.0,need=4,mw=4.0):
    """等静止，同时统计各阶段耗时"""
    t0=time.time(); q=0; last=None; best=1<<30; prev=None
    while time.time()-t0<mw:
        t1=time.perf_counter(); a=grab(); t2=time.perf_counter()
        T["grab"]+=t2-t1; C["grab"]+=1
        if a is None: continue
        t3=time.perf_counter(); reg=a[BY0:BY1,BX0:BX1].astype(np.int16); t4=time.perf_counter()
        T["pxl"]+=t4-t3
        d=float(np.abs(reg-prev).mean()) if (prev is not None and prev.shape==reg.shape) else 99
        prev=reg
        C["quiet_frames"]+=1
        q=q+1 if d<thr else 0
        t5=time.perf_counter(); g,conf=read_grid_np(a); t6=time.perf_counter()
        T["vision"]+=t6-t5; C["vision"]+=1
        ok,bad=is_board_like(conf); best=min(best,bad)
        last=(g if ok else None)
        if q>=need and last is not None:
            T["quiet_wait"]+=time.time()-t0
            return last,0,d
    T["quiet_wait"]+=time.time()-t0
    return None,(99 if best==(1<<30) else best),None

m=VMouse2()
print("=== 单步耗时剖析（10 步）===",flush=True)
print("%-4s %8s %8s %8s %8s %8s %8s %8s"%("步","抓帧","视觉","等静","求解","拖动","后等","总"),flush=True)
rows=[]
for k in range(10):
    for key in T: T[key]=0.0
    for key in C: C[key]=0
    t_all0=time.time()
    g,bad,dd=wait_quiet()
    if g is None:
        print("  #%d 读不到棋盘(bad=%s)"%(k+1,bad),flush=True); continue
    t1=time.perf_counter(); rk=rank_moves(g); t2=time.perf_counter()
    T["solve"]+=t2-t1
    if not rk: print("  #%d 无可走步"% (k+1),flush=True); continue
    t=rk[0]; (i1,j1),(i2,j2)=t[6],t[7]
    t3=time.perf_counter()
    m.drag(*cxy(i1,j1),*cxy(i2,j2))
    t4=time.perf_counter(); T["drag"]+=t4-t3
    t5=time.perf_counter(); g2,bad2,_=wait_quiet(); t6=time.perf_counter()
    T["post_wait"]+=t6-t5
    el=time.time()-t_all0
    print("%-4d %7.0fms %7.0fms %7.0fms %7.0fms %7.0fms %7.0fms %7.0fms"%(
        k+1,T["grab"]*1000,T["vision"]*1000,T["quiet_wait"]*1000,T["solve"]*1000,
        T["drag"]*1000,T["post_wait"]*1000,el*1000),flush=True)
    rows.append(dict(T))
m.close(); cap.stop()

print("\n=== 平均（%d 步）==="%len(rows),flush=True)
keys=["grab","vision","quiet_wait","solve","drag","post_wait"]
avg={k:sum(r[k] for r in rows)/len(rows) for k in keys}
tot=sum(avg.values())
print("%-12s %10s %8s"%("阶段","平均ms","占比"),flush=True)
for k in keys:
    print("%-12s %10.1f %7.1f%%"%(k,avg[k]*1000,avg[k]/tot*100),flush=True)
print("%-12s %10.1f"%("合计",tot*1000),flush=True)
print("\n注: '等静'与'后等'是等待游戏动画的时间（含抓帧轮询）",flush=True)
print("    '抓帧'是 PipeWire 取帧本身的耗时",flush=True)
print("    '视觉'是 read_grid_np 识别耗时",flush=True)
