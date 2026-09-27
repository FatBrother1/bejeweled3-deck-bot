#!/usr/bin/env python3
"""run.py —— 稳定进入「正在运行的闪电对局」并保持，供后续实验使用。

状态判据（修正 live.py 的误判）：
  · 结算页 / 标题页 / 模式树：Board 指针可能仍是残值，但 cs 停滞不动。
  · 真正的对局中：cs 每 0.5 秒至少 +40（厘秒）。
  所以判据 = 「cs 在两次采样间确实增长」，而不是「Board 非空」。

用法：
  python3 run.py enter [最长等待秒]   # 反复尝试进局，直到 cs 在增长
  python3 run.py check                # 只报告当前状态
"""
import sys, time
sys.path.insert(0, "/home/deck")
import numpy as np
from reader_mem import find_pid
import tb


def running_check(pid, gap=0.6):
    """返回 (是否真在跑, cs1, cs2)。"""
    _, c1, _ = tb.clock(pid)
    time.sleep(gap)
    _, c2, _ = tb.clock(pid)
    if c1 is None or c2 is None:
        return False, c1, c2
    return (c2 - c1) >= 20, c1, c2


def check():
    pid = find_pid()
    if pid is None:
        print("游戏未运行")
        return None
    b, cs, s = tb.clock(pid)
    ok, c1, c2 = running_check(pid)
    print("PID=%d Board=%s cs=%s→%s s=%s 真在对局中=%s"
          % (pid, hex(b) if b else None, c1, c2, s, ok))
    return ok


def enter(maxwait=60):
    pid = find_pid()
    if pid is None:
        print("❌ 游戏没在跑")
        return False
    ok = check()
    if ok:
        print("已在对局中")
        return True
    t0 = time.time()
    attempt = 0
    while time.time() - t0 < maxwait:
        attempt += 1
        ok, c1, c2 = running_check(pid, 0.5)
        if ok:
            print("✓ 已在运行中的对局（第 %d 次检查，cs %s→%s）" % (attempt, c1, c2))
            return True
        # 不在局中：按当前画面点一个安全按钮
        print("  [%d] 不在对局中，点「再玩一次」(628,739)…" % attempt)
        tb.click(tb.AGAIN)
        time.sleep(2.5)
        ok, c1, c2 = running_check(pid, 0.5)
        if ok:
            print("✓ 已进入对局（cs %s→%s）" % (c1, c2))
            return True
        # 可能停在标题页/模式树：走一遍标题→闪电
        print("     仍未进局，尝试 标题→闪电 路径…")
        tb.click(tb.TITLE_START)
        time.sleep(2.2)
        tb.click(tb.TREE_LIGHT)
        time.sleep(2.5)
        ok, c1, c2 = running_check(pid, 0.5)
        if ok:
            print("✓ 已进入对局（cs %s→%s）" % (c1, c2))
            return True
    print("❌ %.0f 秒内未能进入对局" % maxwait)
    return False


if __name__ == "__main__":
    c = sys.argv[1] if len(sys.argv) > 1 else "check"
    if c == "enter":
        enter(float(sys.argv[2]) if len(sys.argv) > 2 else 60)
    else:
        check()
