#!/usr/bin/env python3
"""离线测试：抓帧兜底（cap2.Cap）与 PipeWire 节点发现（find_video_node）。

背景（2026-09-27，用户点名"修复啊"）：
  PipeWire 的视频节点整条消失（实测 pw-dump 里一个 Video 节点都没有），
  而引擎直接用 PwCapture、写死 path=93 ⇒ 拿不到帧就 log 一行 return，
  守护每十几秒拉起来一次、bot 永远瞎着。
  本测试不需要真的 PipeWire / gamescope / numpy，全部用假件顶掉。
"""
import sys, types, json, time

# ── 本机没装 numpy/PIL；cap2 与 capture_pw 顶层就 import 它们 ──
def _stub(name, **attrs):
    m = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(m, k, v)
    sys.modules[name] = m
    return m


try:
    import numpy  # noqa: F401
except Exception:
    _stub("numpy", asarray=lambda x: x, frombuffer=lambda b, dtype=None: None,
          uint8=object, ndarray=object)
try:
    from PIL import Image  # noqa: F401
except Exception:
    _pil = _stub("PIL")
    _stub("PIL.Image", open=lambda *a, **k: None, verify=lambda: None)
    _pil.Image = sys.modules["PIL.Image"]

sys.path.insert(0, "/home/deck")
sys.path.insert(0, ".")
import cap2          # noqa: E402
import capture_pw    # noqa: E402

OK = 0
BAD = []


def ck(name, cond, extra=""):
    global OK
    if cond:
        OK += 1
        print("  ✓ %s" % name)
    else:
        BAD.append(name)
        print("  ✗ %s   %s" % (name, extra))


# ══════════════════════════════════════════════════════════════
# A. find_video_node：从 pw-dump 里找视频源
# ══════════════════════════════════════════════════════════════
print("A. find_video_node（pw-dump 解析）")


class _Run:
    def __init__(self, out=None, boom=False):
        self.out = out
        self.boom = boom

    def __call__(self, *a, **k):
        if self.boom:
            raise OSError("pw-dump 不存在")
        return types.SimpleNamespace(stdout=self.out)


def _nodes(*specs):
    """specs: (id, media.class, node.name)"""
    out = []
    for i, mc, nm in specs:
        out.append({"id": i, "type": "PipeWire:Interface:Node",
                    "info": {"props": {"media.class": mc, "node.name": nm}}})
    return json.dumps(out).encode()


_orig_run = capture_pw.subprocess.run

capture_pw.subprocess.run = _Run(_nodes((30, "Audio/Sink", "speaker"),
                                        (93, "Video/Source", "gamescope-0")))
ck("A1 点名 gamescope 的那个", capture_pw.find_video_node() == 93,
   capture_pw.find_video_node())

capture_pw.subprocess.run = _Run(_nodes((11, "Video/Source", "v4l2"),
                                        (12, "Video/Source", "gamescope")))
ck("A2 有 gamescope 就优先它（不是第一个）", capture_pw.find_video_node() == 12,
   capture_pw.find_video_node())

capture_pw.subprocess.run = _Run(_nodes((11, "Video/Source", "v4l2"),
                                        (12, "Audio/Source", "mic")))
ck("A3 没有 gamescope 就用第一个视频源", capture_pw.find_video_node() == 11,
   capture_pw.find_video_node())

capture_pw.subprocess.run = _Run(_nodes((1, "Audio/Sink", "a"), (2, "Video/Sink", "b")))
ck("A4 一个 Video/Source 都没有 → None（就是今天坏掉的样子）",
   capture_pw.find_video_node() is None, capture_pw.find_video_node())

capture_pw.subprocess.run = _Run("这不是 json".encode("utf-8"))
ck("A5 pw-dump 输出不是 json → None", capture_pw.find_video_node() is None)

capture_pw.subprocess.run = _Run(boom=True)
ck("A6 pw-dump 起不来 → None", capture_pw.find_video_node() is None)

capture_pw.subprocess.run = _Run(_nodes((5, "Video/Source", "x")))
ck("A7 混进坏条目也不崩",
   capture_pw.find_video_node() == 5, capture_pw.find_video_node())


