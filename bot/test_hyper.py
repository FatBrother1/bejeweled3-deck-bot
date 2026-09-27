#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""经典模式「万变魔方」策略 —— 离线验证（2026-09-27）

用户点名：能造魔方就造、造出来别用、真没招了再用（魔方能带进下一关）。
这里要证的就是这四句 + 一句"别的模式没跟着变"：

  A. 默认参数 = 老行为（候选表逐项一致）
  B. 只有经典模式声明了这条策略，别的模式权重仍是"不管"
  C. 盘上同时有魔方招和普通招 → 默认解算器选魔方招（改动前的行为），
     经典模式选普通招（改动后的行为）—— 这一条就是 A/B 对照
  D. 魔方招没有被丢掉，只是排最后（真没招了还能走）
  E. 一条普通招都没有时 → 经典模式照样走魔方（不会卡死）
  F. 掩码把普通招掩光、只剩魔方招 → ①b 层拿真实棋盘重算，先不动魔方
  G. 能造魔方的招（5 连）优先于分数更高但不造魔方的招
  H. 其它模式（禅意/冰风暴/任务/闪电/蝴蝶/钻石矿）选步与直调求解器逐项一致
"""
import random
import sys

sys.path.insert(0, ".")
import modes          # noqa: E402
import solver_pro     # noqa: E402

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(("  ✓ " if cond else "  ✗ ") + name + ("" if cond else "   ← " + str(detail)))


def rnd_board(seed):
    rng = random.Random(seed)
    return [[rng.choice("RGOYBPW") for _ in range(8)] for _ in range(8)]


def ctx_for(g, blacklist=None, banned=None):
    return {"g": [r[:] for r in g], "g_raw": [r[:] for r in g],
            "blacklist": blacklist or {}, "banned": banned or set(),
            "banned_sticky": set(), "extra": {}, "nd": 0, "frame": None,
            "log": lambda m: None, "bad": 0, "dead": 0,
            "get_frame": (lambda: None)}


def pattern():
    """无解盘：g[i][j] = C[(i+j) % 7]，任何一换都连不成三个。"""
    C = "RPGWOYB"
    return [[C[(i + j) % 7] for j in range(8)] for i in range(8)]


def board_with_hyper_and_one_move():
    """无解盘 + (4,4) 放一个魔方 + 第 0 行造出一条普通招。

    第 0 行改成 R R P R W O Y B：把 (0,2) 和 (0,3) 一换就是 R R R。
    """
    g = pattern()
    g[0] = list("RRPRWOYB")
    g[4][4] = "S"
    return g


def board_hyper_only():
    """无解盘 + (4,4) 一个魔方 —— 除了动魔方，一条招都没有。"""
    g = pattern()
    g[4][4] = "S"
    return g


def is_hyper_move(g, t):
    (i1, j1), (i2, j2) = t[6], t[7]
    return g[i1][j1] == "S" or g[i2][j2] == "S"


print("A. 默认参数 = 老行为")
bad = 0
for seed in range(200):
    g = rnd_board(seed)
    a = solver_pro.rank_moves(g)
    b = solver_pro.rank_moves(g, w_make_hyper=0.0, save_hyper=False)
    if len(a) != len(b):
        bad += 1
        continue
    for x, y in zip(a, b):
        if x[:9] != y[:9]:
            bad += 1
            break
check("200 个随机盘：显式传默认值与不传逐项一致", bad == 0, "不一致 %d" % bad)

print("\nB. 只有经典模式声明了这条策略")
for k in modes.keys():
    m = modes.by_key(k)
    want = (m.W_MAKE_HYPER, m.SAVE_HYPER)
    got = (m.solver_kw()["w_make_hyper"], m.solver_kw()["save_hyper"])
    is_cls = (k == "classic")
    ok = (got == want) and ((want == (0.0, False)) != is_cls)
    check("  %-10s w_make_hyper=%-6s save_hyper=%-5s" % (k, got[0], got[1]), ok,
          "want=%s" % (want,))

print("\nC. 有魔方又有普通招：默认选魔方，经典模式选普通招（A/B 对照）")
g = board_with_hyper_and_one_move()
rk_def = solver_pro.rank_moves(g)
rk_cls = solver_pro.rank_moves(g, w_make_hyper=3000.0, save_hyper=True)
check("这一盘默认解算器的第一名是魔方招（=改动前的行为）",
      bool(rk_def) and is_hyper_move(g, rk_def[0]),
      rk_def and rk_def[0][6:8])
check("这一盘确实有普通招可走",
      any(not is_hyper_move(g, t) for t in rk_def),
      [t[6:8] for t in rk_def[:5]])
res = modes.by_key("classic").choose(ctx_for(g))
check("经典模式选的是普通招，不是魔方",
      res is not None and not is_hyper_move(g, res["t"]), res and res["cells"])

print("\nD. 魔方招没被丢掉，只是排最后")
check("候选表里仍有魔方招", any(is_hyper_move(g, t) for t in rk_cls),
      [t[6:8] for t in rk_cls[:5]])
hy = [t for t in rk_cls if is_hyper_move(g, t)]
check("魔方招排在候选表末尾", hy and rk_cls.index(hy[0]) >= len(rk_cls) - len(hy),
      "位置 %s / 共 %d" % ([rk_cls.index(t) for t in hy], len(rk_cls)))

print("\nE. 一条普通招都没有 → 照样走魔方（不会卡死）")
g2 = board_hyper_only()
rk2_def = solver_pro.rank_moves(g2)
check("这一盘普通招 = 0（构造正确）",
      all(is_hyper_move(g2, t) for t in rk2_def), len(rk2_def))
res2 = modes.by_key("classic").choose(ctx_for(g2))
check("经典模式仍然有招可走，而且就是魔方招",
      res2 is not None and is_hyper_move(g2, res2["t"]), res2 and res2["cells"])
check("魔方招候选数 = 魔方周围可换的邻居数（≥2）", len(rk2_def) >= 2, len(rk2_def))

print("\nF. 掩码把普通招掩光 → ①b 层用真实棋盘重算")
g3 = board_with_hyper_and_one_move()
c3 = ctx_for(g3)
# 把第 0 行那条普通招牵涉到的三格掩成 '?'（bot 里是黑名单满 3 次就掩）
for j in (0, 2, 3):
    c3["g"][0][j] = "?"
c3["blacklist"] = {(0, 0): 3, (0, 2): 3, (0, 3): 3}
rk_mask = solver_pro.rank_moves(c3["g"], w_make_hyper=3000.0, save_hyper=True)
check("掩码后候选表里只剩魔方招（构造正确）",
      bool(rk_mask) and all(is_hyper_move(c3["g"], t) for t in rk_mask),
      [t[6:8] for t in rk_mask])
logs = []
c3["log"] = logs.append
res3 = modes.by_key("classic").choose(c3)
check("经典模式仍然选了普通招（没白扔魔方）",
      res3 is not None and not is_hyper_move(g3, res3["t"]), res3 and res3["cells"])
check("日志里报了「先不动魔方」",
      any("先不动魔方" in m for m in logs), logs)

print("\nG. 能造魔方的招优先于分数更高的普通招")
found = None
for seed in range(4000):
    gg = rnd_board(seed)
    r = solver_pro.rank_moves(gg)
    if not r:
        continue
    makers = [t for t in r if any(n >= 5 for n in t[9])]
    if makers and not is_hyper_move(gg, r[0]) and not any(
            n >= 5 for n in r[0][9]):
        found = (gg, r, makers[0])
        break
check("找得到「有 5 连招、但默认第一名不是它」的盘", found is not None)
if found:
    gg, r, mk = found
    r2 = solver_pro.rank_moves(gg, w_make_hyper=3000.0, save_hyper=True)
    check("默认第一名不是 5 连招", not any(n >= 5 for n in r[0][9]),
          r[0][9])
    check("加上造魔方权重后，第一名变成 5 连招",
          any(n >= 5 for n in r2[0][9]), r2[0][9])
    res4 = modes.by_key("classic").choose(ctx_for(gg))
    check("经典模式选步 == 加权重后的第一名",
          res4 is not None and res4["cells"] == (r2[0][6], r2[0][7]),
          res4 and res4["cells"])

print("\nH. 其它模式选步与直调求解器逐项一致（没跟着变）")
for key in ("zen", "icescape", "quest", "lightning", "butterfly", "diamond"):
    m = modes.by_key(key)
    bad = 0
    for seed in range(60):
        gg = rnd_board(seed)
        c = ctx_for(gg)
        if key == "diamond":
            c["nd"] = 3
        if key == "butterfly":
            c["extra"] = {"butterflies": [(3, 3)]}
        if key == "lightning":
            c["extra"] = {"timegems": [(2, 2, 5)]}
        res = m.choose(c)
        ref = solver_pro.rank_moves(gg, timegems=c["extra"].get("timegems") or [],
                                    banned=set(), flags={},
                                    butterflies=c["extra"].get("butterflies") or [])
        if not ref:
            if res is not None:
                bad += 1
            continue
        if res is None or res["cells"] != (ref[0][6], ref[0][7]):
            bad += 1
    check("  %-10s 60 盘首选一致" % key, bad == 0, "不一致 %d" % bad)

print("\n" + "=" * 62)
print("通过 %d / 失败 %d" % (len(PASS), len(FAIL)))
if FAIL:
    print("失败项:")
    for f in FAIL:
        print("   " + f)
sys.exit(1 if FAIL else 0)
