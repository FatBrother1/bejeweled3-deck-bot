#!/usr/bin/env python3
"""点击 + 抓帧 helper。
  python3 ui.py click X Y [等待秒] [输出png]
  python3 ui.py shot [输出png]
  python3 ui.py key <键名>
"""
import subprocess, sys, time, os

OUT = "/tmp/tlock"


def shot(path):
    subprocess.run(
        ["timeout", "20", "gst-launch-1.0", "-q", "pipewiresrc", "path=93",
         "num-buffers=1", "!", "videoconvert", "!", "pngenc", "!",
         "filesink", "location=" + path],
        capture_output=True)
    return path


def main():
    cmd = sys.argv[1]
    if cmd == "shot":
        p = sys.argv[2] if len(sys.argv) > 2 else OUT + "/shot.png"
        shot(p)
        print("saved", p)
    elif cmd == "click":
        x, y = int(sys.argv[2]), int(sys.argv[3])
        wait = float(sys.argv[4]) if len(sys.argv) > 4 else 2.5
        p = sys.argv[5] if len(sys.argv) > 5 else OUT + "/click_%d_%d.png" % (x, y)
        sys.path.insert(0, "/home/deck")
        from vmouse2 import VMouse2
        m = VMouse2()
        print("click (%d,%d)" % (x, y), flush=True)
        m.click(x, y)
        m.close()
        time.sleep(wait)
        shot(p)
        print("saved", p)
    elif cmd == "key":
        k = sys.argv[2]
        subprocess.run(["xdotool", "key", k],
                       env={**os.environ, "DISPLAY": ":0"}, capture_output=True)
        print("key", k)


if __name__ == "__main__":
    main()
