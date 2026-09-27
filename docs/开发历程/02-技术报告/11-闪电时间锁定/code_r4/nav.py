#!/usr/bin/env python3
"""nav.py —— 带校验的导航：标题页 → 闪电局。

每一步点完抓帧，由**调用方（模型）看帧确认**，避免盲点。
子命令：
  python3 nav.py title        # 点标题页「开始」
  python3 nav.py tree         # 点模式树「闪电」
  python3 nav.py menu         # 点游戏内「菜单」（暂停）
  python3 nav.py back         # 点选项面板「返回」
  python3 nav.py again        # 点结算页「再玩一次」
  python3 nav.py shot [name]  # 只抓帧
  python3 nav.py click X Y [name]
"""
import os, subprocess, sys, time

W, H = 1280, 800
OUT = "/tmp/tlock"
PTS = {"title": (640, 430), "tree": (300, 590), "menu": (215, 730),
       "back": (889, 598), "again": (628, 739), "mainmenu": (890, 598),
       "hint": (252, 633), "reset": (348, 726)}


def shot(name="nav"):
    p = "%s/%s.png" % (OUT, name)
    subprocess.run(["timeout", "20", "gst-launch-1.0", "-q", "pipewiresrc",
                    "path=93", "num-buffers=1", "!", "videoconvert", "!",
                    "pngenc", "!", "filesink", "location=" + p],
                   capture_output=True)
    print("saved", p)


def click(x, y):
    sys.path.insert(0, "/home/deck")
    from vmouse2 import VMouse2
    m = VMouse2()
    m.click(x, y)
    m.close()


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return
    cmd = sys.argv[1]
    if cmd == "shot":
        shot(sys.argv[2] if len(sys.argv) > 2 else "nav")
        return
    if cmd == "click":
        x, y = int(sys.argv[2]), int(sys.argv[3])
        name = sys.argv[4] if len(sys.argv) > 4 else "click_%d_%d" % (x, y)
        click(x, y)
        time.sleep(2.0)
        shot(name)
        return
    if cmd not in PTS:
        print("未知目标", cmd)
        return
    x, y = PTS[cmd]
    wait = float(sys.argv[2]) if len(sys.argv) > 2 and sys.argv[2].replace(".", "").isdigit() else 2.5
    print("点 %s (%d,%d)" % (cmd, x, y), flush=True)
    click(x, y)
    time.sleep(wait)
    shot(cmd)


if __name__ == "__main__":
    main()