# ══════════════════════════════════════════════════════════════
# B. PwCapture：节点 id 自动发现 + start(wait=)
# ══════════════════════════════════════════════════════════════
print("B. PwCapture 自动找节点 / start 可设等待")
POPEN = {}


class _Popen:
    def __init__(self, cmd, **k):
        POPEN["cmd"] = cmd
        self.stdout = types.SimpleNamespace(read=lambda n: b"")

    def kill(self):
        POPEN["killed"] = True


capture_pw.subprocess.run = _Run(_nodes((77, "Video/Source", "gamescope")))
capture_pw.subprocess.Popen = _Popen
c = capture_pw.PwCapture()
ok = c.start(wait=0.15)
ck("B1 auto 模式下 path 取自发现到的节点", c.path == 77, c.path)
ck("B2 gst 命令里用的是发现到的节点", "path=77" in POPEN["cmd"], POPEN["cmd"][:6])
ck("B3 出不了帧时 start 返回 False", ok is False)

capture_pw.subprocess.run = _Run(_nodes((1, "Audio/Sink", "a")))
c = capture_pw.PwCapture()
c.start(wait=0.15)
ck("B4 发现不到节点 → 退回写死的 93", c.path == 93, c.path)

c = capture_pw.PwCapture(path=42)
capture_pw.subprocess.run = _Run(_nodes((77, "Video/Source", "gamescope")))
c.start(wait=0.15)
ck("B5 显式给 path 就不去发现（保持老调用可用）", c.path == 42, c.path)

capture_pw.subprocess.run = _Run(_nodes((77, "Video/Source", "gamescope")))
capture_pw.PwCapture(path=93).start(wait=0.15)
ck("B6 显式 93 时命令仍是 path=93", "path=93" in POPEN["cmd"], POPEN["cmd"][:6])


# ══════════════════════════════════════════════════════════════
# C. cap2.Cap：兜底与回切
# ══════════════════════════════════════════════════════════════
print("C. cap2.Cap（PipeWire 坏 → 兜底 → 回切）")

CFG = {"start_ok": True, "get": "fresh"}
MADE = []
SHOTS = [0]
LOGS = []


class FakePw:
    def __init__(self, path=None, **kw):
        self.path = 93 if path is None else path
        self.err = None
        self.running = True
        self.seq = 0
        self.stopped = False
        MADE.append(self)

    def start(self, wait=8.0):
        self.wait = wait
        if not CFG["start_ok"]:
            self.err = "eof"
            self.running = False
        return CFG["start_ok"]

    def get(self, timeout=1.0):
        m = CFG["get"]
        if m == "die":
            self.err = "eof"
            self.running = False
            return "PW"
        if m == "stall":
            return "PW"
        self.seq += 1
        return "PW"

    def stop(self):
        self.stopped = True
        self.running = False


def _shot(self):
    SHOTS[0] += 1
    return "SHOT"


cap2.PwCapture = FakePw            # cap2 里是函数内 import，改模块属性即可
cap2.Cap._shot = _shot
capture_pw.PwCapture = FakePw

# C1 PipeWire 好用：一直走 PipeWire，绝不碰 gamescopectl
CFG.update(start_ok=True, get="fresh")
MADE.clear(); SHOTS[0] = 0; LOGS.clear()
c = cap2.Cap(log=LOGS.append)
ck("C1a 启动即拿到 PipeWire", c.ok_pw is True and c.backend == "PipeWire", c.err)
ck("C1b start() 为真", c.start() is True)
ck("C1c 取到的是 PipeWire 的帧", c.get(timeout=0.05) == "PW")
ck("C1d 没走兜底", SHOTS[0] == 0, SHOTS[0])

# C2 启动就坏（今天现场：pw-dump 里没有 Video 节点）
CFG.update(start_ok=False, get="fresh")
MADE.clear(); SHOTS[0] = 0; LOGS.clear()
c = cap2.Cap(log=LOGS.append)
ck("C2a 启动失败 → 标记不可用", c.ok_pw is False and c.pw is None)
ck("C2b backend 报 gamescopectl", c.backend == "gamescopectl", c.backend)
ck("C2c start() 仍为真（兜底能出图）", c.start() is True)
ck("C2d 取到的是兜底的帧", c.get(timeout=0.05) == "SHOT", SHOTS[0])
ck("C2e 日志里说清了为什么退", any("兜底" in x for x in LOGS), LOGS)

