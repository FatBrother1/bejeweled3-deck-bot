#!/usr/bin/env python3
"""快速 Reader v3：解耦静止判定与识别 + 运动感知 + 可切换识别后端。

★★ 三个实测根因 ★★
  ① 原版在**每帧**上调 read_grid_np（50ms/次），一帧等待处理 40+ 帧
     ⇒ 视觉累计 **2147 ms/步**（占单步 85%），**与游戏动画无关**，纯自己的开销。
  ② 解耦后"连续4帧静止"只要 40ms ⇒ **短于动画启动延迟** ⇒ 动画前读到画面
     ⇒ 指纹假变化 ⇒ bot 以为成功（实测同一招重复 12 次、得分 0）。
  ③ 超立方体启发式检测**过检**：把紫火焰(sat 0.47)误判为超立方体
     ⇒ solver 反复走"任意交换引爆"⇒ 全是无效交换 ⇒ 得分 0。
     ⇒ 因此默认使用**原始 vision（颜色投票）**，S 检测作为可选开关且阈值更严。

★ 设计：vision 后端可切换（参数 backends=("vision_np","vision_np2")）
"""
import time
import numpy as np
import sys
sys.path.insert(0, "/home/deck")
from vision_np import BOARD

# 可切换的识别后端
_BACKENDS = {}
def _load(name):
    if name in _BACKENDS: return _BACKENDS[name]
    if name == "vision_np":
        import vision_np as m
    else:
        import vision_np2 as m
    _BACKENDS[name] = m
    return m

BX0 = int(BOARD["x0"]) - 44; BX1 = int(BOARD["x0"] + 7 * BOARD["pitch_x"]) + 44
BY0 = int(BOARD["y0"]) - 44; BY1 = int(BOARD["y0"] + 7 * BOARD["pitch_y"]) + 44

class FastReader:
    def __init__(self, cap, downsample=4, backend="vision_np"):
        self.cap = cap
        self.prev = None
        self.ds = downsample
        self.backend = backend
        self.mod = _load(backend)
        self.stats = {"frames": 0, "grabs": 0, "visions": 0,
                      "t_grab": 0.0, "t_diff": 0.0, "t_vision": 0.0,
                      "waits": 0, "t_wait": 0.0}

    def _region(self, a):
        return a[BY0:BY1:self.ds, BX0:BX1:self.ds].astype(np.int16)

    def frame_diff(self):
        t0 = time.perf_counter()
        a = self.cap.get(timeout=0.5)
        self.stats["t_grab"] += time.perf_counter() - t0
        self.stats["grabs"] += 1
        if a is None: return None, None
        t1 = time.perf_counter()
        r = self._region(a)
        d = None
        if self.prev is not None and self.prev.shape == r.shape:
            d = float(np.abs(r - self.prev).mean())
        self.prev = r
        self.stats["t_diff"] += time.perf_counter() - t1
        self.stats["frames"] += 1
        return a, d

    def recognize(self, a):
        t0 = time.perf_counter()
        g, conf = self.mod.read_grid_np(a)
        self.stats["t_vision"] += time.perf_counter() - t0
        self.stats["visions"] += 1
        ok, bad = self.mod.is_board_like(conf)
        return (g if ok else None), bad

    def wait_still_and_read(self, thr=2.0, need=4, max_wait=4.0, min_still_ms=120,
                            require_motion=False, motion_timeout=1.2):
        """等静止 → 只识别一次。返回 (grid|None, bad, ms_waited, ms_vision)"""
        t0 = time.time(); q = 0; last_frame = None
        quiet_since = None; motion = False
        while time.time() - t0 < max_wait:
            a, d = self.frame_diff()
            if a is None: continue
            last_frame = a
            moving = (d is not None and d >= thr)
            if moving:
                motion = True; q = 0; quiet_since = None
            else:
                q += 1
                if quiet_since is None: quiet_since = time.time()
            still_ok = (q >= need and quiet_since is not None
                        and (time.time() - quiet_since) * 1000 >= min_still_ms)
            if require_motion:
                if motion and still_ok: break
                if (not motion) and (time.time() - t0) > motion_timeout: break
            else:
                if still_ok: break
        waited = (time.time() - t0) * 1000
        self.stats["waits"] += 1; self.stats["t_wait"] += waited
        if last_frame is None:
            return None, 99, waited, 0.0
        tv = time.perf_counter()
        g, bad = self.recognize(last_frame)
        vms = (time.perf_counter() - tv) * 1000
        return g, bad, waited, vms

    def read_now(self):
        """立即抓帧并识别（不等静止）——固定等待模式用。"""
        a = self.cap.get(timeout=0.5)
        if a is None: return None, 99
        return self.recognize(a)
