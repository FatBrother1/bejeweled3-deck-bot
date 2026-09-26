#!/usr/bin/env python3
"""Bejeweled 3 决策器（增强版 v2）：级联模拟 + 真实计分 + ★超立方体支持。

★★ 关键修正（实测事故）★★
  原版没有实现「超立方体(S) 可与任意宝石交换引爆」这条规则 ⇒
  一旦棋盘上有超立方体且其余走法耗尽，solver 会报 0 候选 ⇒ bot 卡死 1 分钟以上。
  实测样本 stuck.png：(4,3) 是超立方体，solver 候选=0，但游戏里明明有解法。

  规则：S 与相邻任意宝石交换 ⇒ 消除该颜色的**全部**宝石（超立方体效果）。
  这里保守建模：S 换 X ⇒ 消掉所有 X + S 本身，计其分数，并继续级联。
"""
import random
from itertools import product

GLYPHS = "RPGWOYB"
BASE_PTS = {3: 50, 4: 100, 5: 200, 6: 300, 7: 400}
def base_pts(n):
    return 500 if n >= 8 else BASE_PTS.get(n, 0)

def same(a, b):
    """连线判定：'S' 不参与普通连线。'D'=钻石矿泥土，同样不可消。"""
    if a in ("?", None) or b in ("?", None): return False
    if a == "S" or b == "S": return False
    if a == "D" or b == "D": return False
    return a == b

def find_matches(g):
    hit = set(); runs = []
    for i in range(8):
        j = 0
        while j < 8:
            k = j
            while k + 1 < 8 and same(g[i][k + 1], g[i][j]): k += 1
            n = k - j + 1
            if n >= 3 and g[i][j] not in ("?", None, "S"):
                c = [(i, x) for x in range(j, k + 1)]
                runs.append((c, n)); hit.update(c)
            j = k + 1
    for j in range(8):
        i = 0
        while i < 8:
            k = i
            while k + 1 < 8 and same(g[k + 1][j], g[i][j]): k += 1
            n = k - i + 1
            if n >= 3 and g[i][j] not in ("?", None, "S"):
                c = [(x, j) for x in range(i, k + 1)]
                runs.append((c, n)); hit.update(c)
            i = k + 1
    return hit, runs

def collapse(g):
    new = [["?"] * 8 for _ in range(8)]
    n_unk = 0
    for j in range(8):
        col = [g[i][j] for i in range(8) if g[i][j] is not None]
        k = len(col); n_unk += (8 - k)
        for i in range(8 - k, 8):
            new[i][j] = col[i - (8 - k)]
    return new, n_unk

def collapse_f(g, fl):
    """和 collapse 一样，但让 flags 跟着宝石一起下落（顶部补的 '?' 没有 flags）。

    ★ 为什么必须带着 flags 下落：火焰/闪电宝石掉到新位置后效果还在。
      不带的话，级联到第二层就会拿"旧位置的状态位"去判引爆范围，纯属乱算。
    """
    new = [["?"] * 8 for _ in range(8)]
    nfl = {}
    for j in range(8):
        col = [(g[i][j], fl.get((i, j), 0)) for i in range(8) if g[i][j] is not None]
        k = len(col)
        for i in range(8 - k, 8):
            g_, f_ = col[i - (8 - k)]
            new[i][j] = g_
            if f_:
                nfl[(i, j)] = f_
    return new, nfl

def expand_specials(hit, fl):
    """把"本轮被消掉的格子"按特殊宝石的效果展开（2026-09-26 新增）。

    规则（Bejeweled 3；状态位见 reader_mem：火焰1 超立方2 闪电4 超新星5）：
      火焰(1)   → 炸自己周围 3×3
      闪电(4)   → 清掉自己所在的整行 + 整列
      超新星(5) → 1|4，两者叠加
    被炸到的格子里若还有特殊宝石，继续引爆（链式），最多 64 格必收敛。

    ★ 超立方(2) 被炸到时游戏里怎么算我没实测过 —— 保守当普通宝石，不展开、不猜。
    """
    if not fl:
        return set(hit)
    out = set(hit)
    while True:
        add = set()
        for (a, b) in out:
            f = fl.get((a, b), 0)
            if f & 1:
                for da in (-1, 0, 1):
                    for db in (-1, 0, 1):
                        x, y = a + da, b + db
                        if 0 <= x < 8 and 0 <= y < 8:
                            add.add((x, y))
            if f & 4:
                for x in range(8):
                    add.add((x, b))
                    add.add((a, x))
        new = add - out
        if not new:
            return out
        out |= new

