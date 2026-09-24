#!/usr/bin/env python3
"""棋盘标定工具（可视化版）—— 换机器 / 换分辨率 / 换补丁后用它。

★ 为什么不做"全自动搜索"
  我实测过自动搜索（投影法/饱和度覆盖率），**不可靠**：
  覆盖率指标随关卡背景变化 —— 同一套正确参数，
  白天关卡覆盖率 0.912、夜间森林关卡只有 0.568，
  自动搜索会漂到错误位置反而"看起来分更高"。
  ⇒ 定案：**自动搜索只给建议，最终必须肉眼确认。**

★ 本工具做法
  1. 抓一帧当前画面
  2. 把当前 board.json 的 8x8 网格画上去，存成 calib_overlay.png
  3. 打印每格读到的宝石（用 vision_np），让你核对
  4. 想调就用 --x0/--y0/--px/--py 再跑一次，直到网格对准
  5. 加 --save 才写入 board.json（旧文件自动备份 .bak）

用法：
    python3 calib.py                     # 看当前标定准不准（存 overlay 图）
    python3 calib.py --x0 476 --y0 79 --px 89.17 --py 88.17
    python3 calib.py --x0 483 --y0 93 --px 85.5 --py 85.2 --save
    python3 calib.py --auto              # 跑一次自动搜索只作参考
"""
import argparse, json, os, sys
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
BOARD_PATH = os.path.join(HERE, "bjbot", "board.json")
OUT_PNG = os.path.join(HERE, "calib_overlay.png")


def grab():
    from capture_pw import PwCapture
    c = PwCapture()
    if not c.start():
        print("抓帧失败:", c.err); return None
    a = None
    for _ in range(40):
        a = c.get(timeout=1.0)
        if a is not None: break
    c.stop()
    return a


def draw_overlay(im, x0, y0, px, py, path=OUT_PNG):
    """把 8x8 网格画到截图上，每格标坐标。"""
    from PIL import Image, ImageDraw
    img = Image.fromarray(im).convert("RGB")
    d = ImageDraw.Draw(img)
    for i in range(8):
        for j in range(8):
            cx = x0 + j * px; cy = y0 + i * py
            d.ellipse([cx - 4, cy - 4, cx + 4, cy + 4], outline=(255, 0, 255), width=2)
    # 棋盘外框
    d.rectangle([x0 - px / 2, y0 - py / 2, x0 + 7.5 * px, y0 + 7.5 * py],
                outline=(0, 255, 255), width=2)
    d.text((x0 - px / 2 + 4, y0 - py / 2 + 4), "x0=%.0f y0=%.0f px=%.1f py=%.1f" % (x0, y0, px, py),
           fill=(0, 255, 255))
    img.save(path)
    return path


def coverage(im, mask, x0, y0, px, py, rad=30):
    h, w = im.shape[:2]
    tot = []
    for i in range(8):
        for j in range(8):
            cy = int(round(y0 + i * py)); cx = int(round(x0 + j * px))
            if cy - rad < 0 or cy + rad >= h or cx - rad < 0 or cx + rad >= w:
                return -1.0
            tot.append(mask[cy - rad:cy + rad, cx - rad:cx + rad].mean())
    return float(np.mean(tot))


def saturation_mask(im):
    f = im.astype(np.float32)
    mx = f.max(axis=2); mn = f.min(axis=2)
    sat = np.where(mx > 1, (mx - mn) / np.maximum(mx, 1), 0)
    return (sat > 0.45) & (mx > 80)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--x0", type=float); ap.add_argument("--y0", type=float)
    ap.add_argument("--px", type=float); ap.add_argument("--py", type=float)
    ap.add_argument("--save", action="store_true", help="写入 board.json")
    a = ap.parse_args()

    im = grab()
    if im is None: sys.exit(1)
    h, w = im.shape[:2]
    print("抓帧 %dx%d" % (w, h))

    # 取参数：命令行优先，否则读现有 board.json
    cur = None
    if os.path.exists(BOARD_PATH):
        cur = json.load(open(BOARD_PATH))
    if a.x0 is not None:
        x0, y0, px, py = a.x0, a.y0, a.px, a.py
        print("用命令行参数")
    elif cur:
        x0, y0, px, py = cur["x0"], cur["y0"], cur["pitch_x"], cur["pitch_y"]
        print("用现有 board.json")
    else:
        # 没标定过 ⇒ 给一个按分辨率的初值（1280x800 的经验值等比例缩放）
        x0 = w * 0.372; y0 = h * 0.099; px = w * 0.0697; py = h * 0.1102
        print("无 board.json，用按分辨率的初值（需人工校准）")

    mask = saturation_mask(im)
    cv = coverage(im, mask, x0, y0, px, py)
    print("当前参数 x0=%.1f y0=%.1f px=%.2f py=%.2f" % (x0, y0, px, py))
    print("饱和度覆盖率 %.3f   （参考值；★随关卡背景变化，不可作唯一判据）" % cv)

    # 识别结果（真正的判据：能否读出 64 格宝石）
    try:
        from vision_np import read_grid_np
        # 临时用这组参数读
        import vision_np
        old = dict(vision_np.BOARD)
        vision_np.BOARD.update({"x0": x0, "y0": y0, "pitch_x": px, "pitch_y": py})
        g, cf = vision_np.read_grid_np(im)
        vision_np.BOARD.update(old)
        nq = str(cf).count("?")
        print()
        print("★ 真正的判据 —— 识别结果：未知格 %d/64" % nq)
        for i, r in enumerate(g):
            print("   %d  %s" % (i, " ".join(r)))
        if nq == 0:
            print("   ✅ 64 格全部识别成功 —— 标定正确")
        elif nq <= 3:
            print("   ⚠️ 有 %d 格没读到，可能只是该格有道具特效；再看 overlay 图确认网格是否对齐" % nq)
        else:
            print("   ❌ 未知格过多 —— 网格没对准，请调整参数（看 overlay 图）")
    except Exception as e:
        print("识别测试失败:", e)

    p = draw_overlay(im, x0, y0, px, py)
    print()
    print("已存标注图: %s" % p)
    print("  → 打开它看：紫色小圆点应落在每颗宝石正中心，青色方框应正好框住整个棋盘")

    if a.save:
        os.makedirs(os.path.dirname(BOARD_PATH), exist_ok=True)
        if cur:
            json.dump(cur, open(BOARD_PATH + ".bak", "w"), ensure_ascii=False, indent=1)
            print("旧标定已备份 → board.json.bak")
        out = {
            "screen": [w, h], "mode": "classic",
            "x0": float(x0), "y0": float(y0),
            "pitch_x": float(px), "pitch_y": float(py),
            "cols": [round(x0 + j * px, 1) for j in range(8)],
            "rows": [round(y0 + i * py, 1) for i in range(8)],
            "coverage": round(cv, 3),
        }
        json.dump(out, open(BOARD_PATH, "w"), ensure_ascii=False, indent=1)
        print("已写入 %s" % BOARD_PATH)
    else:
        print("（未写入；确认对准后加 --save 生效）")


if __name__ == "__main__":
    main()
