#!/usr/bin/env python3
"""牌局模式（Poker）支持：读手牌花色 + 凑同花决策。

## 牌局模式机制（实测 + 官方 wiki 核对）

每消除一次某颜色的宝石 ⇒ 得到一张该花色的牌。
集齐 5 张后判定牌型给分，然后手牌清空重发。

分值表（画面左上角，实测与 wiki 一致）：
    同花 Flush        50000
    四条 4 of a Kind  30000
    葫芦 Full House   15000
    三条 3 of a Kind  10000
    两对 2 Pair        7500
    散牌 Spectrum      5000     （五张花色全不同）
    一对 Pair          2500

## ★★ 骷髅机制（这是策略的核心，来自官方 wiki）

随着游戏进行，**低阶牌型会被标记骷髅**。
打出带骷髅标记的牌型 ⇒ **抛硬币**：四叶草=继续（该手不得分）、骷髅=游戏结束。

每种牌型有自己的"骷髅生成率"和"必定生成骷髅的手数"：

| 牌型 | 分值 | 骷髅生成率 | 多少手后必定生成 |
|---|---|---|---|
| 一对   | 2500  | 10% | 10 手 |
| 散牌   | 5000  | 15% | 12 手 |
| 两对   | 7500  | 20% | 23 手 |
| 三条   | 10000 | 35% | 30 手 |
| 葫芦   | 15000 | 50% | 40 手 |
| 四条   | 30000 | 75% | 90 手 |
| **同花** | **50000** | **100%** | **永远不会** |

（"骷髅生成率"= 打出该牌型时给低阶牌型加骷髅的概率；
  "必生成手数"= 打够这么多次该牌型后，它自己必定被标骷髅）

### 由此得出的策略

1. **同花永远不生成骷髅** ⇒ 追同花既最赚（50000）又绝对安全
2. **每打一手低阶牌型都在积攒骷髅** ⇒ 不能"有步就走"，要忍住
3. **手牌没凑齐牌型时，宁可多消少打** —— 因为打出去的每一手都在加骷髅
4. **四条/葫芦也危险**（75% / 50% 生成率）⇒ 不值得为它们牺牲追同花的机会

这条修正了最初的设计：原以为"手牌全背面时就走普通评分先拿分"，
实际上那等于**疯狂打低阶牌型、加速积累骷髅**，是在自杀。

特殊牌：火焰牌 +100 分、闪电牌 +250 分、万能牌可当任意花色。

## 手牌怎么读

手牌不读内存，直接看画面。原因是手牌在内存里没有找到稳定的结构
（Board 对象内扫过 0x0~0x4000，全是零填充的假阳性），
而它在画面上位置固定、只有 5 张，截一小块判颜色几毫秒就够了
（读整个棋盘也才 1.18 ms）。
"""
import numpy as np

# 5 张牌的取样区（1280x800 绝对坐标，实测标定）
#   依据：扫描 y=345..465 / x=155..360 确认牌的实际范围（红白菱形花纹密集区）。
#   每张牌取一个 20x20 的方块求"最饱和 25% 像素"的均值 —— 单点取样太脆弱，
#   因为牌面有高光、白边和菱形花纹。
CARD_BOXES = [
    (150, 355, 190, 455),   # 牌 1: x0,y0,x1,y1
    (188, 355, 228, 455),   # 牌 2
    (226, 355, 266, 455),   # 牌 3
    (264, 355, 304, 455),   # 牌 4
    (302, 355, 342, 455),   # 牌 5
]
CARD_R = 6   # 兼容旧接口

# 宝石颜色参考（与 vision_np 同一套）
REF = {
    "R": (252, 28, 58),
    "W": (238, 238, 238),
    "G": (12, 205, 32),
    "Y": (251, 220, 22),
    "P": (185, 6, 185),
    "O": (250, 110, 20),
    "B": (8, 120, 243),
}

COLOR_NAME = {"R": "红", "W": "白", "G": "绿", "Y": "黄",
              "P": "紫", "O": "橙", "B": "蓝", "?": "背面"}


