#!/usr/bin/env python3
"""live.py —— 运行态验证「显示秒 = 常数 − 游戏时钟」并测试锁时间。

用法：
  python3 live.py rel [秒]       # 运行中采样 cs 与 0x109CBEC，验证关系
  python3 live.py lock [秒]      # 钉住 Board+0x38，看画面倒计时是否冻住（锁时间）
"""
import sys, time
sys.path.insert(0, "/home/deck")
import numpy as np
from reader_mem import _IOV, _libc, find_pid, GAPP_ADDR, OFF_BOARD
import tb

SHOW = 0x109CBEC


def rv(pid, a):
    d = tb.rd(pid, a, 4)
    return int(np.frombuffer(d, "<i4")[0]) if d and len(d) == 4 else None


def start_round(pid):
    """若不在运行中的对局，点「再玩一次」重开。"""
    st = tb.is_paused(pid)
    b, cs, s = tb.clock(pid)
    print("起始：Board=%s cs=%s 状态=%s" % (hex(b) if b else None, cs,
                                        "暂停" if st else ("运行" if st is False else "未知")))
    if b is None or cs is None:
        print("→ 不在局中，点「再玩一次」")
        tb.click(tb.AGAIN)
        time.sleep(2.5)
    elif st is True:
        print("→ 处于暂停，点「返回」恢复")
        tb.ensure_running(pid)


def do_rel(sec):
    pid = find_pid()
    start_round(pid)
    print(" t     cs      s     show   show+cs/100")
    t0 = time.time()
    vals = []
    while time.time() - t0 < sec:
        _, c, ss = tb.clock(pid)
        sh = rv(pid, SHOW)
        if c is not None and sh is not None:
            v = sh + c / 100.0
            vals.append(v)
            print("%5.1f  %-7s %-5s %-6s %.2f" % (time.time() - t0, c, ss, sh, v))
        time.sleep(0.7)
    if vals:
        print("\nshow+cs/100: min=%.2f max=%.2f 极差=%.2f"
              % (min(vals), max(vals), max(vals) - min(vals)))
        print("→ %s" % ("★ 恒定：显示秒由游戏时钟推导（锁 cs 即锁时间）"
                        if max(vals) - min(vals) < 1.6 else
                        "不恒定：两者不同源"))
    tb.shot("/home/deck/tb/live_rel.png")


def do_lock(sec):
    pid = find_pid()
    start_round(pid)
    b, cs, s = tb.clock(pid)
    if not b:
        print("不在局中")
        return
    addr = b + 0x38
    print("基线 cs=%s show=%s" % (cs, rv(pid, SHOW)))
    tb.shot("/home/deck/tb/lock_before.png")
    hold = cs                      # 冻在当前时刻
    print("★ 钉住 Board+0x38 = %d（保持当前时刻），持续 %.0f 秒" % (hold, sec))
    t0 = time.time()
    n = 0
    marks = [1.0, 2.5, 5.0, 8.0, 12.0, 16.0, 20.0]
    mi = 0
    while time.time() - t0 < sec:
        el = time.time() - t0
        if mi < len(marks) and el >= marks[mi]:
            _, c, ss = tb.clock(pid)
            print("   t=%5.1fs  cs=%-8s s=%-5s show=%s" % (el, c, ss, rv(pid, SHOW)))
            tb.shot("/home/deck/tb/lock_%d.png" % int(marks[mi]))
            mi += 1
        tb.wv(pid, addr, "<i4", hold)
        n += 1
        time.sleep(0.008)
    _, c, ss = tb.clock(pid)
    print("   写 %d 次；结束 cs=%s show=%s" % (n, c, rv(pid, SHOW)))
    tb.shot("/home/deck/tb/lock_end.png")


if __name__ == "__main__":
    c = sys.argv[1] if len(sys.argv) > 1 else "rel"
    n = float(sys.argv[2]) if len(sys.argv) > 2 else (12.0 if c == "rel" else 20.0)
    (do_rel if c == "rel" else do_lock)(n)
