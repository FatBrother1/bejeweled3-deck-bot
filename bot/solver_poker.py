#!/usr/bin/env python3
"""牌局模式求解器：优先凑同花。

## 和普通模式的根本区别

普通模式：每次消除都给分，所以追求"每一步分最高"。
牌局模式：**只有集齐 5 张牌才给分**，消得多但花色杂 = 白消。

## 手牌是【从左往右填】的（2026-09-26 同步抓帧实证）

实测序列（bot 打、另一个进程在手牌变化时存帧）：

    G???? → GG??? → GR??? → GRR?? → GRG?? → GRGG? → GRGOR → GRGOO（结算）
    ????? → （新一手，重新从左边填）

⇒ `?` 是【还没拿到的空位】，不是暗牌；已翻开的永远是一段前缀。

**推论（本次优化最重要的一条）**：同花要 5 张同色 ⇒ **已翻开里一出现第二种
颜色，这手同花就已经死了**。原来的 `best_flush_color` 只看"谁多"，`GRGO?`
还在追 G —— 追一个数学上已经不可能的目标。

## 出牌规则（2026-09-24 实测，wiki 未写明）

**一次消除给一张牌，花色 = 这次消除的「多数色」。**

⇒ 不是"消到目标色"就行，**必须让目标色成为多数色**。
⇒ 进一步：**并列多数是不保险的**（消 1G+1R，游戏给哪色未知），
   所以本次把"严格多数"和"并列多数"分开计分，严格多数给更高权重。

## 目标色怎么选（本次重写）

1. 同花还活着（已翻开全同色）→ 锁定那个色，还差 `5-k` 张
2. 同花已死 → 改冲四条/葫芦：选已翻开里最多的那个色
3. 手牌全空 → **按"有多少步能把它做成严格多数色"选**，不再按盘面宝石数选
   （盘面多 ≠ 能凑出多数消除；实测这一步是空手时的关键）

## 分值表

    同花 50000 > 四条 30000 > 葫芦 15000 > 三条 10000
    > 两对 7500 > 顺子 5000 > 一对 2500

同花是第二名的 1.67 倍，而且**永远不会被标骷髅**，所以值得优先追。

## 特殊宝石在牌局里的价值

    火焰牌 +100 分、闪电牌 +250 分、万能牌可当任意花色
"""
import solver_pro

GLYPHS = "RPGWOYB"
_LAST_TARGET = [None]
_LAST_WHY = [None]

# 严格多数 / 并列多数 的基础分。严格多数 = 这一步必定拿到目标色的牌；
# 并列多数 = 游戏给哪一色未知（实测只验过严格多数的例子），所以压低。
SC_STRICT = 2600.0
SC_TIE = 1800.0


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


def _is_strict_majority(colcnt, color):
    """color 是不是这次消除的【严格】多数色（没有并列）。"""
    if not colcnt or not color:
        return False
    order = sorted(colcnt.values(), reverse=True)
    if colcnt.get(color, 0) != order[0] or order[0] <= 0:
        return False
    return len(order) == 1 or order[0] > order[1]


def _is_majority(colcnt, color):
    """color 是不是多数色（并列也算）。"""
    if not colcnt or not color:
        return False
    top = max(colcnt.values())
    return top > 0 and colcnt.get(color, 0) == top


def _board_counts(g):
    c = {}
    for row in g:
        for ch in row:
            if ch and ch not in ("?", "S"):
                c[ch] = c.get(ch, 0) + 1
    return c


def _hand_counts(hand):
    c = {}
    for ch in (hand or []):
        if ch and ch != "?":
            c[ch] = c.get(ch, 0) + 1
    return c


def _pick_target(g, hand, moves):
    """决定这一步追哪个花色。返回 (颜色, 理由)。

    moves: [(sim, colcnt, i, j, i2, j2, is_cube), ...]（已枚举好的合法交换）
    """
    import poker
    alive, locked, need = poker.flush_state(hand)

    if alive and locked:
        return locked, "同花还活着：已 %d 张 %s，还差 %d 张" % (5 - need, locked, need)

    # 每种颜色"能做严格多数"的步数
    strict = {}
    for mv in moves:
        colcnt = mv[1]
        if not colcnt:
            continue
        order = sorted(colcnt.values(), reverse=True)
        if len(order) == 1 or order[0] > order[1]:
            top = max(colcnt, key=colcnt.get)
            strict[top] = strict.get(top, 0) + 1

    board = _board_counts(g)

    if not alive:
        # 同花已死 → 冲四条/葫芦：选已翻开里最多的那个色
        hc = _hand_counts(hand)
        if hc:
            mx = max(hc.values())
            cands = [c for c, n in hc.items() if n == mx]
            t = max(cands, key=lambda x: (strict.get(x, 0), board.get(x, 0)))
            return t, ("同花已死（已翻开 %s 混色）→ 改冲四条/葫芦，追 %s"
                       % ("".join(sorted(hc)), t))

    # 手牌全空：按"能做成严格多数的步数"选
    if not strict:
        if not board:
            return None, "盘面没有可用颜色"
        t = max(board, key=board.get)
        return t, "没有任何一步能做出严格多数 → 退回盘面最多色 %s" % t
    t = max(strict, key=lambda x: (strict.get(x, 0), board.get(x, 0)))
    return t, ("空手：%s 有 %d 步可做严格多数（盘面 %d 颗，候选中最多）"
               % (t, strict[t], board.get(t, 0)))


