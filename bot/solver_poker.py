#!/usr/bin/env python3
"""牌局模式求解器：优先凑同花，凑不出就按牌型阶梯往下走。

## 和普通模式的根本区别

普通模式：每次消除都给分，所以追求"每一步分最高"。
牌局模式：**只有集齐 5 张牌才给分**，消得多但花色杂 = 白消。

⇒ 所以这里的打分**完全不看"这一步消了多少颗宝石"**（那是"求快"），
  只看"这一步拿到的那张牌，让手牌离哪个牌型更近"。

## 手牌是【从左往右填】的（2026-09-26 同步抓帧实证）

实测序列（bot 打、另一个进程在手牌变化时存帧）：

    G???? → GG??? → GR??? → GRR?? → GRG?? → GRGG? → GRGOR → GRGOO（结算）
    ????? → （新一手，重新从左边填）

⇒ `?` 是【还没拿到的空位】，不是暗牌；已翻开的永远是一段前缀。

**推论**：同花要 5 张同色 ⇒ **已翻开里一出现第二种颜色，这手同花就已经死了**。
原来的 `best_flush_color` 只看"谁多"，`GRGO?` 还在追 G —— 追一个数学上已经
不可能的目标。

## 出牌规则（2026-09-24 实测，wiki 未写明）

**一次消除给一张牌，花色 = 这次消除的「多数色」。**

⇒ 不是"消到目标色"就行，**必须让目标色成为多数色**。
⇒ 进一步：**并列多数是不保险的**（消 1G+1R，游戏给哪色未知）。

## 目标 = 牌型阶梯（2026-09-27 重写）

用户要的优先级：**同花 → 四条 → 葫芦 → 三条 → 两对 → 顺子 → 一对**。
阶梯本身和"还差几张"都由 `poker.best_plan(hand)` 算（纯 Python、离线可测）。

每一步的打分键是**字典序**（越靠前越优先）：

    1. 这张牌到手之后，手牌还能做到的最高牌型分值   ← poker.best_plan
    2. 凑成它还差几张（越少越好）
    3. 这张牌是不是当前计划要的花色
    4. 这一步之后盘上还剩多少颗"计划要的花色"（保住供给，下一张还要它）
    5. 并列多数扣一点（游戏给哪色未知 = 不保险）
    6. 特殊宝石、魔方（只在前面全平时起作用）

旧打分（2026-09-26）是 `2600/1800 + 100×消目标色 + 1×总得分 + 2×潜力 + 30×魔方`
—— **消得越多排越前**。实测两处明显偏离用户要的优先级（离线复现，见
`test_poker.py` 的回归组）：

  · **拿不到目标色的那一步，它奖励"消掉更多目标色"**（`10×t_hit`）。
    这一步本来就拿不到目标色的牌，却把下一张牌要用的宝石自己烧掉 ——
    400 个随机盘面里 159 个出现，最多的一个盘面一次烧掉 4 颗。
  · **手牌 `GRBY?`（4 张全不同）时，目标色一定落在手里已有的颜色里**
    ⇒ 最多凑「一对 2500」；正确解是拿一张**手里没有的颜色**凑「散牌 5000」。

## 空手时追哪个色

手牌一张没翻开时没有花色信息，`best_plan` 的目标色列表是空的，
这时按**第 17 轮实测出来的规则**选：哪个色"能做出严格多数的步数"最多就选它
（盘面宝石多 ≠ 能凑出多数消除）。

## 分值表

    同花 50000 > 四条 30000 > 葫芦 15000 > 三条 10000
    > 两对 7500 > 顺子 5000 > 一对 2500

同花是第二名的 1.67 倍，而且**永远不会被标骷髅**，所以值得优先追。

## 特殊宝石在牌局里的价值

    火焰牌 +100 分、闪电牌 +250 分、万能牌可当任意花色
"""
import solver_pro

GLYPHS = "RGOYBPW"
_LAST_TARGET = [None]
_LAST_WHY = [None]

# 并列多数的惩罚。只在前四项全平时起作用，量级远小于最小的牌型分差
# （一对 2500 → 散牌 5000）。
UNCERTAIN_PENALTY = 1