# C3 运行中断了（旧代码在这里会一直返回最后一帧）
CFG.update(start_ok=True, get="fresh")
MADE.clear(); SHOTS[0] = 0; LOGS.clear()
c = cap2.Cap(log=LOGS.append)
ck("C3a 先确认在 PipeWire 上", c.backend == "PipeWire")
CFG["get"] = "die"
f = c.get(timeout=0.05)
ck("C3b 这一帧不返回冻住的旧帧，直接给兜底帧", f == "SHOT", f)
ck("C3c 已经切到兜底", c.backend == "gamescopectl" and c.ok_pw is False)
ck("C3d 旧的 PipeWire 被停掉", MADE[0].stopped is True)
ck("C3e 日志里报了断线", any("断了" in x for x in LOGS), LOGS)
ck("C3f 后续帧继续来自兜底", c.get(timeout=0.05) == "SHOT")

# C4 运行中卡住（err 没置位、线程还在，但一帧新的都没有）
CFG.update(start_ok=True, get="fresh")
MADE.clear(); SHOTS[0] = 0; LOGS.clear()
c = cap2.Cap(log=LOGS.append)
CFG["get"] = "stall"
for _ in range(cap2.Cap.STALL - 1):
    c.get(timeout=0.05)
ck("C4a 还没到阈值时仍在 PipeWire 上", c.backend == "PipeWire", c.stall)
c.get(timeout=0.05)
ck("C4b 连续 %d 次没有新帧就判定卡死" % cap2.Cap.STALL, c.backend == "gamescopectl",
   c.stall)
ck("C4c 卡死也有日志", any("卡住" in x for x in LOGS), LOGS)

# C5 在兜底路径上回试 PipeWire，节点回来了就切回去
CFG.update(start_ok=False, get="fresh")
MADE.clear(); SHOTS[0] = 0; LOGS.clear()
c = cap2.Cap(log=LOGS.append)
ck("C5a 先在兜底上", c.backend == "gamescopectl")
CFG["start_ok"] = True
c.last_retry = time.time() - c.RETRY - 1        # 假装已经过了回试间隔
f = c.get(timeout=0.05)
ck("C5b 到点回试，节点回来了就用回 PipeWire", c.backend == "PipeWire", c.backend)
ck("C5c 这一帧来自 PipeWire", f == "PW", f)
ck("C5d 回切有日志", any("可用" in x for x in LOGS), LOGS)
c.get(timeout=0.05)
ck("C5e 回切之后不再走兜底", SHOTS[0] <= 1, SHOTS[0])

# C6 两条路都不行：start() 必须为假（引擎据此 return，不会空转）
CFG.update(start_ok=False, get="fresh")
MADE.clear(); SHOTS[0] = 0; LOGS.clear()
c = cap2.Cap(log=LOGS.append)
cap2.Cap._shot = lambda self: None
ck("C6a 两条路都不行 → start() 为假", c.start() is False)
ck("C6b err 有内容可打", bool(c.err), c.err)
cap2.Cap._shot = _shot

# C7 stop 会停掉 PipeWire
CFG.update(start_ok=True, get="fresh")
MADE.clear(); SHOTS[0] = 0; LOGS.clear()
c = cap2.Cap(log=LOGS.append)
c.stop()
ck("C7 stop() 透传到 PipeWire", MADE[0].stopped is True)

# C8 不带 log 参数也能用（poker.py / which_mode.py 就是这么调的）
CFG.update(start_ok=False, get="fresh")
MADE.clear(); SHOTS[0] = 0; LOGS.clear()
c = cap2.Cap()
ck("C8 不传 log 不报错", c.get(timeout=0.05) == "SHOT")

capture_pw.subprocess.run = _orig_run

print()
print("通过 %d 项，失败 %d 项" % (OK, len(BAD)))
if BAD:
    for b in BAD:
        print("  ✗ " + b)
    sys.exit(1)
print("全部通过")
