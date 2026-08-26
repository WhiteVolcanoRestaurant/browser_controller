#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""OCR 独立调试脚本：直接对 logs/ 里最新的截图跑 PaddleOCR。

目的：快速定位「text_count 一直为 0」的根因——
- 是截图本身空白？
- 是 PaddleOCR 没加载好？
- 是截图格式/尺寸不对？
用法：
    python debug_ocr.py                # 跑最新的一张 debug_page_*.png
    python debug_ocr.py logs/xxx.png   # 指定某张截图
"""

import glob
import os
import sys

import numpy as np
from PIL import Image

# 复用项目里的 OCREngine（保证 USERPROFILE/HOME 重定向逻辑一致）
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from ocr_engine import OCREngine  # noqa: E402


def find_latest_screenshot():
    pattern = os.path.join(PROJECT_ROOT, "logs", "debug_page_*.png")
    files = sorted(glob.glob(pattern), key=os.path.getmtime)
    return files[-1] if files else None


def dump_image_info(img):
    w, h = img.size
    # 采样判断是否为近似全白/全黑
    samples = 30
    step_w = max(w // samples, 1)
    step_h = max(h // samples, 1)
    total = 0
    brightness_sum = 0
    for i in range(0, w, step_w):
        for j in range(0, h, step_h):
            r, g, b = img.convert("RGB").getpixel((i, j))
            brightness_sum += (r + g + b) / 3.0
            total += 1
    avg_bright = brightness_sum / total if total else 0
    print(f"[DEBUG] 图片尺寸: {w}x{h}, 平均亮度: {avg_bright:.1f}"
          f" (≈0 全黑, ≈255 全白)")
    return w, h, avg_bright


def main():
    target = sys.argv[1] if len(sys.argv) > 1 else find_latest_screenshot()
    if not target or not os.path.isfile(target):
        print(f"[ERROR] 找不到截图: {target}")
        print("       请先运行 main.py 让它在 logs/ 下生成截图，或手动传入图片路径。")
        sys.exit(1)
    print(f"[INFO] 分析截图: {target}")

    try:
        img = Image.open(target)
    except Exception as e:
        print(f"[ERROR] 打开截图失败: {e}")
        sys.exit(1)

    w, h, avg_bright = dump_image_info(img)
    if avg_bright > 250:
        print("[WARN] 截图接近全白，可能页面还在加载 / 被 iframe 挡住 / 渲染出问题。")
    elif avg_bright < 5:
        print("[WARN] 截图接近全黑，可能页面崩溃 / headless 截图异常。")

    # 尝试多张缩放，OCR 对中文字大小很敏感
    scales = [1.0, 1.5, 2.0]
    engine = OCREngine(use_gpu=True, show_log=False)

    for scale in scales:
        if scale == 1.0:
            scaled = img
        else:
            scaled = img.resize((int(w * scale), int(h * scale)), Image.LANCZOS)
        print(f"\n[RUN] 缩放倍数: {scale}, 尺寸: {scaled.size}")
        try:
            results = engine.recognize(scaled)
        except Exception as e:
            print(f"      OCR 抛出异常: {e}")
            continue
        print(f"      识别到 {len(results)} 条文字")
        for i, r in enumerate(results, 1):
            bbox = r.get("bbox") or []
            if bbox:
                xs = [p[0] for p in bbox]
                ys = [p[1] for p in bbox]
                cx, cy = int(sum(xs)/len(xs)), int(sum(ys)/len(ys))
                loc = f"({cx},{cy})"
            else:
                loc = "(无坐标)"
            print(f"      {i:>2}. 置信度 {r['confidence']:.2f} {loc} -> {r['text']!r}")


if __name__ == "__main__":
    main()
