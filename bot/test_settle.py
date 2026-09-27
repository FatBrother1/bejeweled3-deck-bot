#!/usr/bin/env python3
"""结算画面判据回归测试（2026-09-26）。

为什么要单独测这个：`screen_is_gameover` 每轮都跑，**判错的代价是不对称的** ——
   · 漏判（该 True 判成 False）→ bot 对着结算画面一直"下棋"，
     走法全被拒 → 全拉黑 → 解禁 → 再出同一招（用户报的"空转和重复交换"），
     而且**永远点不到「再玩一次」**（"再来一局开关不起效果"）；
   · 误判（该 False 判成 True）→ 对局中途去点 (640,738)，
     那是棋盘下方，轻则白送一步，重则点到别的按钮。
所以两边都要有硬样本，而且阈值要离两侧都远。

样本放在 /home/deck/bjbot/settle_refs/{pos,neg}/，都是 1280x800 真实抓帧。
没有这个目录时测试跳过（不算失败）—— 它依赖上机抓的帧，不是纯离线件。

判据本体：bot_v6.screen_is_gameover
  区域 (150:450, 200:1080)，特征 (R-B)>60 的像素占比，阈值 0.75。
"""
import os
import sys

sys.path.insert(0, "/home/deck")

PASS, FAIL = [], []


def check(name, ok, extra=""):
    (PASS if ok else FAIL).append(name)
    print("  %s %s%s" % ("✓" if ok else "✗", name, ("  " + extra) if extra else ""))


REFS = "/home/deck/bjbot/settle_refs"

try:
    import numpy as np
    from PIL import Image
    import bot_v6
except Exception as e:
    print("环境不满足（需要 numpy/Pillow 和 /home/deck 下的 bot_v6.py）: %s" % e)
    sys.exit(0)

if not os.path.isdir(REFS):
    print("跳过：%s 不存在（需要上机抓的样本帧）" % REFS)
    sys.exit(0)


def load(p):
    return np.asarray(Image.open(p).convert("RGB"), dtype="float32")


def ratio(a):
    p = a[150:450, 200:1080]
    r, b = p[:, :, 0], p[:, :, 2]
    return float(((r - b) > 60).mean())


# ── 期望表：文件 → (最低/最高判据值, 期望 screen_is_gameover) ──────────────
#   结算是 0.887~0.912，非结算是 0.000~0.647，阈值 0.75 落在中间。
POS_MIN = 0.80        # 结算必须至少这么高
NEG_MAX = 0.70        # 非结算必须最多这么高

print("\nA. 结算画面（必须判 True）")
posdir = os.path.join(REFS, "pos")
pos = sorted(f for f in os.listdir(posdir) if f.endswith(".png")) if os.path.isdir(posdir) else []
check("有结算样本帧", len(pos) >= 3, "共 %d 张" % len(pos))
for fn in pos:
    a = load(os.path.join(posdir, fn))
    v = ratio(a)
    check("%-26s 判据=%.3f ≥ %.2f" % (fn, v, POS_MIN), v >= POS_MIN)
    check("%-26s screen_is_gameover=True" % fn,
          bot_v6.screen_is_gameover(a) is True)

print("\nB. 非结算画面（必须判 False）")
negdir = os.path.join(REFS, "neg")
neg = sorted(f for f in os.listdir(negdir) if f.endswith(".png")) if os.path.isdir(negdir) else []
check("有非结算样本帧", len(neg) >= 8, "共 %d 张" % len(neg))
for fn in neg:
    a = load(os.path.join(negdir, fn))
    if a.shape[0] < 460 or a.shape[1] < 1085:
        print("  · %-26s 尺寸 %s 太小，判据按设计返回 None，跳过"
              % (fn, a.shape[:2]))
        continue
    v = ratio(a)
    check("%-26s 判据=%.3f ≤ %.2f" % (fn, v, NEG_MAX), v <= NEG_MAX)
    check("%-26s screen_is_gameover=False" % fn,
          bot_v6.screen_is_gameover(a) is False)

print("\nD. 徽章面板识别（screen_is_badge，必须与结算面板分得开）")
badgedir = os.path.join(REFS, "badge")
badge = sorted(f for f in os.listdir(badgedir) if f.endswith(".png")) if os.path.isdir(badgedir) else []
check("有徽章面板样本帧", len(badge) >= 1, "共 %d 张" % len(badge))
for fn in badge:
    a = load(os.path.join(badgedir, fn))
    check("%-26s screen_is_badge=True" % fn, bot_v6.screen_is_badge(a) is True)
# 结算面板必须【不】被当成徽章面板（否则会去点 (640,716)，那是柱状图区）
for fn in pos:
    a = load(os.path.join(posdir, fn))
    check("%-26s 结算不被当成徽章面板" % fn,
          bot_v6.screen_is_badge(a) is False)
# 其余所有参考帧也都不能是徽章面板。
#   ⚠️ neg/ 里有两张**本来就是徽章面板**的帧（它们同时是"结算判据"的负样本，
#      所以留在 neg/ 不能挪走）—— 按文件名把它们排除在"误判"统计外。
KNOWN_BADGE = {"badge_overlay.png"}
bad_hits = []
others = [f for f in os.listdir(negdir)
          if f.endswith(".png") and f not in KNOWN_BADGE]
for fn in others:
    a = load(os.path.join(negdir, fn))
    if a.shape[0] < 80 or a.shape[1] < 951:
        continue
    if bot_v6.screen_is_badge(a) is True:
        bad_hits.append(fn)
check("其余 %d 张参考帧没有一张被误判成徽章面板" % len(others),
      not bad_hits, ("误判: " + ", ".join(bad_hits)) if bad_hits else "")
# 而 neg/badge_overlay.png 本身【应该】被认成徽章面板（它确实是）
check("neg/badge_overlay.png 被正确认成徽章面板",
      bot_v6.screen_is_badge(load(os.path.join(negdir, "badge_overlay.png"))) is True)

print("\nC. 两侧余量（阈值 0.75）")
worst_pos = min((ratio(load(os.path.join(posdir, f))) for f in pos), default=None)
best_neg = max((ratio(load(os.path.join(negdir, f))) for f in neg), default=None)
if worst_pos is not None:
    check("最低的结算样本 %.3f 高于阈值 0.75" % worst_pos, worst_pos > 0.75,
          "余量 +%.3f" % (worst_pos - 0.75))
if best_neg is not None:
    check("最高的非结算样本 %.3f 低于阈值 0.75" % best_neg, best_neg < 0.75,
          "余量 -%.3f" % (0.75 - best_neg))
if worst_pos is not None and best_neg is not None:
    check("两侧余量都 ≥ 0.08（阈值没擦边）",
          (worst_pos - 0.75) >= 0.08 and (0.75 - best_neg) >= 0.08)

print("\n" + "=" * 62)
print("通过 %d / 失败 %d" % (len(PASS), len(FAIL)))
if FAIL:
    print("失败项:")
    for f in FAIL:
        print("  - " + f)
    sys.exit(1)
