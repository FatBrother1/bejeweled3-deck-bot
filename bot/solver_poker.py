#!/usr/bin/env python3
"""牌局模式求解器：优先凑同花。

## 和普通模式的根本区别

普通模式：每次消除都给分，所以追求"每一步分最高"。
牌局模式：**只有集齐 5 张牌才给分**，消得多但花色杂 = 白消。

所以要换目标函数：
1. **优先消除"目标花色"的宝石** —— 目标花色 = 手牌里已翻开最多的那个
2. 同分时再看常规得分（连消、格数）
3. 避免把好牌消掉：如果某步消的是"目标花色"，加权最大

## 分值表（画面左上角实测 + 资料核对）

    同花 50000 > 四条 30000 > 葫芦 15000 > 三条 10000
    > 两对 7500 > 顺子 5000 > 一对 2500

同花是第二名的 1.67 倍，所以**永远优先追同花**。

## 特殊宝石在牌局里的价值

    火焰牌 +100 分、闪电牌 +250 分、万能牌可当任意花色
万能牌价值最高 —— 它能补上缺的那张，等于把"差一张"变成同花。
"""
import solver_pro

GLYPHS = "RPGWOYB"
_LAST_TARGET = [None]


def _colors_in_move(g, sim_result):
    """算出这一步会消掉哪些颜色的宝石，各多少个。

    sim_result 是 solver_pro.simulate 的返回值，
    其中 first_cells 是首层消除的格子坐标列表。
    """
    total, casc, first_cells, first_runs, specials, final = sim_result
    cnt = {}
    for (r, c) in first_cells:
        ch = g[r][c] if 0 <= r < 8 and 0 <= c < 8 else None
        if ch and ch != "?":
            cnt[ch] = cnt.get(ch, 0) + 1
    return cnt


def get_last_target():
    """返回上一次 rank_moves_poker 用的目标花色（给日志用）。"""
    return _LAST_TARGET[0]


def rank_moves_poker(g, hand=None, target=None, w_target=6.0, w_score=1.0,
                     w_special=8.0, w_pot=2.0, topk=0):
    """牌局模式打分。

    hand   : poker.read_hand() 的结果（list of 花色字符，'?' 是背面）
    target : 目标花色；给了就用它，否则从 hand 推断
    w_target : 消掉目标花色的权重（这是本模式的核心）
    """
    # 目标花色
    if target is None and hand:
        import poker
        t = poker.best_flush_color(hand)
        if isinstance(t, list):
            # 并列（手牌里几张该色一样多）→ 选棋盘上宝石更多的那个，
            # 因为棋盘上越多越容易堆到 5 张。
            counts = {}
            for row in g:
                for ch in row:
                    if ch and ch != "?":
                        counts[ch] = counts.get(ch, 0) + 1
            target = max(t, key=lambda x: counts.get(x, 0))
        elif t is None:
            # 一张都没翻开 → 选棋盘上最多的颜色
            counts = {}
            for row in g:
                for ch in row:
                    if ch and ch not in ("?", "S"):
                        counts[ch] = counts.get(ch, 0) + 1
            target = max(counts, key=counts.get) if counts else None
        else:
            target = t

    # ★ 手上全背面（一张都没翻开）时，没有花色信息可依据。
    #   这时退化成"选棋盘上最多的颜色"来堆牌 —— 已在上面的 target 推断里处理。
    #   但更稳的做法是：仍按普通评分选最优走法，因为这时候追哪色都一样，
    #   不如先把分数拿到手。
    _LAST_TARGET[0] = target
    out = []
    for i in range(8):
        for j in range(8):
            for (i2, j2) in ((i, j + 1), (i + 1, j)):
                if i2 > 7 or j2 > 7:
                    continue
                a, b = g[i][j], g[i2][j2]
                if a in ("?", None) or b in ("?", None):
                    continue
                # 超立方体：任意交换都合法
                is_cube = (a == "S" or b == "S")
                if not is_cube and a == b:
                    continue
                sim = solver_pro.simulate(g, i, j, i2, j2)
                if sim is None:
                    continue
                total, casc, first_cells, first_runs, spec, final = sim
                if total <= 0:
                    continue

                colcnt = _colors_in_move(g, sim)
                t_hit = colcnt.get(target, 0) if target else 0
                cube_bonus = 1 if is_cube else 0
                cleared = len(set(first_cells))

                # ★★ 策略核心（2026-09-24 实证规则）★★
                #
                # 实测出牌规则：一次消除给【一张】牌，花色 = 这次消除的【多数色】。
                #   证据：消 B×2 + G×1 → 只加了一张 B（不是各加一张）；
                #         消 R×2 + Y×1 → 加 R；消 R×1 + Y×2 → 加 Y。
                #
                # 推论（重要）：**"消到目标色"是不够的，必须让目标色成为多数色**。
                #   消 X×1 但别的色×3 ⇒ 拿到的是别的色的牌，等于白消。
                #
                # 手牌满 5 张自动结算，玩家无法选择"打不打"，
                # 唯一能控制的就是"让哪种颜色成为多数色"。
                # 同花 50000 分且永不生成骷髅 ⇒ 唯一目标就是尽快凑同花。
                t_dom = 0
                if target and colcnt:
                    top = max(colcnt.values())
                    if colcnt.get(target, 0) == top and top > 0:
                        t_dom = 1                     # 目标色是多数色 ✓
                if t_dom:
                    score = (2000.0                        # 目标色当多数色 = 唯一要的
                             + 100.0 * colcnt.get(target, 0)
                             + w_score * total
                             + w_special * spec
                             + w_pot * solver_pro.potential(final)
                             + 30.0 * cube_bonus)
                elif t_hit > 0:
                    score = (10.0 * t_hit                 # 消到目标色但不是多数色，聊胜于无
                             + 0.2 * total)
                else:
                    score = (0.05 * total                 # 完全没消到目标色 = 几乎不考虑
                             + w_special * spec * 0.5)
                out.append((score, total, cleared, casc, spec, (i, j), (i2, j2),
                            final, t_hit, t_dom))
    out.sort(key=lambda t: -t[0])
    return out[:topk] if topk else out


def best_move_poker(g, hand=None, target=None, **kw):
    """返回 (预测得分, 消格数, (i1,j1), (i2,j2))，没有走法返回 None。"""
    r = rank_moves_poker(g, hand=hand, target=target, **kw)
    if not r:
        return None
    t = r[0]
    return (t[1], t[2], t[5], t[6])


if __name__ == "__main__":
    # 造一个局面测试：目标花色绿(G)，看它是否优先选消绿的走法
    g = [
        ["G", "G", "R", "O", "B", "Y", "P", "W"],
        ["R", "O", "G", "Y", "P", "B", "W", "G"],
        ["O", "Y", "P", "B", "W", "G", "R", "O"],
        ["B", "W", "G", "R", "O", "Y", "P", "B"],
        ["Y", "P", "B", "W", "G", "R", "O", "Y"],
        ["W", "G", "R", "O", "Y", "P", "B", "W"],
        ["P", "B", "Y", "G", "R", "O", "W", "P"],
        ["G", "R", "O", "Y", "P", "B", "W", "G"],
    ]
    hand = ["G", "B", "?", "?", "?"]
    r = rank_moves_poker(g, hand=hand, topk=5)
    print("目标花色应为 G（手牌里 G 和 B 各 1 张，取棋盘上多的）")
    for t in r:
        print("  分=%.0f 直接得分=%-4d 消目标色=%-2d %s<->%s"
              % (t[0], t[1], t[8], t[5], t[6]))
