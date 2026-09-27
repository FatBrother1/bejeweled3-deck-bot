#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""牌局模式「牌型阶梯」—— 离线验证（2026-09-27 重写）

覆盖：
  A. best_plan：同花→四条→葫芦→三条→两对→散牌→一对，逐档可达性
  B. flush_state：已翻开一混色，同花就死了（第 17 轮的结论）
  C. 目标色：同花活着必锁该色；`GRBY?` 必追手里没有的颜色（散牌 5000）
  D. 排序主键：拿得到目标色的那批**全部**排在拿不到的前面
  E. 保住供给：拿不到目标色时优先消【别的】颜色（旧代码反过来奖励消目标色）
  F. 空手：目标色 = 能做出严格多数最多的那个色
  G. 返回结构不变（bot_v6 依赖 t[1]/t[5]/t[6]/t[8]）
  H. 随机压力：200 盘 × 4 手牌不崩、不返回坏值

跑法：`python3 test_poker.py`（纯 Python，不需要 numpy）。
"""
import random
import sys

import poker
import solver_poker as SP
import solver_pro

PASS, FAIL = [], []
GL = "RGOYBPW"


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(("  ✓ " if cond else "  ✗ ") + name + ("" if cond else "   ← " + str(detail)))


def rnd_board(seed):
    rng = random.Random(seed)
    return [[rng.choice(GL) for _ in range(8)] for _ in range(8)]


def move_cards(g, t):
    """这一步会拿到哪种花色的牌（自己按 simulate 重算，不用实现里的私有函数）。"""
    sim = solver_pro.simulate(g, t[5][0], t[5][1], t[6][0], t[6][1])
    if sim is None:
        return []
    cnt = {}
    for (r, c) in sim[2]:
        cnt[g[r][c]] = cnt.get(g[r][c], 0) + 1
    if not cnt:
        return []
    top = max(cnt.values())
    return sorted(c for c, n in cnt.items() if n == top)


def strict_colors(g, t):
    """这一步能做出【严格】多数的颜色（并列则空）。"""
    c = move_cards(g, t)
    if not c:
        return []
    sim = solver_pro.simulate(g, t[5][0], t[5][1], t[6][0], t[6][1])
    cnt = {}
    for (r, cc) in sim[2]:
        cnt[g[r][cc]] = cnt.get(g[r][cc], 0) + 1
    order = sorted(cnt.values(), reverse=True)
    if len(order) == 1 or order[0] > order[1]:
        return [c[0]]
    return []


print("A. best_plan —— 还能做到的最高牌型（用户要的阶梯）")
cases = [
    (["?", "?", "?", "?", "?"], ("同花", 50000, 5, []), "空手：同花还活着、还没定色"),
    (["G", "?", "?", "?", "?"], ("同花", 50000, 4, ["G"]), "1 张 → 锁 G，还差 4"),
    (["G", "G", "G", "G", "?"], ("同花", 50000, 1, ["G"]), "4 张 → 还差 1（同花优先）"),
    (["G", "G", "G", "R", "?"], ("四条", 30000, 1, ["G"]), "3+1 → 四条差 1（压过葫芦）"),
    (["G", "G", "R", "R", "?"], ("葫芦", 15000, 1, ["G", "R"]), "2+2 → 葫芦差 1"),
    (["G", "G", "R", "B", "?"], ("三条", 10000, 1, ["G"]), "2+1+1 → 三条差 1"),
    (["G", "R", "B", "?", "?"], ("三条", 10000, 2, ["G", "R", "B"]), "1+1+1 → 三条差 2"),
    (["G", "R", "B", "Y", "?"], ("散牌", 5000, 1, ["O", "P", "W"]),
     "1+1+1+1 → 散牌，追手里没有的颜色"),
    (["G", "G", "R", "R", "B"], ("两对", 7500, 0, []), "满 5 张：两对"),
    (["G", "G", "G", "G", "R"], ("四条", 30000, 0, []), "满 5 张：四条"),
    (["G", "R", "B", "Y", "W"], ("散牌", 5000, 0, []), "满 5 张：散牌"),
]
for hand, want, label in cases:
    got = poker.best_plan(hand)
    check("%s  %s → %s" % (label, "".join(hand), got[0]), got == want, "期望 %s" % (want,))
check("2+1+1 空 2 位 → 四条差 2（不是葫芦）",
      poker.best_plan(["G", "G", "R", "?", "?"]) == ("四条", 30000, 2, ["G"]),
      poker.best_plan(["G", "G", "R", "?", "?"]))
check("阶梯顺序就是游戏分值表从高到低",
      [v for _, v in poker.RANK_LADDER] == [50000, 30000, 15000, 10000, 7500, 5000, 2500],
      poker.RANK_LADDER)

print("\nB. flush_state —— 同花还活着吗")
for hand, want, label in [
    (["?", "?", "?", "?", "?"], (True, None, 5), "空手"),
    (["G", "?", "?", "?", "?"], (True, "G", 4), "1 张 G"),
    (["G", "G", "G", "G", "?"], (True, "G", 1), "4 张 G，还差 1"),
    (["G", "R", "?", "?", "?"], (False, None, 0), "混色 ⇒ 同花已死"),
    (["G", "R", "G", "O", "O"], (False, None, 0), "混色（实测出现过的手牌）"),
]:
    got = poker.flush_state(hand)
    check("%s  %s → %s" % (label, "".join(hand), got), got == want, "期望 %s" % (want,))

print("\nC. 目标色")
for hand, want in ((["G", "G", "?", "?", "?"], "G"),
                   (["B", "?", "?", "?", "?"], "B"),
                   (["W", "W", "W", "?", "?"], "W"),
                   (["G", "G", "G", "G", "?"], "G")):
    SP.rank_moves_poker(rnd_board(7), hand=hand, topk=3)
    got = SP.get_last_target()
    check("同花活 %s → 锁定 %s" % ("".join(hand), got), got == want, "期望 %s" % want)

# C2：GRBY? 必须去拿手里没有的颜色（散牌 5000 > 一对 2500）
qual = 0
bad = []
for seed in range(30):
    gb = rnd_board(seed)
    rk = SP.rank_moves_poker(gb, hand=["G", "R", "B", "Y", "?"], topk=0)
    if not rk:
        continue
    has_new = any(all(c not in "GRBY" for c in move_cards(gb, x)) for x in rk)
    if not has_new:
        continue          # 这盘根本没有能产出新颜色的招，退回一对是对的
    qual += 1
    if not all(c not in "GRBY" for c in move_cards(gb, rk[0])):
        bad.append(seed)
check("GRBY? → 有『新颜色』招时必定拿它凑散牌（%d 个可比盘面）" % qual,
      qual >= 5 and not bad, "反例 seed=%s" % bad)

print("\nD. 排序主键：拿得到目标色的那批全排在前面")
viol = 0
for seed in range(40):
    gb = rnd_board(seed)
    rk = SP.rank_moves_poker(gb, hand=["G", "G", "?", "?", "?"], topk=0)
    seen_no = False
    for x in rk:
        if x[9]:                      # t[9] = 这一步让目标色 G 成为多数色
            if seen_no:
                viol += 1
                break
        else:
            seen_no = True
check("手牌 GG???：40 盘里『拿到 G 的招排在没拿到 G 的后面』0 次", viol == 0,
      "违规 %d" % viol)

print("\nE. 保住供给：拿不到目标色时别烧目标色")
# E1 确定性回归：seed=7 是旧代码的现场（旧第一名一次消掉 4 颗 G）
g7 = rnd_board(7)
rk7 = SP.rank_moves_poker(g7, hand=["G", "G", "?", "?", "?"], topk=0)
check("seed=7 第一名消掉的 G 是 0 颗（旧代码：4 颗，全部候选里最多）",
      rk7[0][8] == 0, "t_hit=%d" % rk7[0][8])
check("seed=7 日志三栏自洽（目标色=G、消目标色=0、多数=0）",
      SP.get_last_target() == "G" and rk7[0][8] == 0 and rk7[0][9] == 0,
      (SP.get_last_target(), rk7[0][8], rk7[0][9]))

# E2 统计：400 个"拿不到 G 牌"的盘面里，只在【真有取舍】的盘面上看
#     （所有候选消的 G 一样多 = 没得选，不算）
few, many, real = 0, 0, 0
for seed in range(400):
    gb = rnd_board(seed)
    rk = SP.rank_moves_poker(gb, hand=["G", "G", "?", "?", "?"], topk=0)
    if not rk:
        continue
    if any("G" in move_cards(gb, x) for x in rk):
        continue                      # 这盘拿得到 G 牌，不属本组
    allg = [x[8] for x in rk]         # t[8] = 这一步消掉几颗目标色 G
    if max(allg) == min(allg):
        continue                      # 没得选
    real += 1
    if rk[0][8] == min(allg):
        few += 1
    elif rk[0][8] == max(allg):
        many += 1
check("拿不到 G 的盘面里真有取舍的 %d 个：第一名挑『消 G 最少』%d 个、"
      "『最多』%d 个（旧代码必挑最多）" % (real, few, many),
      real > 50 and few >= 0.75 * real and many <= 0.10 * real,
      "最少/最多 = %d/%d" % (few, many))

print("\nF. 空手：目标色 = 能做出严格多数最多的色")
ok = True
for seed in range(20):
    gb = rnd_board(seed)
    rk = SP.rank_moves_poker(gb, hand=["?", "?", "?", "?", "?"], topk=0)
    if not rk:
        continue
    cnt = {}
    for x in rk:
        for c in strict_colors(gb, x):
            cnt[c] = cnt.get(c, 0) + 1
    if not cnt:
        continue
    best = max(cnt.values())
    if cnt.get(SP.get_last_target(), 0) != best:
        ok = False
        print("     反例 seed=%d 目标=%s（严格多数步数 %d，最多 %d）"
              % (seed, SP.get_last_target(), cnt.get(SP.get_last_target(), 0), best))
check("空手 → 目标是『严格多数步数最多』的那个色（20 盘）", ok)

print("\nG. 返回结构不变（bot_v6 依赖这些下标）")
gb = rnd_board(3)
rk = SP.rank_moves_poker(gb, hand=["G", "?", "?", "?", "?"], topk=5)
check("有返回", len(rk) > 0, len(rk))
check("元组 11 项", all(len(x) == 11 for x in rk), [len(x) for x in rk])
check("t[0]=牌型分值 是数", isinstance(rk[0][0], (int, float)), type(rk[0][0]))
check("t[1]=直接得分 是 int", isinstance(rk[0][1], int), type(rk[0][1]))
check("t[5]/t[6] 是两个格子坐标",
      isinstance(rk[0][5], tuple) and isinstance(rk[0][6], tuple), rk[0][5:7])
check("t[8]=消目标色 是 int", isinstance(rk[0][8], int), type(rk[0][8]))
check("t[9]=多数 是 0/1", rk[0][9] in (0, 1), rk[0][9])
check("t[10]=严格多数 是 0/1", rk[0][10] in (0, 1), rk[0][10])
check("t[0] 随排序不增", all(rk[i][0] >= rk[i + 1][0] for i in range(len(rk) - 1)))
check("t[0] 是阶梯上的分值",
      all(x[0] in (2500, 5000, 7500, 10000, 15000, 30000, 50000) for x in rk),
      sorted(set(x[0] for x in rk)))
bm = SP.best_move_poker(gb, hand=["G", "?", "?", "?", "?"])
check("best_move_poker 返回 4 元组", bm is not None and len(bm) == 4, bm)

print("\nH. 随机压力（200 盘 × 4 手牌）")
bad = 0
for seed in range(200):
    gb = rnd_board(seed)
    for hand in (["?", "?", "?", "?", "?"], ["G", "R", "?", "?", "?"],
                 ["G", "G", "G", "?", "?"], ["G", "R", "B", "Y", "?"]):
        try:
            rk = SP.rank_moves_poker(gb, hand=hand)
            t = SP.get_last_target()
            if t is not None and t not in GL:
                bad += 1
            for x in rk:
                if not isinstance(x[0], (int, float)):
                    bad += 1
                if len(x) != 11:
                    bad += 1
        except Exception as e:
            bad += 1
            print("     异常 seed=%d hand=%s: %s" % (seed, "".join(hand), e))
check("200 盘 × 4 手牌 无异常无坏值", bad == 0, "坏值 %d" % bad)

print("\n" + "=" * 60)
print("通过 %d / 失败 %d" % (len(PASS), len(FAIL)))
if FAIL:
    print("失败项: " + ", ".join(FAIL))
sys.exit(1 if FAIL else 0)
