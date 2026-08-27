#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""testVLM.py —— 单张截图测试 VLM 做题能力（完全复用主流程决策链路）。

用法：
    python testVLM.py                # 默认测试 test1.png
    python testVLM.py 某截图.png     # 指定截图

与主流程同一套代码：OCR 识别 → DecisionEngine._call_vlm_fallback
（decision_engine.VLM_PROMPT_TEMPLATE 读题作答）→ VLMClient 请求/解析 → OCR 反查坐标。
不在这里维护第二套 Prompt；切换模型只需改 config.py 的 OLLAMA_MODEL。
"""

import json
import sys

from PIL import Image

import config
from ocr_engine import OCREngine
from decision_engine import DecisionEngine
from vlm_client import VLMClient


def get_vlm_decision(image_path):
    # 与 main.py 完全一致的初始化
    ocr = OCREngine(use_gpu=True)
    vlm = VLMClient()
    decision = DecisionEngine(ocr, vlm, config)
    decision.vlm_ready = vlm.check_health()
    if not decision.vlm_ready:
        print(f"[testVLM] 警告：Ollama 不可用或模型 {vlm.model} 未加载，请先 ollama pull {vlm.model}")

    screenshot = Image.open(image_path).convert("RGB")
    ocr_results = ocr.recognize(screenshot)
    print(f"[testVLM] OCR 识别到 {len(ocr_results)} 条文字")

    # 直接调用主流程的"题目页 VLM 兜底"（读题作答），返回与主流程完全一致的决策。
    # 需要思考的页面（题目/拿不准）在 main.py 里同样走这个方法。
    result = decision._call_vlm_fallback(screenshot, ocr_results, "test_page")
    if decision.last_vlm_raw:
        print(f"[testVLM] VLM 原始返回: {decision.last_vlm_raw!r}")
    return result


# 测试运行
if __name__ == "__main__":
    image_path = sys.argv[1] if len(sys.argv) > 1 else "test1.png"
    print(f"[testVLM] 截图: {image_path}  模型: {VLMClient().model}")
    result = get_vlm_decision(image_path)
    print(json.dumps(result, indent=2, ensure_ascii=False))
