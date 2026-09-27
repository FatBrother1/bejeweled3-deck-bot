#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""模式脚本化 —— 离线验证（行为等价 + 结构正确）

要证的核心只有一条：**把 if 链拆成八个模式文件之后，引擎的行为没变。**

  A. 注册表：8 个模式全部加载，KEY/NAME/GEO/EFFECTIVE 齐全
  B. 几何映射：新模式表与旧 if 表逐项一致
  C. 有效判据：新模式表与旧条件 `nd>0 or poker` 逐项一致
  D. 普通模式选步 == 带模式权重的 solver_pro.rank_moves
     （2026-09-27 起经典模式多了「万变魔方」权重，参照系要带上它；
       策略本身在 test_hyper.py 里单测）
  E. 两道假死局兜底真的会救（掩码致 0 候选 / 合法走法全被 ban）
  F. 牌局模式选步 == 旧牌局分支（两种手牌状态各测）
  G. 模式粘性规则：classic/poker 跟着走，diamond/butterfly/lightning 粘住
  H. 检测优先级：poker hint > diamond > butterfly > lightning > classic
"""
import random
import sys

import modes
import solver_pro
import solver_poker
import poker

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(("  ✓ " if cond else "  ✗ ") + name + ("" if cond else "   ← " + str(detail)))


def rnd_board(seed, mud=0):
    rng = random.Random(seed)
    g = [[rng.choice("RGOYBPW") for _ in range(8)] for _ in range(8)]
    for _ in range(mud):
        g[rng.randrange(8)][rng.randrange(8)] = "D"
    return g


def ctx_for(g, nd=0, extra=None, hint=None, frame=None):
    return {"g": [r[:] for r in g], "g_raw": [r[:] for r in g],
            "blacklist": {}, "banned": set(), "banned_sticky": set(),
            "extra": extra or {}, "nd": nd, "frame": frame,
            "log": lambda m: None, "bad": 0, "dead": 0,
            "get_frame": (lambda: None)}


print("A. 注册表")
KEYS = modes.keys()
check("注册 8 个模式", len(KEYS) == 8, KEYS)
for k in KEYS:
    m = modes.by_key(k)
    ok = bool(m and m.KEY == k and m.NAME and m.GEO and m.EFFECTIVE)
    check("  %-10s KEY/NAME/GEO/EFFECTIVE 齐全  geo=%-9s effective=%s"
          % (k, getattr(m, "GEO", "?"), getattr(m, "EFFECTIVE", "?")), ok)
check("八个模式是八个不同文件（KEY 不重复）", len(set(KEYS)) == 8)

print("\nB. 几何映射 vs 旧 if 表")
# 旧表：poker→poker；有泥→diamond；有蝴蝶→butterfly；其余→classic
#   注意 hint 只有 "poker" 是有意义的（画面判据）；其余情况 hint 必须是 None，
#   否则会被当成"点名模式"直接返回、绕过特征检测。
OLD_GEO = [("poker", 0, False, "poker"), (None, 0, False, "classic"),
           (None, 3, False, "diamond"), (None, 0, True, "butterfly"),
           (None, 3, True, "diamond")]           # 有泥优先于蝴蝶
for hint, nd, bf, want in OLD_GEO:
    m = modes.detect({"hint": hint, "nd": nd,
                      "extra": {"butterflies": [(0, 0)] if bf else []},
                      "frame": None})
    check("hint=%-7s nd=%d 蝴蝶=%-5s → geo=%-9s（旧表 %s）"
          % (hint, nd, bf, m.GEO, want), m.GEO == want)

print("\nC. 有效判据 vs 旧条件 `nd>0 or poker`")
OLD_EFF = [(0, False, "score"), (3, False, "board"), (0, True, "board"),
           (3, True, "board")]
for nd, is_poker, want in OLD_EFF:
    m = modes.detect({"hint": ("poker" if is_poker else None), "nd": nd,
                      "extra": {}, "frame": None})
    check("nd=%d 牌局=%-5s → effective=%-5s（旧条件 %s）"
          % (nd, is_poker, m.EFFECTIVE, want), m.EFFECTIVE == want)

print("\nD. 普通模式选步 == 直接调 solver_pro.rank_moves（200 盘）")
# ★ 2026-09-27：经典模式加了「万变魔方」策略（造魔方加权 + 有别的招不动魔方），
#   所以参照系要带上它自己的权重 —— 这条测的是「引擎只转发、不自己决策」，
#   模式权重变了它就该跟着变（策略本身在 test_hyper.py 里单测）。
cls = modes.by_key("classic")
bad = 0
for seed in range(200):
    g = rnd_board(seed)
    c = ctx_for(g)
    res = cls.choose(c)
    ref = solver_pro.rank_moves(g, timegems=[], banned=set(), flags={},
                                butterflies=[], **cls.solver_kw())
    if not ref:
        if res is not None:
            bad += 1
        continue
    if res is None or res["cells"] != (ref[0][6], ref[0][7]) or res["pred"] != ref[0][1]:
        bad += 1
        if bad <= 2:
            print("     反例 seed=%d res=%s ref=%s" % (seed, res and res["cells"],
                                                       (ref[0][6], ref[0][7])))
check("200 盘首选走法与带模式权重的求解器逐项一致", bad == 0, "不一致 %d" % bad)

print("\nE. 两道假死局兜底")
# 造一个"掩码把候选杀光"的局面：先取一个真有解的局面
g = rnd_board(3)
found = None
for seed in range(400):
    gg = rnd_board(seed)
    if solver_pro.rank_moves(gg):
        found = gg
        break
check("找得到一个有解局面", found is not None)
# ① 掩码版 0 候选、真实棋盘有候选
c = ctx_for(found)
for r in range(8):
    for cc in range(8):
        c["g"][r][cc] = "?"
c["blacklist"] = {(0, 0): 3}       # 有掩码，才允许走第①层兜底
res = modes.by_key("classic").choose(c)
check("① 掩码致 0 候选 → 用 g_raw 救回", res is not None,
      res and res["cells"])
# ② 合法走法全被 banned
ref = solver_pro.rank_moves(found)
mv = frozenset({ref[0][6], ref[0][7]})
c2 = ctx_for(found)
c2["g"] = [r[:] for r in found]
# 把真实棋盘上所有候选都 ban 掉
allmv = set()
for t in solver_pro.rank_moves(found, topk=0):
    allmv.add(frozenset({t[6], t[7]}))
c2["banned"] = allmv
res2 = modes.by_key("classic").choose(c2)
check("② 合法走法全被 ban → 解禁重算救回", res2 is not None,
      res2 and res2["cells"])

print("\nF. 牌局模式选步 == 牌局求解器（2026-09-27 起空手也走它）")
_g = rnd_board(11)
_orig_read = poker.read_hand
try:
    # ① 手牌全背面 → 2026-09-27 改：也走牌局求解器（原来退回普通评分），取 t[5],t[6]
    poker.read_hand = lambda fr, verbose=False: ["?", "?", "?", "?", "?"]
    res = modes.by_key("poker").choose(ctx_for(_g, frame="x"))
    ref = solver_poker.rank_moves_poker(_g, hand=["?", "?", "?", "?", "?"], topk=10)
    ok = (res is None and not ref) or (res and ref and
                                       res["cells"] == (ref[0][5], ref[0][6]))
    check("① 手牌全背面 → 走牌局求解器，取 t[5],t[6]", ok,
          res and res["cells"])
    # ② 手牌有花色 → 旧代码走 solver_poker，取 t[5],t[6]
    poker.read_hand = lambda fr, verbose=False: ["G", "G", "?", "?", "?"]
    res = modes.by_key("poker").choose(ctx_for(_g, frame="x"))
    ref = solver_poker.rank_moves_poker(_g, hand=["G", "G", "?", "?", "?"], topk=10)
    ok = (res is None and not ref) or (res and ref and
                                       res["cells"] == (ref[0][5], ref[0][6]))
    check("② 手牌有花色 → 走牌局求解器，取 t[5],t[6]", ok, res and res["cells"])
finally:
    poker.read_hand = _orig_read
check("牌局 DEAD_EXIT_AT=30（旧代码 dead>=30 就 break）",
      modes.by_key("poker").DEAD_EXIT_AT == 30)
check("普通模式 DEAD_EXIT_AT=None（旧代码就地待命、不退出）",
      modes.by_key("classic").DEAD_EXIT_AT is None)

print("\nG. 模式粘性规则")
from bot_v6 import select_mode
cur = modes.by_key("classic")
# classic 可以被 diamond 顶掉
m = select_mode(cur, {"hint": None, "nd": 3, "extra": {}, "frame": None})
check("classic → diamond（兜底可被顶掉）", m.KEY == "diamond", m.KEY)
# diamond 不会被 classic 顶回来
m2 = select_mode(m, {"hint": None, "nd": 0, "extra": {}, "frame": None})
check("diamond → 仍是 diamond（粘住）", m2.KEY == "diamond", m2.KEY)
# diamond 不会被 butterfly 顶掉
m3 = select_mode(m, {"hint": None, "nd": 3,
                     "extra": {"butterflies": [(0, 0)]}, "frame": None})
check("diamond + 出现蝴蝶 → 仍是 diamond（粘住）", m3.KEY == "diamond", m3.KEY)
# poker 可以跟着 hint 走回来
p = modes.by_key("poker")
m4 = select_mode(p, {"hint": None, "nd": 0, "extra": {}, "frame": None})
check("poker + hint 消失 → 回到 classic（跟着走）", m4.KEY == "classic", m4.KEY)

print("\nH. 检测优先级")
m = modes.detect({"hint": "poker", "nd": 3,
                  "extra": {"butterflies": [(0, 0)], "timegems": [(1, 1, 9)]},
                  "frame": None})
check("poker hint 压过泥土/蝴蝶/时间宝石", m.KEY == "poker", m.KEY)
m = modes.detect({"hint": None, "nd": 3,
                  "extra": {"butterflies": [(0, 0)], "timegems": [(1, 1, 9)]},
                  "frame": None})
check("泥土压过蝴蝶和时间宝石", m.KEY == "diamond", m.KEY)
m = modes.detect({"hint": None, "nd": 0,
                  "extra": {"butterflies": [(0, 0)], "timegems": [(1, 1, 9)]},
                  "frame": None})
check("蝴蝶压过时间宝石", m.KEY == "butterfly", m.KEY)
m = modes.detect({"hint": None, "nd": 0,
                  "extra": {"timegems": [(1, 1, 9)]}, "frame": None})
check("只有时间宝石 → lightning", m.KEY == "lightning", m.KEY)
m = modes.detect({"hint": None, "nd": 0, "extra": {}, "frame": None})
check("什么都没有 → classic 兜底", m.KEY == "classic", m.KEY)

# ★ 2026-09-26 新增：闪电靠棋盘对象的 vtable 值认领
#   时间宝石只在盘上待几秒，光靠"有宝石"要等几秒才认得出 —— 那几秒会拿经典
#   几何去点（实测闪电棋盘比经典低约 47px，点到隔壁行、必被拒）。
m = modes.detect({"hint": None, "nd": 0,
                  "extra": {"board_vt": 0x8665C4}, "frame": None})
check("棋盘 vtable=0x8665C4（无时间宝石）→ lightning", m.KEY == "lightning", m.KEY)
m = modes.detect({"hint": None, "nd": 0,
                  "extra": {"board_vt": 0x86511C}, "frame": None})
check("棋盘 vtable=0x86511C（经典）→ classic", m.KEY == "classic", m.KEY)
m = modes.detect({"hint": None, "nd": 0,
                  "extra": {"board_vt": 0x8665C4, "butterflies": [(0, 0)]},
                  "frame": None})
check("蝴蝶压过闪电 vtable", m.KEY == "butterfly", m.KEY)
check("闪电几何 = lightning（board_lightning.json）",
      modes.by_key("lightning").GEO == "lightning",
      modes.by_key("lightning").GEO)

print("\n" + "=" * 62)
print("通过 %d / 失败 %d" % (len(PASS), len(FAIL)))
if FAIL:
    print("失败项:")
    for f in FAIL:
        print("   " + f)
sys.exit(1 if FAIL else 0)