def simulate(g, i, j, i2, j2, max_cascade=12, stop_on_unknown=True, flags=None):
    """模拟一次交换的完整级联。
       ★ 支持超立方体：若交换的一方是 'S'，则消除另一方颜色的全部宝石。
       ★ flags（2026-09-26 新增）：{(行,列): 状态位}，来自 reader_mem 的
         extra["flags"]。给了就模拟火焰/闪电/超新星的引爆范围；不给（None/空）
         则行为与从前逐字节一致 —— 这是可回滚、可 A/B 的前提。"""
    grid = [row[:] for row in g]
    fl = dict(flags) if flags else None
    a0, b0 = grid[i][j], grid[i2][j2]
    grid[i][j], grid[i2][j2] = b0, a0
    if fl is not None:
        # 状态位跟着交换走
        fa, fb = fl.get((i, j), 0), fl.get((i2, j2), 0)
        fl.pop((i, j), None); fl.pop((i2, j2), None)
        if fa: fl[(i2, j2)] = fa
        if fb: fl[(i, j)] = fb
    total = 0; casc = 0; specials = 0
    first_cells = []; first_runs = []
    final = grid
    # ★ 超立方体引爆（首层）
    if "S" in (a0, b0):
        target = b0 if a0 == "S" else a0
        if target not in ("S", "?", None):
            cells = [(r, c) for r in range(8) for c in range(8)
                     if grid[r][c] == target]
            cells += [(r, c) for r in range(8) for c in range(8) if grid[r][c] == "S"]
            cells = list(dict.fromkeys(cells))
            if cells:
                casc = 1
                total += base_pts(max(3, len(cells))) if len(cells) >= 3 else 50*len(cells)//3
                specials += 3
                first_cells = cells
                first_runs = [len(cells)]
                for a, b in cells:
                    grid[a][b] = None
                    if fl is not None: fl.pop((a, b), None)
                if fl is not None:
                    grid, fl = collapse_f(grid, fl)
                else:
                    grid, _ = collapse(grid)
                final = grid
    while casc < max_cascade:
        hit, runs = find_matches(grid)
        if not hit: break
        if stop_on_unknown and any(grid[a][b] in ("?", None) for a, b in hit):
            break
        casc += 1
        step = 0
        for cells, n in runs:
            step += base_pts(n)
            if n == 4: specials += 1
            elif n >= 5: specials += 3
        total += step * casc
        # ★ 特殊宝石展开：火焰炸 3×3、闪电清整行整列、超新星叠加、链式引爆
        blast = expand_specials(hit, fl) if fl is not None else hit
        if not first_cells:
            base = [c for cells, _ in runs for c in cells]
            if fl is not None:
                seen = set(base)
                first_cells = base + [c for c in sorted(blast) if c not in seen]
            else:
                first_cells = base
            first_runs = [n for _, n in runs]
        for a, b in blast:
            grid[a][b] = None
            if fl is not None: fl.pop((a, b), None)
        if fl is not None:
            grid, fl = collapse_f(grid, fl)
        else:
            grid, _ = collapse(grid)
        final = grid
    return total, casc, first_cells, first_runs, specials, final

def potential(g):
    n = 0
    ok = lambda c: c not in ("?", None, "S")
    for i in range(8):
        for j in range(6):
            a, b, c = g[i][j], g[i][j+1], g[i][j+2]
            if ok(a) and a == b and c != a: n += 1
            if ok(a) and a == c and b != a: n += 1
    for j in range(8):
        for i in range(6):
            a, b, c = g[i][j], g[i+1][j], g[i+2][j]
            if ok(a) and a == b and c != a: n += 1
            if ok(a) and a == c and b != a: n += 1
    return n

