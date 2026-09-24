#!/usr/bin/env python3
"""Bejeweled 3 虚拟鼠标（v2）—— 实测 100% 成功率的确定性配置。

为什么不跟踪光标位置：实测"位置跟踪"假设在本环境不可靠（会出现拖拽静默失效），
而"每步撞角归零"是确定性的、代价可压到 0.02s，因此选后者。
参数由 exp_input.py 的对照实验选出（B 组：5/5 成功）。
"""
import time
import evdev
from evdev import UInput, ecodes as e


class VMouse2:
    def __init__(self, home_n=6, home_d=-1500, home_sleep=0.004,
                 steps=3, move_sleep=0.015, hold=0.05):
        cap = {e.EV_REL: [e.REL_X, e.REL_Y], e.EV_KEY: [e.BTN_LEFT]}
        self.ui = UInput(cap, name="dsh-vmouse", version=1)
        time.sleep(0.4)
        self.home_n = home_n; self.home_d = home_d; self.home_sleep = home_sleep
        self.steps = steps; self.move_sleep = move_sleep; self.hold = hold
        self.x = 0.0; self.y = 0.0

    def _rel(self, dx, dy):
        if dx: self.ui.write(e.EV_REL, e.REL_X, int(round(dx)))
        if dy: self.ui.write(e.EV_REL, e.REL_Y, int(round(dy)))
        self.ui.syn()

    def home(self):
        """撞左上角归零（确定性定位，代价 ~0.02s）。"""
        for _ in range(self.home_n):
            self._rel(self.home_d, self.home_d)
            time.sleep(self.home_sleep)
        self.x = 0.0; self.y = 0.0

    def move_from_home(self, x, y):
        self._rel(x, y)
        self.x, self.y = float(x), float(y)
        time.sleep(0.01)

    def click(self, x, y, hold=0.03):
        self.home(); self.move_from_home(x, y)
        self.ui.write(e.EV_KEY, e.BTN_LEFT, 1); self.ui.syn()
        time.sleep(hold)
        self.ui.write(e.EV_KEY, e.BTN_LEFT, 0); self.ui.syn()

    def drag(self, x1, y1, x2, y2):
        self.home()
        self.move_from_home(x1, y1)
        self.ui.write(e.EV_KEY, e.BTN_LEFT, 1); self.ui.syn()
        time.sleep(self.hold)
        for k in range(1, self.steps + 1):
            nx = x1 + (x2 - x1) * k / self.steps
            ny = y1 + (y2 - y1) * k / self.steps
            self._rel(nx - self.x, ny - self.y)
            self.x, self.y = nx, ny
            time.sleep(self.move_sleep)
        time.sleep(self.hold)
        self.ui.write(e.EV_KEY, e.BTN_LEFT, 0); self.ui.syn()

    def close(self):
        try: self.ui.close()
        except Exception: pass