def _colors_in_move(g, sim_result, swap=None):
    """算出这一步会消掉哪些颜色的宝石，各多少个。

    sim_result 是 solver_pro.simulate 的返回值，
    其中 first_cells 是首层消除的格子坐标列表。

    ★ 2026-09-27 修：必须**在交换后的棋盘上**读 ★
      原来直接在传入的 g（= 交换前的棋盘）上读 first_cells 的颜色，而被交换的
      那两格恰好总在首层消除里 ⇒ 它们的颜色读到的是**换过去之前**那一颗 ⇒
      多数色判错。实测 400 随机盘、31,757 个合法交换：**5.16% 估错**，
      而且错的全是同一个方向 —— 把「并列多数」读成「严格多数」
      （样本：求解器判 R 严格多数、真实是 R/W 并列）。
      牌的花色由多数色决定，并列时游戏给哪色未知 ⇒ 高估确定性会让计划去追
      一个可能拿不到的颜色，日志里的 `★严格多数` 标记也跟着失真。
    """
    total, casc, first_cells, first_runs, specials, final = sim_result
    gg = g
    if swap is not None:
        (i, j), (i2, j2) = swap
        gg = [row[:] for row in g]
        gg[i][j], gg[i2][j2] = gg[i2][j2], gg[i][j]
    cnt = {}
    for (r, c) in first_cells:
        ch = gg[r][c] if 0 <= r < 8 and 0 <= c < 8 else None
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


def _cards_of(colcnt):
    """这一步会拿到哪种花色的牌 —— 多数色；并列则全部列出（游戏给哪色未知）。"""
    if not colcnt:
        return []
    top = max(colcnt.values())
    if top <= 0:
        return []
    return sorted(c for c, n in colcnt.items() if n == top)


def _plan_after(hand, card):
    """假设下一张牌是 card，这手牌**还能做到**的最好牌型。

    返回 poker.best_plan 的 `(名称, 分值, 还差几张, 目标色列表)`。
    """
    import poker
    h = list(hand or [])
    for k in range(len(h)):
        if h[k] == "?":
            h[k] = card
            return poker.best_plan(h)
    return poker.best_plan(h)          # 手牌已满（游戏马上结算），这张不算数


def _keep(final, tg):
    """这一步之后盘上还剩多少颗"我们还要的花色"。越多越好（下一张还要它）。"""
    n = 0
    for row in final:
        for ch in row:
            if ch in tg:
                n += 1
    return n


def _pin_first_color(g, moves):
    """手牌一张没翻开（花色还没定）时，先用哪个色开局。

    ★ 第 17 轮的规则，原样保留：按"有多少步能把它做成【严格】多数色"选，
      不按盘面宝石数选（盘面多 ≠ 能凑出多数消除）。

    moves: [(sim, colcnt, i, j, i2, j2, is_cube), ...]（已枚举好的合法交换）
    """
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
    if not strict:
        if not board:
            return None, "盘面没有可用颜色"
        t = max(board, key=board.get)
        return t, "没有任何一步能做出严格多数 → 退回盘面最多色 %s" % t
    t = max(strict, key=lambda x: (strict.get(x, 0), board.get(x, 0)))
    return t, ("手牌全空：%s 有 %d 步可做严格多数（盘面 %d 颗，候选中最多）"
               % (t, strict[t], board.get(t, 0)))


def get_last_target():
    """返回上一次 rank_moves_poker 用的目标花色（给日志用）。"""
    return _LAST_TARGET[0]


def get_last_why():
    """返回上一次为什么选这个目标色（给日志用）。"""
    return _LAST_WHY[0]