def _card_color(frame, cx, cy):
    """读一张牌的主色。cx,cy 是牌中心。返回 (glyph, rgb, sat)。

    ★ 2026-09-24 踩过的坑（务必保留此注释）：
       最初用「取最饱和的 25% 像素」来排除白边框，阈值为 sat 的 75 分位。
       但牌面常常 77% 都是白色（宝石只占中间一小块），
       此时 75 分位 = 0 ⇒ "sat >= 0" 选中了全部像素
       ⇒ 均值被白色淹没 ⇒ 黄/蓝宝石被读成 '?'。
       修法：改用**固定饱和度阈值**，而不是分位数。
    """
    # 找到 cx,cy 落在哪个牌框里
    box = None
    for (x0, y0, x1, y1) in CARD_BOXES:
        if x0 <= cx <= x1 and y0 <= cy <= y1:
            box = (x0, y0, x1, y1)
            break
    if box is None:
        patch = frame[max(0, cy - CARD_R):cy + CARD_R + 1,
                      max(0, cx - CARD_R):cx + CARD_R + 1]
    else:
        x0, y0, x1, y1 = box
        patch = frame[y0 + 6:y1 - 6, x0 + 6:x1 - 6]   # 缩进避开牌边白框
    if patch.size == 0:
        return "?", (0, 0, 0), 0.0
    flat = patch.reshape(-1, 3).astype(np.float32)
    r0, g0, b0 = flat[:, 0], flat[:, 1], flat[:, 2]

    # ① 牌背判据：红白菱形花纹。红色的"菱形"占相当比例。
    #    实测牌背的红 ≈ RGB(233,1,1)，占比 0.36~0.45。
    is_diamond_red = (r0 > 190) & (g0 < 80) & (b0 < 80)
    red_ratio = float(is_diamond_red.mean())
    if red_ratio > 0.30:
        mx = flat.max(1); mn = flat.min(1)
        sat = np.where(mx > 0, (mx - mn) / np.maximum(mx, 1), 0)
        return "?", (float(r0.mean()), float(g0.mean()), float(b0.mean())), \
               float(np.percentile(sat, 90))

    # ② 取高饱和像素（固定阈值，绝不用分位数）
    mx = flat.max(1); mn = flat.min(1)
    sat_all = np.where(mx > 0, (mx - mn) / np.maximum(mx, 1), 0)
    sel = flat[sat_all >= 0.45]
    if len(sel) < 20:
        # 高饱和像素太少 —— 可能是白色宝石（骷髅）或低饱和牌面
        sel2 = flat[sat_all >= 0.25]
        sel = sel2 if len(sel2) >= 20 else flat
    r, g, b = [float(v) for v in sel.mean(axis=0)]
    mxv, mnv = max(r, g, b), min(r, g, b)
    satv = (mxv - mnv) / mxv if mxv > 0 else 0.0

    # ③ 白色宝石：整体很亮、接近中性
    if r > 200 and g > 200 and b > 200 and satv < 0.20:
        return "W", (r, g, b), satv

    best, bd = "?", 1e9
    for key, ref in REF.items():
        d = (r - ref[0]) ** 2 + (g - ref[1]) ** 2 + (b - ref[2]) ** 2
        if d < bd:
            bd, best = d, key
    if bd > 115 ** 2:
        return "?", (r, g, b), satv
    return best, (r, g, b), satv


def read_hand(frame, verbose=False):
    """读手牌。返回 5 个花色字符的 list，'?' 表示牌面朝下。"""
    if frame is None:
        return None
    out = []
    for k, (x0, y0, x1, y1) in enumerate(CARD_BOXES):
        cx, cy = (x0 + x1) // 2, (y0 + y1) // 2
        try:
            g, rgb, sat = _card_color(frame, cx, cy)
        except Exception:
            g, rgb, sat = "?", (0, 0, 0), 0.0
        out.append(g)
        if verbose:
            print("    牌%d 框(%d,%d)-(%d,%d) RGB=(%.0f,%.0f,%.0f) sat=%.2f → %s"
                  % (k + 1, x0, y0, x1, y1, rgb[0], rgb[1], rgb[2], sat,
                     COLOR_NAME.get(g, "?")))
    return out


