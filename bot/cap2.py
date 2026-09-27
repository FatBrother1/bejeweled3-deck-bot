#!/usr/bin/env python3
"""稳健抓帧：PipeWire 优先，坏了自动回退 gamescopectl，节点回来了再切回去。

★ 2026-09-27（bot 变瞎那次，用户点名"修复啊"）：
  PipeWire 的视频节点会**整条消失**（实测 `pw-dump` 里一个 Video 节点都没有，
  `pw-cli info 93` 报 no global）。旧写法只在构造那一刻判一次，两个洞：
    ① 运行中坏掉时 `PwCapture.get()` 会一直返回**最后一帧**（不是 None）——
       画面冻住、bot 以为游戏暂停，回退永远不触发；
    ② 一旦退到 gamescopectl 就再也回不来，哪怕节点已经回来了。
  现在：运行中发现（err / 线程退出 / 连续几次拿不到新帧）就切兜底；
  在兜底路径上每隔 RETRY 秒回试一次 PipeWire，回来了自动用回 90fps 那条路。
"""
import os, subprocess, time
import numpy as np
from PIL import Image

SHOT = "/home/deck/bjbot/cap2.png"


class Cap:
    RETRY = 60.0        # 在兜底路径上每隔多少秒回试一次 PipeWire
    STALL = 5           # 连续几次拿不到新帧就认定 PipeWire 卡死

    def __init__(self, log=None):
        self.log = log or (lambda m: None)
        self.pw = None
        self.ok_pw = False
        self.err = None
        self.last_retry = 0.0
        self.stall = 0
        self._try_pw()

    # ── PipeWire ───────────────────────────────────────────────
    def _try_pw(self, wait=8.0):
        try:
            from capture_pw import PwCapture
            c = PwCapture()
            if c.start(wait=wait):
                self.pw = c; self.ok_pw = True; self.err = None; self.stall = 0
                self.log("  抓帧: PipeWire 节点 %s 可用（90fps）" % c.path)
                return True
            self.err = "PipeWire 首帧失败(%s)" % c.err
            try: c.stop()
            except Exception: pass
        except Exception as e:
            self.err = "PipeWire 异常: %s" % e
        self.pw = None; self.ok_pw = False
        return False

    def _drop_pw(self, why):
        self.err = why
        self.log("  ⚠️ %s —— 改用 gamescopectl 兜底（约 2fps，慢但不断）" % why)
        try: self.pw.stop()
        except Exception: pass
        self.pw = None; self.ok_pw = False
        self.last_retry = time.time()

    # ── 对外接口（引擎只认 start/get/stop）─────────────────────
    @property
    def backend(self):
        return "PipeWire" if self.pw is not None else "gamescopectl"

    def start(self):
        """引擎启动检查：PipeWire 不行就确认兜底那条路真能出图。"""
        if self.pw is not None:
            return True
        self.log("  ⚠️ %s —— 改用 gamescopectl 兜底（约 2fps，慢但不断）"
                 % (self.err or "PipeWire 不可用"))
        return self.get(timeout=2.0) is not None

    def get(self, timeout=1.0):
        if self.pw is not None:
            s0 = self.pw.seq
            a = self.pw.get(timeout=timeout)
            if a is None:
                self._drop_pw("PipeWire 抓不到帧(%s)" % (self.pw.err or "空帧"))
            elif self.pw.err or not self.pw.running:
                self._drop_pw("PipeWire 断了(%s)" % (self.pw.err or "线程退出"))
            elif self.pw.seq == s0:
                # 整段 timeout 里一帧新的都没有 —— 流卡住了。
                # （画面静止不会这样：流是持续的，静止画面照样在出帧）
                self.stall += 1
                if self.stall >= self.STALL:
                    self._drop_pw("PipeWire 卡住（连续 %d 次没有新帧）" % self.stall)
                return a          # 这一帧还是先给出去，不浪费
            else:
                self.stall = 0
                return a
        # 走到这里说明在用兜底（或刚切过来）：到点就回试一次 PipeWire
        if self.pw is None and time.time() - self.last_retry >= self.RETRY:
            self.last_retry = time.time()
            if self._try_pw(wait=1.5):
                a = self.pw.get(timeout=timeout)
                if a is not None:
                    return a
        return self._shot()

    def _shot(self):
        """gamescopectl 兜底：一帧 PNG，约 450ms。"""
        p = SHOT
        for _ in range(2):
            if os.path.exists(p):
                try: os.remove(p)
                except OSError: pass
            subprocess.run(["gamescopectl", "screenshot", p], check=False)
            t0 = time.time()
            while time.time() - t0 < 4:
                if os.path.exists(p) and os.path.getsize(p) > 200000:
                    try:
                        im = Image.open(p); im.verify()
                        return np.asarray(Image.open(p).convert("RGB"))
                    except Exception: pass
                time.sleep(0.03)
        return None

    def stop(self):
        if self.pw: self.pw.stop()


if __name__ == "__main__":
    c = Cap(log=print); print("PipeWire 可用:", c.ok_pw)
    t0 = time.time(); n = 0
    while time.time() - t0 < 3:
        if c.get(timeout=0.3) is not None: n += 1
    print("3 秒取到 %d 帧，当前后端 %s" % (n, c.backend))
    c.stop()
