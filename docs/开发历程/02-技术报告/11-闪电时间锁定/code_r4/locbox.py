#!/usr/bin/env python3
"""locbox.py —— 程序化定位倒计时框（用 Deck 上的 numpy）。"""
import struct, sys, zlib
import numpy as np


def read_png(path):
    d = open(path, "rb").read()
    pos = 8
    idat = b""
    w = h = ct = None
    while pos < len(d):
        ln = struct.unpack(">I", d[pos:pos + 4])[0]
        typ = d[pos + 4:pos + 8]
        data = d[pos + 8:pos + 8 + ln]
        if typ == b"IHDR":
            w, h, bd, ct = struct.unpack(">IIBB", data[:10])
        elif typ == b"IDAT":
            idat += data
        pos += 12 + ln
    raw = zlib.decompress(idat)
    ch = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}[ct]
    stride = w * ch
    out = np.zeros((h, w, ch), np.uint8)
    prev = np.zeros(stride, np.int32)
    p = 0
    for y in range(h):
        f = raw[p]
        p += 1
        line = np.frombuffer(raw[p:p + stride], np.uint8).astype(np.int32).copy()
        p += stride
        if f == 1:
            for i in range(ch, stride):
                line[i] = (line[i] + line[i - ch]) & 255
        elif f == 2:
            line = (line + prev) & 255
        elif f == 3:
            for i in range(stride):
                a = line[i - ch] if i >= ch else 0
                line[i] = (line[i] + ((a + prev[i]) >> 1)) & 255
        elif f == 4:
            for i in range(stride):
                a = line[i - ch] if i >= ch else 0
                bb = prev[i]
                c = prev[i - ch] if i >= ch else 0
                pp = a + bb - c
                pa, pb, pc = abs(pp - a), abs(pp - bb), abs(pp - c)
                pr = a if (pa <= pb and pa <= pc) else (bb if pb <= pc else c)
                line[i] = (line[i] + pr) & 255
        prev = line
        out[y] = line.reshape(w, ch)
    return out[:, :, :3] if ch >= 3 else np.repeat(out, 3, axis=2)


img = read_png(sys.argv[1])
h, w, _ = img.shape
r = img[:, :, 0].astype(np.int16)
g = img[:, :, 1].astype(np.int16)
b = img[:, :, 2].astype(np.int16)
mask = (r > 110) & (b > 110) & (r - g > 45) & (b - g > 25)
top = mask[:170, :]
print("图 %dx%d  顶栏粉色像素 %d" % (w, h, int(top.sum())))
dens = top.sum(0)
segs = []
st = None
for x in range(w):
    if dens[x] > 0 and st is None:
        st = x
    elif dens[x] == 0 and st is not None:
        segs.append((st, x - 1))
        st = None
if st is not None:
    segs.append((st, w - 1))
for s0, s1 in segs:
    if s1 - s0 < 20:
        continue
    sub = top[:, s0:s1 + 1]
    rr = np.nonzero(sub.any(1))[0]
    print("   x %4d..%-4d 宽=%3d  y %d..%d  质量=%d"
          % (s0, s1, s1 - s0 + 1, int(rr.min()), int(rr.max()), int(sub.sum())))
