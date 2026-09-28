#!/usr/bin/env python3
"""2026-09-28 模式优化回归：冰风暴策略 / 蝴蝶造魔方 / 闪电特宝权重 / 双超能对撞。

纪律：rank_moves 新增的三个权重（w_vertical/w_starcol/w_hyper2）默认 0，
不传 = 旧行为逐字节一致 —— A 组就是守这条的。
"""
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import solver_pro
from solver_pro import rank_moves, find_matches

FAIL = []


def check(name, ok, detail=""):
    print("  %s %s %s" % ("✓" if ok else "✗", name, detail))
    if not ok:
        FAIL.append(name)


def swapped(g, i, j, i2, j2):
    s = [r[:] for r in g]
    s[i][j], s[i2][j2] = s[i2][j2], s[i][j]
    return s


def top_is_vertical(g, mv):
    (i1, j1), (i2, j2) = mv
    _, runs = find_matches(swapped(g, i1, j1, i2, j2))
    for cells, _n in runs:
        if len(set(c for _, c in cells)) == 1:
            return True
    return False


# ── A. 默认参数恒等（300 盘随机局面，新旧调用逐项一致） ──────────────
random.seed(20260928)
same_cnt = 0
for t in range(300):
    b = [[random.choice("RPGWOYB") for _ in range(8)] for _ in range(8)]
    a = rank_moves(b)
    c = rank_moves(b, w_vertical=0.0, w_starcol=0.0, w_hyper2=0.0)
    if a != c:
        check("A 默认恒等", False, "第 %d 盘不一致" % t)
        break
    same_cnt += 1
check("A1 默认参数恒等（300 盘逐项一致）", same_cnt == 300, "%d/300" % same_cnt)

# 带 flags/banned 的调用同样恒等
b = [[random.choice("RPGWOYB") for _ in range(8)] for _ in range(8)]
fl = {(3, 3): 1, (5, 5): 4}
a = rank_moves(b, flags=fl, banned={frozenset({(0, 0), (0, 1)})})
c = rank_moves(b, flags=fl, banned={frozenset({(0, 0), (0, 1)})},
               w_vertical=0.0, w_starcol=0.0, w_hyper2=0.0)
check("A2 带 flags+banned 恒等", a == c)

# ── B. 冰风暴：竖向匹配加权 ─────────────────────────────────────────
random.seed(7)
board_v = None
for _ in range(2000):
    b = [[random.choice("RPGWOYB") for _ in range(8)] for _ in range(8)]
    rk = rank_moves(b)
    if not rk:
        continue
    tops = [t for t in rk if top_is_vertical(b, (t[6], t[7]))]
    if tops and not top_is_vertical(b, (rk[0][6], rk[0][7])):
        board_v = b          # 有竖向招但默认第一名不是竖向的盘
        break
if board_v:
    rk0 = rank_moves(board_v)
    rk1 = rank_moves(board_v, w_vertical=3000.0)
    check("B1 w_vertical 把竖向招顶到第一",
          top_is_vertical(board_v, (rk1[0][6], rk1[0][7])),
          "默认第一 %s<->%s → 加权后 %s<->%s"
          % (rk0[0][6], rk0[0][7], rk1[0][6], rk1[0][7]))
else:
    check("B1 w_vertical 把竖向招顶到第一", False, "2000 盘没造出反例盘")

# ── C. 冰风暴：闪电宝石（flag 4）引爆加权 ───────────────────────────
#   底板是无三连的循环图案；(5,3)(5,4) 两枚 P、(5,4) 是闪电宝石。
#   唯一能消到它的招 = (4,5)<->(5,5)，把 P 挪下来凑成横向三连。
base = [["R", "G", "B", "Y", "O", "W", "P", "R"],
        ["G", "B", "Y", "O", "W", "P", "R", "G"],
        ["B", "Y", "O", "W", "P", "R", "G", "B"],
        ["Y", "O", "W", "P", "R", "G", "B", "Y"],
        ["O", "W", "P", "R", "G", "B", "Y", "O"],
        ["W", "P", "R", "G", "B", "Y", "O", "W"],
        ["P", "R", "G", "B", "Y", "O", "W", "P"],
        ["R", "G", "B", "Y", "O", "W", "P", "R"]]