def rank_moves_poker(g, hand=None, target=None, w_special=8.0, topk=0):
    """牌局模式打分（2026-09-27：改成按牌型阶梯排序）。

    hand   : poker.read_hand() 的结果（list of 花色字符，'?' 是空位）
    target : 目标花色；给了就用它，否则按牌型阶梯推断
    topk   : 只返回前 k 个（0 = 全返回）

    ⚠️ 旧签名里的 `w_target/w_score/w_pot` 已删 —— 那三个权重就是"消得越多
       分越高"的来源，本轮的目标正是**不看消了多少**。没有调用方传它们。

    返回按优先级降序的列表，每项 11 元组（结构没动，bot 依赖 t[1]/t[5]/t[6]/t[8]）：
      (计划分值, total, cleared, casc, spec, (i,j), (i2,j2), final,
       t_hit, t_dom, t_strict)

    t[0] 现在是**"这张牌到手后还能做到的最高牌型分值"**（2500~50000），
    不再是旧的加权总分；它随排序键单调不增。
    """
    import poker
    hand = list(hand) if hand else ["?"] * 5

    # ── 第一遍：枚举所有合法交换 ──
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
                moves.append((sim, _colors_in_move(g, sim, swap=((i, j), (i2, j2))),
                              i, j, i2, j2, is_cube))

    if not moves:
        _LAST_TARGET[0] = None
        _LAST_WHY[0] = "无合法交换"
        return []

    # ── 决定目标色（= 计划要收的花色）──
    plan = poker.best_plan(hand)         # (名称, 分值, 还差几张, 目标色列表)
    if target:
        tgt, why = target, "调用方指定"
    elif plan[3]:
        tgt = plan[3][0]
        why = ("牌型阶梯：这手还能做「%s」→ 追 %s，还差 %d 张"
               % (plan[0], "/".join(plan[3]), plan[2]))
    else:
        # 手牌全空：best_plan 给不出颜色，按"能做出严格多数的步数"定
        tgt, why = _pin_first_color(g, moves)
    _LAST_TARGET[0] = tgt
    _LAST_WHY[0] = why

    # ── 第二遍：按"这张牌到手之后还能做到什么牌型"排序 ──
    rows = []
    tgset = plan[3] or ([tgt] if tgt else [])
    for (sim, colcnt, i, j, i2, j2, is_cube) in moves:
        total, casc, first_cells, first_runs, spec, final = sim
        cards = _cards_of(colcnt)

        if cards:
            infos = [_plan_after(hand, c) for c in cards]
            vals_ = [x[1] for x in infos]
            needs_ = [x[2] for x in infos]
            # 并列多数时游戏给哪色未知 ⇒ 按各可能结果的**平均**算（期望值），
            # 再在键尾扣一点不确定惩罚。
            bi = max(range(len(cards)), key=lambda k: (vals_[k], -needs_[k]))
            best_tg = infos[bi][3] or [cards[bi]]
            val = sum(vals_) / float(len(vals_))
            need = sum(needs_) / float(len(needs_))
        else:
            best_tg = list(tgset)
            val, need = 0.0, 5.0

        hit = 1 if [c for c in cards if c in tgset] else 0
        keep = _keep(final, best_tg)
        unc = UNCERTAIN_PENALTY if len(cards) > 1 else 0

        # 字典序键：牌型 → 还差几张 → 是不是目标色 → 保住供给 → 不确定 → 特殊 → 魔方
        key = (-val, need, -hit, -keep, unc, -w_special * spec,
               0 if is_cube else 1, i, j, i2, j2)
        rows.append((key, val, total, len(set(first_cells)), casc, spec,
                     (i, j), (i2, j2), final, colcnt, cards))

    rows.sort(key=lambda r: r[0])

    # ── 第三遍（只为日志）：目标色按"这一步真正拿到的那张牌"显示 ──
    # 计划的目标色可能不止一个（`GR???` 追 G 或 R 都算数；散牌要的是手里还没有
    # 的颜色）。取第一名实际产出的那个，日志里 `目标色/消目标色/★严格多数`
    # 三栏才自洽；第一名没产出目标色时保留计划里的第一个 —— 那一行正好就是
    # "这一步拿不到目标色"的现场，得看得见。
    win_cards = rows[0][10]
    inter = [c for c in win_cards if c in tgset]
    if inter:
        tgt = inter[0]
        _LAST_TARGET[0] = tgt

    out = []
    for r in rows:
        colcnt = r[9]
        out.append((r[1], r[2], r[3], r[4], r[5], r[6], r[7], r[8],
                    colcnt.get(tgt, 0) if tgt else 0,
                    1 if _is_majority(colcnt, tgt) else 0,
                    1 if _is_strict_majority(colcnt, tgt) else 0))
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
    import poker
    for hand in (["G", "G", "?", "?", "?"], ["G", "R", "?", "?", "?"],
                 ["G", "R", "B", "Y", "?"], ["?", "?", "?", "?", "?"]):
        r = rank_moves_poker(g, hand=hand, topk=3)
        print("手牌 %s  计划=%s  目标色=%s"
              % ("".join(hand), poker.best_plan(hand), get_last_target()))
        print("   理由: %s" % get_last_why())
        for t in r:
            print("     牌型分=%-6.0f 直接得分=%-4d 消目标色=%-2d 多数=%d %s<->%s"
                  % (t[0], t[1], t[8], t[9], t[5], t[6]))