def get_last_target():
    """返回上一次 rank_moves_poker 用的目标花色（给日志用）。"""
    return _LAST_TARGET[0]


def get_last_why():
    """返回上一次为什么选这个目标色（给日志用）。"""
    return _LAST_WHY[0]


def rank_moves_poker(g, hand=None, target=None, w_target=6.0, w_score=1.0,
                     w_special=8.0, w_pot=2.0, topk=0):
    """牌局模式打分。

    hand   : poker.read_hand() 的结果（list of 花色字符，'?' 是空位）
    target : 目标花色；给了就用它，否则按 _pick_target 推断

    返回按分数降序的列表，每项：
      (score, total, cleared, casc, spec, (i,j), (i2,j2), final, t_hit, t_dom,
       t_strict)
    """
    # ── 第一遍：枚举所有合法交换（目标色的选择依赖这一步的结果）──
    moves = []
    for i in range(8):
        for j in range(8):
            for (i2, j2) in ((i, j + 1), (i + 1, j)):
                if i2 > 7 or j2 > 7:
                    continue
                a, b = g[i][j], g[i2][j2]
                if a in ("?", None) or b in ("?", None):
                    continue
                is_cube = (a == "S" or b == "S")
                if not is_cube and a == b:
                    continue
                sim = solver_pro.simulate(g, i, j, i2, j2)
                if sim is None:
                    continue
                total, casc, first_cells, first_runs, spec, final = sim
                if total <= 0:
                    continue
                moves.append((sim, _colors_in_move(g, sim), i, j, i2, j2, is_cube))

    if not moves:
        _LAST_TARGET[0] = None
        _LAST_WHY[0] = "无合法交换"
        return []

    # ── 决定目标色 ──
    if target:
        tgt, why = target, "调用方指定"
    else:
        tgt, why = _pick_target(g, hand, moves)
    _LAST_TARGET[0] = tgt
    _LAST_WHY[0] = why

    # ── 第二遍：打分 ──
    out = []
    for (sim, colcnt, i, j, i2, j2, is_cube) in moves:
        total, casc, first_cells, first_runs, spec, final = sim
        t_hit = colcnt.get(tgt, 0) if tgt else 0
        t_dom = 1 if _is_majority(colcnt, tgt) else 0
        t_strict = 1 if _is_strict_majority(colcnt, tgt) else 0
        cleared = len(set(first_cells))
        cube_bonus = 1 if is_cube else 0

        # ★★ 策略核心（2026-09-24 实证规则 + 2026-09-26 严格多数）★★
        #
        # 一次消除给【一张】牌，花色 = 这次消除的【多数色】。
        # 手牌满 5 张自动结算，玩家无法选择"打不打"，
        # 唯一能控制的就是"让哪种颜色成为多数色"。
        # 同花 50000 分且永不生成骷髅 ⇒ 唯一目标就是尽快凑同花。
        #
        # ★ 2026-09-26：并列多数与严格多数分开。消 1G+1R 时游戏给哪色未知，
        #   不能和"消 3G+1R"（必定 G）同等对待。
        base = SC_STRICT if t_strict else (SC_TIE if t_dom else 0.0)
        if t_dom:
            score = (base
                     + 100.0 * t_hit
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
                    final, t_hit, t_dom, t_strict))
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
    for hand in (["G", "G", "?", "?", "?"], ["G", "R", "?", "?", "?"],
                 ["?", "?", "?", "?", "?"]):
        r = rank_moves_poker(g, hand=hand, topk=3)
        print("手牌 %s  目标色=%s" % ("".join(hand), get_last_target()))
        print("   理由: %s" % get_last_why())
        for t in r:
            print("     分=%.0f 直接得分=%-4d 消目标色=%-2d 多数=%d %s<->%s"
                  % (t[0], t[1], t[8], t[9], t[5], t[6]))
