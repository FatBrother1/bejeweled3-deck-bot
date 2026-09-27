#!/usr/bin/env python3
"""relation.py —— 验证「倒计时 = 常数 − 游戏时钟」并测试锁定。

三个实验：
  ① 同时采样 Board+0x38(cs)、0x109CBEC(显示秒)、Board+0xC84(s)，
     看 显示 + cs/100 是否恒等于一个常数。
  ② 若①成立 → 锁定测试：把 Board+0x38 钉在低位，看 0x109CBEC 是否跟着冻住。
  ③ 对比：钉住 0x109CBEC，看 Board+0x38 是否照走（预期照走）。

用法：
  python3 relation.py rel [秒数]      # 实验①
  python3 relation.py pinclock [秒]   # 实验②
  python3 relation.py pinshow [秒]    # 实验③
"""
import sys, time
sys.path.insert(0, "/home/deck")
import numpy as np
from reader_mem import _IOV, _libc, find_pid, GAPP_ADDR, OFF_BOARD
import tb

SHOW = 0x109CBEC


def rv(pid, addr):
    d = tb.rd(pid, addr, 4)
    return int(np.frombuffer(d, "<i4")[0]) if d and len(d) == 4 else None


def do_rel(sec):
    pid = find_pid()
    b, cs, s = tb.clock(pid)
    if not b:
        print("不在局中")
        return
    print("Board=0x%X  cs_off=0x38  show=0x%X" % (b, SHOW))
    print("   t     Board+0x38(cs)  Board+0xC84(s)  show(0x109CBEC)   show+cs/100")
    t0 = time.time()
    tot = []
    while time.time() - t0 < sec:
        _, c, ss = tb.clock(pid)
        sh = rv(pid, SHOW)
        if c is not None and sh is not None:
            tot.append(sh + c / 100.0)
            print("  %5.2f   %10s   %10s   %10s   %12.2f"
                  % (time.time() - t0, c, ss, sh, sh + c / 100.0))
        time.sleep(0.5)
    if tot:
        import statistics
        print("\n  show+cs/100 统计：min=%.2f max=%.2f 均值=%.2f 标准差=%.3f"
              % (min(tot), max(tot), statistics.mean(tot),
                 statistics.pstdev(tot) if len(tot) > 1 else 0))
        print("  → %s" % ("★ 恒定！倒计时由游戏时钟推导" if max(tot) - min(tot) < 2.0
                          else "不恒定（两者不同源）"))


def do_pinclock(sec):
    pid = find_pid()
    b, cs, s = tb.clock(pid)
    if not b:
        print("不在局中")
        return
    addr = b + 0x38
    print("① 记录基线：cs=%s show=%s" % (cs, rv(pid, SHOW)))
    tb.shot("/home/deck/tb/rel_before.png")
    target = 100          # 钉在 1.00 秒（低位）
    print("② 钉住 Board+0x38 = %d（=%.2f 秒）保持 %.0f 秒，高频写…" % (target, target / 100.0, sec))
    t0 = time.time()
    n = 0
    marks = [1.0, 3.0, 6.0, 10.0, 15.0]
    mi = 0
    while time.time() - t0 < sec:
        el = time.time() - t0
        if mi < len(marks) and el >= marks[mi]:
            _, c, ss = tb.clock(pid)
            sh = rv(pid, SHOW)
            print("   t=%5.1fs  Board+0x38=%-8s show=%-6s" % (el, c, sh))
            tb.shot("/home/deck/tb/rel_pin_%d.png" % int(marks[mi]))
            mi += 1
        tb.wv(pid, addr, "<i4", target)
        n += 1
        time.sleep(0.01)
    print("   写 %d 次；结束 cs=%s show=%s" % (n, tb.clock(pid)[1], rv(pid, SHOW)))
    tb.shot("/home/deck/tb/rel_end.png")


def do_pinshow(sec):
    pid = find_pid()
    _, cs, s = tb.clock(pid)
    sh = rv(pid, SHOW)
    print("① 基线：cs=%s show=%s" % (cs, sh))
    target = 300
    print("② 钉住 0x%X = %d，保持 %.0f 秒" % (SHOW, target, sec))
    t0 = time.time()
    n = 0
    marks = [1.0, 3.0, 6.0, 10.0]
    mi = 0
    while time.time() - t0 < sec:
        el = time.time() - t0
        if mi < len(marks) and el >= marks[mi]:
            _, c, ss = tb.clock(pid)
            print("   t=%5.1fs  cs=%-8s show=%s" % (el, c, rv(pid, SHOW)))
            tb.shot("/home/deck/tb/rel_show_%d.png" % int(marks[mi]))
            mi += 1
        tb.wv(pid, SHOW, "<i4", target)
        n += 1
        time.sleep(0.01)
    print("   写 %d 次；结束 cs=%s show=%s" % (n, tb.clock(pid)[1], rv(pid, SHOW)))


if __name__ == "__main__":
    c = sys.argv[1] if len(sys.argv) > 1 else "rel"
    n = float(sys.argv[2]) if len(sys.argv) > 2 else (12.0 if c == "rel" else 15.0)
    if c == "rel":
        do_rel(n)
    elif c == "pinclock":
        do_pinclock(n)
    elif c == "pinshow":
        do_pinshow(n)