def rank_moves(g, w_special=8.0, w_row=2.0, w_pot=2.0, topk=0, timegems=None,
               banned=None, flags=None, butterflies=None):
    """给所有走法打分。

    timegems: [(行, 列, 计数), ...] —— 闪电模式的时间宝石位置。
      ★ 有它时必须优先去消：闪电模式是限时的，不拿时间宝石就等着时间耗尽。
        实测（2026-09-25）时间宝石的标记是 flags & 131072、计数在 +0x244。
        没有这个参数时行为与从前完全一致（不影响其它模式）。
    butterflies: [(行, 列), ...] —— 蝴蝶模式的蝴蝶宝石位置（状态位 128）。
      ★ 蝴蝶飞到顶行就结束，所以"这一步能消掉蝴蝶"的招要压倒性优先，
        并按 (8-行号) 加紧急度（越靠上越急）。不传时行为与从前完全一致。
    banned: set(frozenset({(i1,j1),(i2,j2)})) —— 已被游戏拒绝过的走法。
      ★ 棋盘没变时被拒的招必然再被拒（求解是确定性的），直接跳过，
        否则 bot 会反复出同一招（实测 #145~#149 连续 5 步同一招全被拒）。
        棋盘一变（任何有效步）由 bot 负责清空。
    """
    tg = set((i, j) for i, j, _ in (timegems or []))
    bf = set(butterflies or ())
    ban = banned or set()
    # ★ 钻石矿（2026-09-25，用户纠偏）：目标 = 往下挖，越深越好。
    #   泥破了画面自动下移，金子只是顺带的分数 —— 所以一切以挖泥为准：
    #   贴泥的招加权，且挖得越深（泥格行号越大）权重越高。
    has_dirt = any("D" in row for row in g)
    w_dig = 300.0
    out = []
    for i in range(8):
        for j in range(8):
            for di, dj in ((0, 1), (1, 0)):
                i2, j2 = i + di, j + dj
                if i2 > 7 or j2 > 7: continue
                if frozenset(((i, j), (i2, j2))) in ban: continue
                a, b = g[i][j], g[i2][j2]
                # 'D'=钻石矿泥土：游戏不允许交换泥块，直接跳过
                if a in ("?", "D", None) or b in ("?", "D", None): continue
                if a == b: continue
                total, casc, cells, runs, spec, fg = simulate(g, i, j, i2, j2,
                                                             flags=flags)
                if total <= 0: continue
                cleared = len(set(cells))
                avg_row = (sum(r for r, _ in cells) / len(cells)) if cells else 0.0
                pot = potential(fg)
                score = total + w_special * spec + w_row * avg_row + w_pot * pot
                if has_dirt:
                    digs = 0.0
                    for (ci, cj) in set(cells):
                        for di, dj in ((0, 1), (0, -1), (1, 0), (-1, 0)):
                            ni, nj = ci + di, cj + dj
                            if 0 <= ni < 8 and 0 <= nj < 8 and g[ni][nj] == "D":
                                # 深度缩放：越深的泥（行号越大）越值钱，引导 bot
                                # 永远朝泥墙最深处下手
                                digs += 1.0 + ni / 7.0
                    score += w_dig * digs
                # ★ 闪电模式：这一步吃掉几个时间宝石，每个给巨额加权。
                #   权重远大于普通得分 —— 时间比分数重要。
                if tg:
                    t_hit = sum(1 for c in set(cells) if c in tg)
                    if t_hit:
                        score += 100000.0 * t_hit
                # ★ 蝴蝶模式（2026-09-26）：蝴蝶飞到顶行就结束，所以"能消掉蝴蝶"的招
                #   必须压倒性优先，而且越靠上越急 —— 用 (8-行号) 当紧急度：
                #   贴顶行(row=1)的一只 = 700000，最底下(row=7) = 100000。
                #   消两只就叠加。权重远大于普通得分，跟时间宝石一个量级。
                if bf:
                    b_hit = [c for c in set(cells) if c in bf]
                    if b_hit:
                        score += 100000.0 * sum(8 - r for r, _ in b_hit)
                out.append((score, total, cleared, casc, spec, pot,
                            (i, j), (i2, j2), fg, runs))
    out.sort(key=lambda x: -x[0])
    return out[:topk] if topk else out

def best_move(g, **kw):
    r = rank_moves(g, **kw)
    if not r: return None
    t = r[0]
    return (t[1], t[2], t[6], t[7])

if __name__ == "__main__":
    import time, random
    random.seed(7)
    b = [[random.choice(GLYPHS) for _ in range(8)] for _ in range(8)]
    t0 = time.time(); r = rank_moves(b); el = time.time() - t0
    print("普通局面: 候选 %d, 耗时 %.1f ms" % (len(r), el*1000))
    # 构造只有超立方体可解的局面
    b2 = [["W","G","R","O","B","Y","R","W"],
          ["P","B","R","O","Y","O","R","Y"],
          ["R","Y","Y","P","B","O","Y","B"],
          ["W","R","P","P","Y","W","W","B"],
          ["G","W","G","S","G","B","G","Y"],
          ["G","R","Y","O","R","W","R","O"],
          ["O","Y","W","O","G","P","G","Y"],
          ["Y","W","P","R","W","O","O","G"]]
    r2 = rank_moves(b2)
    print("超立方体局面: 候选 %d" % len(r2))
    for x in r2[:5]:
        print("   score=%.1f 分=%d 消%d格 %s<->%s" % (x[0], x[1], x[2], x[6], x[7]))
