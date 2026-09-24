#!/usr/bin/env python3
"""通过 PipeWire 常驻抓帧（gamescope 视频节点）—— 90fps 原始 RGB，零注入。

实测（Steam Deck / GE-Proton10-32 / gamescope 3.16.23）：
  gamescopectl screenshot  : 2.2 fps (450ms/帧，PNG 编码瓶颈)
  pipewiresrc + fdsink     : 90 fps (11.1ms/帧，原始 RGB 3072000 字节)
"""
import os, subprocess, threading, time
import numpy as np

W, H, FRAME = 1280, 800, 1280 * 800 * 3
GST = ["gst-launch-1.0", "-q", "pipewiresrc", "path=93",
       "!", "videoconvert", "!", "video/x-raw,format=RGB",
       "!", "fdsink", "fd=1"]


class PwCapture:
    """后台线程持续读帧，只保留最新一帧（丢弃积压，保证低延迟）。"""

    def __init__(self, path=93, width=1280, height=800):
        self.w, self.h = width, height
        self.frame_bytes = width * height * 3
        self.path = path
        self.proc = None
        self.latest = None
        self.seq = 0
        self.running = False
        self.lock = threading.Lock()
        self.err = None

    def start(self):
        cmd = [c if c != "path=93" else "path=%d" % self.path for c in GST]
        self.proc = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                                     stderr=subprocess.DEVNULL,
                                     bufsize=self.frame_bytes)
        self.running = True
        self.t = threading.Thread(target=self._loop, daemon=True)
        self.t.start()
        # 等首帧
        t0 = time.time()
        while self.latest is None and time.time() - t0 < 8:
            time.sleep(0.02)
        return self.latest is not None

    def _loop(self):
        """读满整帧再交付。注意 fdsink 的 read 可能**短读**（一次读不满一帧），
        必须累积到 frame_bytes 才 reshape，否则会 ValueError（实测踩过）。"""
        fb = self.frame_bytes
        buf = bytearray()
        while self.running:
            try:
                chunk = self.proc.stdout.read(fb - len(buf))
            except Exception as e:
                self.err = str(e); break
            if not chunk:
                self.err = "eof"; break
            buf.extend(chunk)
            if len(buf) >= fb:
                arr = np.frombuffer(bytes(buf[:fb]), dtype=np.uint8)
                arr = arr.reshape(self.h, self.w, 3)
                with self.lock:
                    self.latest = arr
                    self.seq += 1
                del buf[:fb]

    def get(self, timeout=1.0):
        """拿最新一帧（numpy RGB）。"""
        t0 = time.time()
        with self.lock:
            s0 = self.seq
        while time.time() - t0 < timeout:
            with self.lock:
                if self.seq != s0 and self.latest is not None:
                    return self.latest.copy()
            time.sleep(0.001)
        with self.lock:
            return self.latest.copy() if self.latest is not None else None

    def stop(self):
        self.running = False
        try:
            if self.proc: self.proc.kill()
        except Exception:
            pass


if __name__ == "__main__":
    c = PwCapture()
    ok = c.start()
    print("start ok =", ok, "err =", c.err)
    if ok:
        t0 = time.time(); n = 0
        while time.time() - t0 < 3:
            f = c.get()
            n += 1
        print("3 秒取到 %d 帧 (%.1f fps)" % (n, n / 3))
        from PIL import Image
        Image.fromarray(c.get()).save("/home/deck/pwcap_test.png")
        print("saved /home/deck/pwcap_test.png")
    c.stop()
