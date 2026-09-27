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
    """连线判定：'S' 不参与普通连线。"""
    if a in ("?", None) or b in ("?", None): return False
    if a == "S" or b == "S": return False
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

def simulate(g, i, j, i2, j2, max_cascade=12, stop_on_unknown=True):
    """模拟一次交换的完整级联。
       ★ 支持超立方体：若交换的一方是 'S'，则消除另一方颜色的全部宝石。"""
    grid = [row[:] for row in g]
    a0, b0 = grid[i][j], grid[i2][j2]
    grid[i][j], grid[i2][j2] = b0, a0
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
                for a, b in cells: grid[a][b] = None
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
        if not first_cells:
            first_cells = [c for cells, _ in runs for c in cells]
            first_runs = [n for _, n in runs]
        for a, b in hit: grid[a][b] = None
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

def rank_moves(g, w_special=8.0, w_row=2.0, w_pot=2.0, topk=0):
    out = []
    for i in range(8):
        for j in range(8):
            for di, dj in ((0, 1), (1, 0)):
                i2, j2 = i + di, j + dj
                if i2 > 7 or j2 > 7: continue
                a, b = g[i][j], g[i2][j2]
                if a in ("?", None) or b in ("?", None): continue
                if a == b: continue
                total, casc, cells, runs, spec, fg = simulate(g, i, j, i2, j2)
                if total <= 0: continue
                cleared = len(set(cells))
                avg_row = (sum(r for r, _ in cells) / len(cells)) if cells else 0.0
                pot = potential(fg)
                score = total + w_special * spec + w_row * avg_row + w_pot * pot
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
