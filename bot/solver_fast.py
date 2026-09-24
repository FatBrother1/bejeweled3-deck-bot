#!/usr/bin/env python3
"""Bejeweled 3 决策器（快速版）：枚举全部相邻交换，取消除数最大者。

移植 megajewel 的 AllBestFastStrategy 思路（全盘 8x8 枚举，非贪心单点），
并加入：'S'（道具）作万能宝石处理、对 4/5 连消给额外权重。
"""
from itertools import product

def same(a, b):
    """连线判定：是否同色。
    注意 'S'（道具/超立方体）**不参与连线** —— 它靠在旁边不会自动消除，
    只有被交换时才引爆。若让它参与连线会凭空造出三连（实测踩过：
    超立方体被误读成白宝石，造出"四连白"，bot 以为棋盘没结算而死等）。"""
    if a == "?" or b == "?" or a == "S" or b == "S": return False
    return a == b

def find_matches(g):
    """返回 (被消除的格子集合, 连消长度列表)。"""
    hit = set(); runs = []
    for i in range(8):
        j = 0
        while j < 8:
            k = j
            while k + 1 < 8 and same(g[i][k + 1], g[i][j]): k += 1
            n = k - j + 1
            if n >= 3 and g[i][j] != "?":
                runs.append(n)
                for x in range(j, k + 1): hit.add((i, x))
            j = k + 1
    for j in range(8):
        i = 0
        while i < 8:
            k = i
            while k + 1 < 8 and same(g[k + 1][j], g[i][j]): k += 1
            n = k - i + 1
            if n >= 3 and g[i][j] != "?":
                runs.append(n)
                for x in range(i, k + 1): hit.add((x, j))
            i = k + 1
    return hit, runs

def score_grid(g):
    hit, runs = find_matches(g)
    if not hit: return 0, 0
    # 4 连/5 连会生成道具，额外加权
    bonus = sum(3 for n in runs if n >= 5) + sum(1 for n in runs if n == 4)
    return len(hit) + bonus, len(hit)

def best_move(g):
    """返回 (score, cleared, (i1,j1), (i2,j2))，无解返回 None。"""
    best = None
    for i in range(8):
        for j in range(8):
            for di, dj in ((0, 1), (1, 0)):
                i2, j2 = i + di, j + dj
                if i2 > 7 or j2 > 7: continue
                a, b = g[i][j], g[i2][j2]
                if a == "?" or b == "?": continue
                if a == b: continue               # 同色交换无意义
                # 'S'（超立方体）可与任意宝石交换并引爆 -> 允许
                g[i][j], g[i2][j2] = b, a
                sc, cleared = score_grid(g)
                g[i][j], g[i2][j2] = a, b
                if sc <= 0: continue
                if best is None or (sc, cleared) > best[:2]:
                    best = (sc, cleared, (i, j), (i2, j2))
    return best
