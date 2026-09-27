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

★ 2026-09-27：`numpy` 改成**惰性导入**（只在 `_card_color` 里 import）。
  原因：本模块里只有"看画面读牌"这一件事需要 numpy，而**决策逻辑**
  （`flush_state` / `hand_value` / 新增的牌型阶梯 `best_plan`）是纯 Python。
  模块级 import 会让整个牌局决策栈在没装 numpy 的机器上 import 就炸
  （本机就是这样：`test_modes.py` / `test_poker.py` 在手机上一行都跑不了，
  只能上 Deck 跑）。惰性之后决策逻辑本机可测，读牌路径行为一字未变。
"""

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

# 七种花色的固定顺序（与 solver_pro.GLYPHS 同一套，牌型阶梯里用来列"还没出现的颜色"）
GLYPHS = "RGOYBPW"


def _card_color(frame, cx, cy):
    """读一张牌的主色。cx,cy 是牌中心。返回 (glyph, rgb, sat)。

    ★ 2026-09-24 踩过的坑（务必保留此注释）：
       最初用「取最饱和的 25% 像素」来排除白边框，阈值为 sat 的 75 分位。
       但牌面常常 77% 都是白色（宝石只占中间一小块），
       此时 75 分位 = 0 ⇒ "sat >= 0" 选中了全部像素
       ⇒ 均值被白色淹没 ⇒ 黄/蓝宝石被读成 '?'。
       修法：改用**固定饱和度阈值**，而不是分位数。
    """
    import numpy as np      # 惰性导入：只有读牌这条路径需要它（见文件头说明）
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


def flush_state(hand):
    """★ 2026-09-26：这手牌还能不能追同花。

    手牌是【从左往右填】的，已翻开的永远是一段前缀（'?' = 还没拿到的空位，
    不是暗牌）。同步抓帧实测序列：

        G???? → GG??? → GR??? → GRR?? → GRG?? → GRGG? → GRGOR → GRGOO（结算）
        ????? → （新一手，重新从左边填）

    同花要求 5 张同色 ⇒ **只要已翻开里出现了第二种颜色，这手同花就已经死了**，
    再追是白费（原来的 best_flush_color 不管这个，`GRGO?` 还在追 G）。

    返回 (还能不能追, 锁定的目标色, 还差几张)。
    手牌全空时返回 (True, None, 5) —— 目标色还没定，交给求解器按盘面选。
    """
    vals = [c for c in (hand or []) if c and c != "?"]
    if not vals:
        return (True, None, 5)
    if len(set(vals)) == 1:
        return (True, vals[0], 5 - len(vals))
    return (False, None, 0)


# ── 牌型阶梯（2026-09-27 新增）────────────────────────────────
#
# 用户要的优先级：**同花 → 四条 → 葫芦 → 三条 → 两对 → 顺子 → 一对**，
# 也就是游戏左上角分值表从高到低。分值本身就是优先级，所以阶梯直接按分值排。
#
# ⚠️ 名字对齐：游戏面板写的是「顺子 5000」（五张花色全不同），
#    本文件历史上叫它「散牌 Spectrum」（wiki 的英文名）。这里沿用内部旧名，
#    免得同一个日志里出现两个名字。
RANK_LADDER = (
    ("同花", 50000),
    ("四条", 30000),
    ("葫芦", 15000),
    ("三条", 10000),
    ("两对", 7500),
    ("散牌", 5000),
    ("一对", 2500),
)
RANK_VALUE = dict(RANK_LADDER)


def best_plan(hand):
    """★ 2026-09-27：这手牌**还能做到**的最高牌型，以及推进它要拿什么花色。

    返回 `(名称, 分值, 还差几张, 目标色列表)`。

    「还差几张」= 凑成该牌型还要连续拿到几张牌（每张都得是目标色）。
    目标色列表可能为空 —— 只有一种情况：手牌一张没翻开，花色还没定，
    这时"目标色"要由盘面决定（交给 solver_poker 按能做出严格多数的步数选）。

    为什么需要它：旧代码在"同花已死"之后只做一件事 —— 选**已翻开里最多**
    的那个色。那是个不错的启发式，但它没把牌型阶梯当回事，于是：

      · 手牌 `GRBY?`（4 张全不同）：最优是再拿一张**手里没有的颜色**凑
        「散牌 5000」，旧代码一定在 G/R/B/Y 里挑 ⇒ 只能凑「一对 2500」
      · 手牌 `GGRB?`（2+1+1）：四条已经没戏（只剩 1 个空位）、葫芦也没戏，
        最优是再拿 G 凑「三条 10000」；旧代码选 G 是对的，但理由是"G 最多"
        而不是"三条比两对高"

    可达性全部按"还剩几个空位"算，不做概率假设。
    """
    vals = [c for c in (hand or []) if c and c != "?"]
    n = len(vals)
    slots = 5 - n
    cnt = {}
    for c in vals:
        cnt[c] = cnt.get(c, 0) + 1

    if n >= 5:                      # 手牌已满，游戏直接结算，没什么可计划的
        name, pts, _ = hand_value(vals)
        return (name, pts, 0, [])

    # ① 同花：已翻开的全同色（一张没翻开也算"还活着"，只是还没定色）
    if len(cnt) <= 1:
        c = vals[0] if vals else None
        return ("同花", RANK_VALUE["同花"], 5 - n, [c] if c else [])

    # ② 四条：某个色还差几张贴满 4 张
    need = {c: 4 - cnt[c] for c in cnt if 4 - cnt[c] <= slots}
    if need:
        k = min(need.values())
        return ("四条", RANK_VALUE["四条"], k, [c for c in need if need[c] == k])

    # ③ 葫芦：三张 + 一对（两个色，凑齐所需张数之和不超过空位数）
    hulu = []
    for a in cnt:
        for b in cnt:
            if a == b:
                continue
            x = max(0, 3 - cnt[a])
            y = max(0, 2 - cnt[b])
            if x + y <= slots:
                hulu.append((x + y, a, b))
    if hulu:
        k = min(x for x, _, _ in hulu)
        tg = []
        for x, a, b in hulu:
            if x == k:
                for c in (a, b):
                    if c not in tg:
                        tg.append(c)
        return ("葫芦", RANK_VALUE["葫芦"], k, tg)

    # ④ 三条
    need = {c: 3 - cnt[c] for c in cnt if 3 - cnt[c] <= slots}
    if need:
        k = min(need.values())
        return ("三条", RANK_VALUE["三条"], k, [c for c in need if need[c] == k])

    # ⑤ 两对
    two = []
    ks = sorted(cnt)
    for ai in range(len(ks)):
        for bi in range(ai + 1, len(ks)):
            a, b = ks[ai], ks[bi]
            x = max(0, 2 - cnt[a])
            y = max(0, 2 - cnt[b])
            if x + y <= slots:
                two.append((x + y, a, b))
    if two:
        k = min(x for x, _, _ in two)
        tg = []
        for x, a, b in two:
            if x == k:
                for c in (a, b):
                    if c not in tg:
                        tg.append(c)
        return ("两对", RANK_VALUE["两对"], k, tg)

    # ⑥ 散牌（游戏面板叫「顺子」）：5 张全不同 ⇒ 接下来拿手里**还没有**的颜色
    if len(cnt) + slots >= 5:
        return ("散牌", RANK_VALUE["散牌"], 5 - n,
                [c for c in GLYPHS if c not in cnt])

    # ⑦ 一对
    need = {c: 2 - cnt[c] for c in cnt if 2 - cnt[c] <= slots}
    if need:
        k = min(need.values())
        return ("一对", RANK_VALUE["一对"], k, [c for c in need if need[c] == k])
    return ("无", 0, slots, [])


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