b = [r[:] for r in base]
b[4][2] = "Y"          # 拆掉 (4,2) 的 P：否则 (4,2)<->(5,2) 也把 P 送进 (5,2) 连到星标
b[4][5] = "P"          # 挪下来要用的那枚
b[5][1] = "G"          # 拆掉 (5,1) 的 P：否则 (4,2)<->(5,2) 也能凑出 P 连线引到它
b[5][3] = "P"
b[5][4] = "P"          # 闪电宝石本体
fl = {(5, 4): 4}
TARGET = frozenset({(4, 5), (5, 5)})
rk0 = rank_moves(b, flags=fl)
rk1 = rank_moves(b, flags=fl, w_starcol=2000.0)
top0 = frozenset((rk0[0][6], rk0[0][7])) if rk0 else None
top1 = frozenset((rk1[0][6], rk1[0][7])) if rk1 else None
check("C1 w_starcol 把引爆闪电宝石的招顶到第一",
      top0 is not None and top0 != TARGET and top1 == TARGET,
      "默认第一=%s → 加权后第一=%s" % (top0, top1))

# ── D. 双超能对撞 ───────────────────────────────────────────────────
b = [r[:] for r in base]
b[3][3] = "S"
b[3][4] = "S"
rk0 = rank_moves(b)
mv = frozenset({(3, 3), (3, 4)})
in0 = any(frozenset((t[6], t[7])) == mv for t in rk0)
rk1 = rank_moves(b, w_hyper2=50000.0)
top1 = frozenset((rk1[0][6], rk1[0][7])) if rk1 else None
check("D1 无 w_hyper2 时 S-S 对撞不进候选", rk0 and not in0)
check("D2 w_hyper2 时 S-S 对撞排第一", top1 == mv,
      "第一=%s 分=%.0f" % (top1, rk1[0][0]))

# ── E. 各模式 solver_kw ─────────────────────────────────────────────
from modes.icescape import Mode as Ice
from modes.butterfly import Mode as Bf
from modes.lightning import Mode as Li
from modes.classic import Mode as Cl

kw = Ice().solver_kw()
check("E1 冰风暴 kw", kw.get("w_vertical") == 3000.0
      and kw.get("w_starcol") == 2000.0 and kw.get("w_hyper2") == 50000.0,
      str({k: kw[k] for k in ("w_vertical", "w_starcol", "w_hyper2")}))
kw = Bf().solver_kw()
check("E2 蝴蝶 kw（造魔方 1500）", kw.get("w_make_hyper") == 1500.0)
kw = Li().solver_kw()
check("E3 闪电 kw（w_special 10）", kw.get("w_special") == 10.0)
kw = Cl().solver_kw()
check("E4 经典 kw 不变", kw.get("save_hyper") is True and kw.get("w_make_hyper") == 3000.0
      and "w_special" not in kw and "w_vertical" not in kw)

# ── F. 蝴蝶端到端：造魔方招在蝴蝶模式里前置 ─────────────────────────
random.seed(11)
for _ in range(3000):
    b = [[random.choice("RPGWOYB") for _ in range(8)] for _ in range(8)]
    b[0][0] = "S"        # 盘上已有魔方（有魔方才体现攒的行为差异不大，
    rk0 = rank_moves(b)  # 这里只验 kw 真的传进去了：w_make_hyper>0 时
    if not rk0:
        continue
    made0 = [t for t in rk0 if not (b[t[6][0]][t[6][1]] == "S"
                                    or b[t[7][0]][t[7][1]] == "S")
             and any(n >= 5 for n in t[9])]
    if made0 and rk0[0] != made0[0]:
        rk1 = rank_moves(b, w_make_hyper=1500.0)
        makes = any(n >= 5 for n in rk1[0][9])
        check("F1 w_make_hyper 让造魔方招排第一",
              makes and rk1[0][0] >= made0[0][0] + 1500.0 - 1e-6,
              "默认第一分=%.0f → 加权后第一分=%.0f（造魔方招最高分=%.0f）"
              % (rk0[0][0], rk1[0][0], made0[0][0]))
        break
else:
    check("F1 w_make_hyper 改变候选排序", False, "3000 盘没造出含 5 连的盘")

print()
if FAIL:
    print("失败 %d 项: %s" % (len(FAIL), FAIL))
    sys.exit(1)
print("全部通过")