def best_flush_color(hand):
    """给定手牌，返回最值得追的花色。"""
    if not hand:
        return None
    cnt = {}
    for c in hand:
        if c and c != "?":
            cnt[c] = cnt.get(c, 0) + 1
    if not cnt:
        return None
    mx = max(cnt.values())
    cands = [c for c, n in cnt.items() if n == mx]
    return cands[0] if len(cands) == 1 else cands


# 各牌型的骷髅风险：(骷髅生成率, 必定生成骷髅的手数)
SKULL_RISK = {
    "一对":   (0.10, 10),
    "散牌":   (0.15, 12),
    "两对":   (0.20, 23),
    "三条":   (0.35, 30),
    "葫芦":   (0.50, 40),
    "四条":   (0.75, 90),
    "同花":   (1.00, None),   # 100% 生成率，但同花自己永远不会被标骷髅
}
SAFE_HANDS = {"同花"}


def skull_risk(name):
    """返回 (生成骷髅的概率, 必定生成的手数)。同花是安全的。"""
    return SKULL_RISK.get(name, (0.0, None))


def is_safe_hand(name):
    return name in SAFE_HANDS


def should_hold(hand, plays=None):
    """判断该不该"忍住不打"。

    返回 (该不该忍, 理由)。

    原则：
      - 手牌能凑成同花 → 打（安全且最赚）
      - 手牌即将能凑同花（已有 3~4 张同色）→ **忍**，继续追
      - 手牌只能凑低阶牌型 → 越打越多骷髅，但如果已经攒够 5 张、
        再不打就浪费手牌位，则权衡后打
    """
    if not hand:
        return False, "无手牌信息"
    vals = [c for c in hand if c and c != "?"]
    n = len(vals)
    cnt = {}
    for c in vals:
        cnt[c] = cnt.get(c, 0) + 1
    best_n = max(cnt.values()) if cnt else 0
    name, pts, used = hand_value(hand)

    if best_n >= 5:
        return False, "已成同花，打（安全 50000 分）"
    # 已经翻开 5 张、凑不出同花 → 只能打，但要知道风险
    if n >= 5:
        r, cap = skull_risk(name)
        return False, "手牌已满，只能打%s（风险 %.0f%%）" % (name, r * 100)
    # 有 3~4 张同色 → 值得再追
    if best_n >= 3:
        return True, "已有 %d 张同色，继续追同花" % best_n
    # 已翻开 ≥2 张且已构成低阶牌型（如一对）：打出它会给该牌型累加骷髅，
    # 能忍则忍 —— 这是骷髅机制下的核心纪律。
    if n >= 2 and name not in ("无", "同花"):
        r, cap = skull_risk(name)
        return True, "忍住不打%s（会给它加骷髅，生成率 %.0f%%）" % (name, r * 100)
    return False, "只有 %d 张翻开，正常推进" % n


def hand_value(hand):
    """评估当前手牌的牌型与分值。返回 (名称, 分值, 张数)。"""
    vals = [c for c in hand if c and c != "?"] if hand else []
    n = len(vals)
    if n < 2:
        return ("无", 0, n)
    cnt = {}
    for c in vals:
        cnt[c] = cnt.get(c, 0) + 1
    counts = sorted(cnt.values(), reverse=True)
    if 5 in counts:
        return ("同花", 50000, 5)
    if 4 in counts:
        return ("四条", 30000, 4)
    if counts[:2] == [3, 2]:
        return ("葫芦", 15000, 5)
    if 3 in counts:
        return ("三条", 10000, 3)
    if counts.count(2) >= 2:
        return ("两对", 7500, 4)
    if 2 in counts:
        return ("一对", 2500, 2)
    if n == 5:
        return ("散牌", 5000, 5)
    return ("无", 0, n)


if __name__ == "__main__":
    import sys
    sys.path.insert(0, "/home/deck")
    from cap2 import Cap
    c = Cap()
    a = None
    for _ in range(25):
        a = c.get(timeout=1.0)
        if a is not None:
            break
    c.stop()
    print("逐张判定:")
    h = read_hand(a, verbose=True)
    print()
    print("手牌   :", h)
    print("已翻开 :", "".join(x for x in h if x != "?"))
    print("该追   :", best_flush_color(h))
    print("当前牌型:", hand_value(h))
