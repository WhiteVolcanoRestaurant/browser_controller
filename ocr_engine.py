#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""模块 2：OCREngine —— 封装 PaddleOCR 文字检测与识别（PRD 第三节 模块2）"""

import os
import sys

# 【强制规则】重定向 PaddleOCR 模型缓存目录到当前纯英文项目路径，
# 避免 Windows 中文用户名目录（如 C:\Users\打工\.paddleocr）导致底层 C++ 引擎加载模型失败。
# 必须在 import paddleocr 之前设置（paddleocr 在 OCREngine.__init__ 中延迟导入）。
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
os.environ["USERPROFILE"] = PROJECT_ROOT
os.environ["HOME"] = PROJECT_ROOT

import numpy as np
from PIL import Image


class OCREngine:
    def __init__(self, use_gpu=True, lang="ch", show_log=False):
        from paddleocr import PaddleOCR
        self._PaddleOCR = PaddleOCR
        self._use_gpu = use_gpu
        self._lang = lang
        self._show_log = show_log
        self._ocr = self._create_ocr(use_gpu)

    def _create_ocr(self, use_gpu):
        # 依次尝试：指定模式 -> CPU -> 最小参数，兼容不同 PaddleOCR 版本
        attempts = [
            {"use_angle_cls": True, "lang": self._lang, "use_gpu": use_gpu, "show_log": self._show_log},
            {"use_angle_cls": True, "lang": self._lang, "use_gpu": False, "show_log": self._show_log},
            {"lang": self._lang},
        ]
        last_err = None
        for kwargs in attempts:
            try:
                return self._PaddleOCR(**kwargs)
            except Exception as e:
                last_err = e
        raise (last_err if last_err else RuntimeError("PaddleOCR 初始化失败"))

    def recognize(self, image):
        # 输入：PIL.Image 或 numpy array；返回 [{text, bbox, confidence}, ...]
        if isinstance(image, Image.Image):
            w, h = image.size
            print(f"[OCR] 输入图片尺寸 {w}x{h}, 模式 {image.mode}")
            image = np.array(image)
        # 先尝试 2 倍放大（中文字小时 PaddleOCR 更容易识别）
        variants = [(image, 1.0)]
        try:
            from PIL import Image as _Img
            scaled = _Img.fromarray(image).resize(
                (image.shape[1] * 2, image.shape[0] * 2), _Img.LANCZOS)
            variants.insert(0, (np.array(scaled), 2.0))
        except Exception:
            pass

        last_raw = None
        for arr, scale in variants:
            try:
                raw = self._ocr.ocr(arr, cls=True)
            except Exception as e:
                print(f"[OCR] 缩放 {scale}x ocr() 异常: {e}")
                raw = None
                # GPU 推理失败（如缺 cudnn64_8.dll）时，自动降级为 CPU 实例重试一次
                if self._use_gpu:
                    try:
                        print("[OCR] GPU 推理失败，自动降级为 CPU 运行", file=sys.stderr)
                        self._ocr = self._create_ocr(use_gpu=False)
                        self._use_gpu = False
                        raw = self._ocr.ocr(arr, cls=True)
                    except Exception as e2:
                        print(f"[OCR] 降级后依然异常: {e2}")
            last_raw = raw
            results = self._parse_v2(raw, scale)
            if results:
                print(f"[OCR] 缩放 {scale}x 识别到 {len(results)} 条文字")
                return results
            try:
                raw_v3 = self._ocr.predict(arr)
                results = self._parse_v3(raw_v3, scale)
                if results:
                    print(f"[OCR] 缩放 {scale}x predict 识别到 {len(results)} 条文字")
                    return results
            except Exception:
                pass

        print(f"[OCR] 所有缩放均识别为空, 原始 raw={last_raw!r}")
        return []

    def _parse_v2(self, raw, scale=1.0):
        # PaddleOCR 2.x 结构：[[[box, (text, conf)], ...], ...]
        results = []
        for page in (raw or []):
            if page is None:
                continue
            for item in page:
                if len(item) < 2:
                    continue
                box = item[0]
                text, conf = item[1][0], item[1][1]
                # 如果我们把图放大了再跑 OCR，bbox 要缩回到原始尺寸
                if scale != 1.0:
                    box = [[int(p[0] / scale), int(p[1] / scale)] for p in box]
                results.append({
                    "text": str(text),
                    "bbox": [[int(p[0]), int(p[1])] for p in box],
                    "confidence": float(conf),
                })
        return results

    def _parse_v3(self, raw, scale=1.0):
        # PaddleOCR 3.x predict 结构：list[dict(rec_texts/rec_scores/rec_polys)]
        results = []
        for item in (raw or []):
            if not isinstance(item, dict):
                continue
            texts = item.get("rec_texts") or []
            scores = item.get("rec_scores") or []
            polys = item.get("rec_polys") or item.get("dt_polys") or []
            for i, text in enumerate(texts):
                conf = scores[i] if i < len(scores) else 0.0
                bbox = []
                if i < len(polys):
                    bbox = [[int(p[0] / scale), int(p[1] / scale)] for p in polys[i]]
                results.append({
                    "text": str(text),
                    "bbox": bbox,
                    "confidence": float(conf),
                })
        return results

    @staticmethod
    def compact_text(text):
        # OCR 字距较大时会在字之间插入空格（如"继  续"），去掉所有空白再参与匹配。
        # str.split() 默认按 Unicode 空白切分（含全角空格 \u3000）。
        return "".join((text or "").split())

    def filter_by_keywords(self, ocr_results, keywords, prefix=None):
        # 模糊匹配（text 包含任一关键词），按"从下到上"（y 坐标降序）返回。
        # 匹配前先去掉文本内所有空白（OCR 会在字距大的字之间插入空格，如"继  续"）。
        # 推进/翻页按钮通常在页面底部、正文在上方，从下到上优先尝试，
        # 避免正文里的误匹配词（如"再三确认"）排在真实按钮前面被先点。
        # 关键：排除否定形式（如"不确定"不应命中"确定"），避免误点。
        # prefix：额外匹配"以 prefix 开头"的文字（如引导按钮"点击翻转"不在关键词表里，
        #         但以"点击"开头即可视为引导点击按钮）；否定形式（如"不点击"）天然不满足前缀。
        matched = []
        for r in ocr_results:
            compact = self.compact_text(r.get("text", ""))
            if not compact:
                continue
            hit = None
            for k in keywords:
                if k in compact:
                    # "不" + 关键词 出现在 text 里，说明是否定形式（不确定/不提交等），跳过
                    if ("不" + k) in compact:
                        continue
                    hit = k
                    break
            if hit is None and prefix and compact.startswith(prefix):
                hit = prefix
            if hit is not None:
                matched.append(r)
        # 空 bbox（v3 解析可能无坐标）排最后，避免 get_center_point 除零
        matched.sort(key=lambda r: self.get_center_point(r["bbox"])[1]
                     if r.get("bbox") else -1, reverse=True)
        return matched

    def locate_by_text(self, ocr_results, target_text):
        # 在 OCR 结果中反查目标文字，返回最佳匹配（含 bbox），找不到返回 None。
        # VLM 只负责决策出要点的文字，坐标由这里的 OCR 结果反查得到。
        # 双方都先去空白（OCR 会在字距大的字之间插入空格），再双向包含匹配。
        target = self.compact_text(target_text)
        if not target:
            return None
        best = None
        for r in ocr_results:
            text = self.compact_text(r.get("text", ""))
            if not text:
                continue
            # 双向包含匹配，兼容 OCR 漏字/多字导致的细微差异
            if target in text or text in target:
                if best is None or r.get("confidence", 0) > best.get("confidence", 0):
                    best = r
        return best

    def get_center_point(self, bbox):
        # 四点坐标 -> 中心点
        xs = [p[0] for p in bbox]
        ys = [p[1] for p in bbox]
        return (int(sum(xs) / len(xs)), int(sum(ys) / len(ys)))
