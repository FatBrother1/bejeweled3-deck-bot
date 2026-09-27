#!/usr/bin/env python3
"""倒计时框裁剪抓图 —— 输出放大 3 倍的小图，便于人/模型读数。

用法：
  python3 tcrop.py [输出png] [等待秒]
"""
import subprocess, sys, time

# 倒计时框实测坐标 x∈[1010,1155] y∈[10,90]。
# videocrop 语义：right/bottom = 从右/下边缘裁掉多少像素。
OUT = "/tmp/tlock/tcrop.png"
W, H = 1280, 800


def grab(path, x0=990, y0=0, x1=1180, y1=110, scale=4):
    subprocess.run(
        ["timeout", "20", "gst-launch-1.0", "-q", "pipewiresrc", "path=93",
         "num-buffers=1", "!", "videoconvert", "!",
         "videocrop", "left=%d" % x0, "right=%d" % (W - x1),
         "top=%d" % y0, "bottom=%d" % (H - y1), "!",
         "videoscale", "!", "video/x-raw,width=%d" % ((x1 - x0) * scale),
         "!", "pngenc", "!", "filesink", "location=" + path],
        capture_output=True)
    return path


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else OUT
    wait = float(sys.argv[2]) if len(sys.argv) > 2 else 0.0
    if wait:
        time.sleep(wait)
    grab(path)
    print("saved", path)


if __name__ == "__main__":
    main()
