#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""模块 3：DecisionEngine —— 决策引擎（PRD 第三节 模块3 + 第五节 VLM 兜底）"""

import json
import os
import time

from PIL import Image


# 公共开头：角色设定 + OCR 文字上下文 + 页面 URL（两个 VLM 提示词共用）
VLM_COMMON_HEAD = """你是一个网页课程学习助手。请根据页面截图和下方 OCR 识别出的文字，决定下一步操作。

【OCR 识别到的文字】（带编号，请据此选择要点击的目标）：
{ocr_texts}

当前页面URL: {page_url}
"""

# 公共结尾：注意事项（两个 VLM 提示词共用）
VLM_COMMON_TAIL = """
注意：
- target_text 必须逐字复制 OCR 文字，不要改写或增删，否则无法定位到点击坐标。
- 只返回 JSON，不要输出其它内容。"""

# 题目页兜底规则：读题作答 + 常规翻页/结束判断
VLM_QUESTION_RULES = """决策规则：
- 优先点击推进课程进度的按钮（如"下一页""下一题""下一步""继续""确定"等），action 设为 "click"，target_text 填写该按钮文字。
- 如果页面包含题目或问答，且你能确定正确答案，则 action 设为 "click"，target_text 填写正确选项对应的文字；多选题一次只填一个尚未选中的正确选项，等所有正确选项都选完后，再让 target_text 填"提交"。
- 如果页面包含题目或问答，但你无法确定答案、或题目是开放题/涉及安全判断拿不准时，action 设为 "need_human"，target_text 填空字符串 ""，reason 说明需要人工介入的原因。
- 如果页面显示"已完成""学习完成""课程完成"等结束提示，action 设为 "terminate"，target_text 填空字符串 ""。
- 如果暂时无法确定且不是题目，action 设为 "wait"，target_text 填空字符串 ""。"""

# 语义兜底规则：OCR 匹配不到标准翻页按钮时，判断页面上有没有"推进按钮"
VLM_NAV_RULES = """决策规则：
- 当前页面没有识别出标准翻页按钮（如"下一页""继续""下一步"），请判断页面上是否存在一个"能推进课程进度"的可点击元素（按钮/链接/图片链接）。
- 这类元素通常是页面中靠下方、唯一明显的按钮或引导点击文字，例如"点击xx查看xxxx""看看有哪些xxxx"，这些文字一般能引导用户点击查看。
- 如果存在这样的元素，action 设为 "click"，target_text 填写该元素文字。
- 如果页面是纯内容展示、没有可点击的推进元素，action 设为 "need_human"，target_text 填空字符串 ""。reason 说明你对这一页内容讲了什么的理解和判断，哪一段文本是最"能推进课程进度"的。"""


VLM_PROMPT_TEMPLATE = (
    VLM_COMMON_HEAD
    + """请严格按照以下 JSON 格式输出决策，不要输出任何其他内容：
{{
  "action": "click" 或 "wait" 或 "terminate" 或 "need_human",
  "target_text": "要点击的目标文字（必须原样复制自上方 OCR 文字）",
  "reason": "一句话说明理由",
  "confidence": 0.0 到 1.0 的数字
}}

"""
    + VLM_QUESTION_RULES
    + VLM_COMMON_TAIL
)


# 语义兜底 Prompt：当 OCR 匹配不到标准翻页按钮（下一页/继续）时，
# 让 VLM 判断页面上是否存在"能推进课程进度"的可点击元素（引导语/图片按钮等）。
VLM_SEMANTIC_PROMPT = (
    VLM_COMMON_HEAD
    + """请严格按照以下 JSON 格式输出决策，不要输出任何其他内容：
{{
  "action": "click" 或 "need_human",
  "target_text": "该可点击元素的文字（必须原样复制自上方 OCR 文字）",
  "reason": "一句话说明为什么它是推进按钮",
  "confidence": 0.0 到 1.0 的数字
}}

"""
    + VLM_NAV_RULES
    + VLM_COMMON_TAIL
)


class DecisionEngine:
    def __init__(self, ocr_engine, vlm_client, config):
        self.ocr_engine = ocr_engine
        self.vlm_client = vlm_client
        self.config = config
        # 由 main.py 启动时健康检查写入；False 时所有 VLM 调用直接转 need_human
        self.vlm_ready = True
        # 最近一次 VLM 原始返回内容，供困难样本记录（VLM 校验失败后需保留实际输出）
        self.last_vlm_raw = ""

    def _vlm_disabled_result(self):
        return {"action": "need_human",
                "reason": "VLM 未启用/不可用，请人工处理此页"}

    def decide(self, screenshot, ocr_results, page_url):
        all_text = " ".join(r.get("text", "") for r in ocr_results)

        # 步骤 1：优先匹配"推进进度"按钮（start/next）。学习内容页最明确的信号。
        # 必须排在结束检测之前：阶段性完成页会同时出现"恭喜你，你已完成了本微课"
        # 与"下一页"（接着进测验），有"下一页"就优先点击推进，而不是误判成课程结束；
        # 真正的结束页是"课程的学习已完成"正文 + "返回列表"按钮（没有"下一页"）。
        # 也必须放在题目检测之前：内容页文本里可能含"选择"等词，先走题目检测会误判成题目页。
        for priority in ("start", "next"):
            keywords = self.config.TARGET_BUTTONS[priority]
            matched = self.ocr_engine.filter_by_keywords(ocr_results, keywords)
            if not matched:
                continue
            candidates = self._build_candidates(matched)
            if candidates:
                return {"action": "click",
                        "x": candidates[0]["x"], "y": candidates[0]["y"],
                        "target": candidates[0]["target"],
                        "confidence": candidates[0]["confidence"],
                        "candidates": candidates}
            # 低置信度：继续尝试下一个优先级

        # 步骤 2：结束检测。没有可点的翻页按钮时才检查结束标志。
        # 结束标志只认正文"课程的学习已完成"等（按钮"返回列表"可能与其它页面内容冲突，
        # 不能用按钮文字判定；也不用裸"已完成"，阶段性文案"你已完成了本微课"会误判）。
        if any(et in all_text for et in self.config.END_TEXTS):
            return {"action": "terminate", "target": "", "confidence": 1.0,
                    "reason": "检测到课程完成标志"}

        # 步骤 3：题目检测（VLM）。没有明确翻页按钮时，才检查是否题目页，
        #        交给 VLM 用"逻辑能力"读题作答。
        if any(k in all_text for k in self.config.QUESTION_KEYWORDS):
            result = self._call_vlm_fallback(screenshot, ocr_results, page_url)
            if result.get("action") in ("error", "wait"):
                return {"action": "need_human",
                        "reason": result.get("reason", "检测到题目但无法自动作答")}
            return result

        # 步骤 4：submit 按钮（提交/确认/确定）——非题目页的确认按钮
        matched = self.ocr_engine.filter_by_keywords(
            ocr_results, self.config.TARGET_BUTTONS["submit"])
        if matched:
            candidates = self._build_candidates(matched)
            if candidates:
                return {"action": "click",
                        "x": candidates[0]["x"], "y": candidates[0]["y"],
                        "target": candidates[0]["target"],
                        "confidence": candidates[0]["confidence"],
                        "candidates": candidates}

        # 步骤 5：引导点击（"点击了解/点击查看"等引导语按钮）——标准翻页/提交都没有时，
        #        尝试点击页面底部的"点击 xxx"引导元素（反诈案例页常见，如"点击了解经过"）。
        #        排 submit 之后、wait 之前：无 VLM 模式下推进的最后一次机会；
        #        候选按从下到上排序（filter_by_keywords），先点最靠下的引导元素。
        matched = self.ocr_engine.filter_by_keywords(
            ocr_results, self.config.TARGET_BUTTONS["guide_click"])
        if matched:
            candidates = self._build_candidates(matched)
            if candidates:
                return {"action": "click",
                        "x": candidates[0]["x"], "y": candidates[0]["y"],
                        "target": candidates[0]["target"],
                        "confidence": candidates[0]["confidence"],
                        "candidates": candidates}

        # 步骤 6：OCR 无结果时等待（可能是登录页或页面尚未渲染），不触发 VLM
        if not ocr_results:
            return {"action": "wait", "reason": "OCR未识别到文字，等待页面加载或用户登录"}

        return {"action": "wait", "reason": "未匹配到任何目标"}

    def _build_candidates(self, matched, limit=3):
        # 把 OCR 匹配结果转成候选点击坐标列表（按置信度降序，最多 limit 个）。
        # 用于"误匹配时点一个无反应就换下一个命中位置"的多候选试错。
        candidates = []
        for m in matched:
            if m.get("confidence", 0) < self.config.OCR_CONFIDENCE_THRESHOLD:
                continue
            cx, cy = self.ocr_engine.get_center_point(m["bbox"])
            candidates.append({"x": cx, "y": cy, "target": m["text"],
                               "confidence": m["confidence"]})
            if len(candidates) >= limit:
                break
        return candidates

    def _call_vlm_fallback(self, screenshot, ocr_results, page_url=""):
        # 题目页 VLM 兜底：读题作答（选择正确选项）
        if not self.vlm_ready:
            return self._vlm_disabled_result()
        return self._vlm_query(screenshot, ocr_results, page_url, VLM_PROMPT_TEMPLATE)

    def semantic_fallback(self, screenshot, ocr_results, page_url=""):
        # 语义兜底：OCR 匹配不到标准翻页按钮时，让 VLM 判断"推进按钮"。
        # 用于"看看有哪些新型诈骗""点击词云查看""知识卡片"这类引导语/图片按钮。
        if not self.vlm_ready:
            return self._vlm_disabled_result()
        result = self._vlm_query(screenshot, ocr_results, page_url, VLM_SEMANTIC_PROMPT)
        if result.get("action") in ("error", "wait"):
            return {"action": "need_human",
                    "reason": result.get("reason", "VLM无法判断推进按钮")}
        return result

    def _vlm_query(self, screenshot, ocr_results, page_url, prompt_template):
        # 截图保存 + 构造 prompt + 调 VLM + 解析 + 反查坐标（通用逻辑）
        self.last_vlm_raw = ""
        try:
            expected_w = self.config.VLM_IMAGE_WIDTH
            expected_h = self.config.VLM_IMAGE_HEIGHT
            if screenshot.size == (expected_w, expected_h):
                scaled = screenshot.copy()
            else:
                # 维持宽高比缩放，以竖屏高为基准
                ratio = min(expected_w / screenshot.size[0], expected_h / screenshot.size[1])
                tw = max(1, int(screenshot.size[0] * ratio))
                th = max(1, int(screenshot.size[1] * ratio))
                scaled = screenshot.resize((tw, th), Image.LANCZOS)
        except Exception as e:
            return {"action": "error", "reason": f"截图缩放失败: {e}"}

        os.makedirs(self.config.LOG_DIR, exist_ok=True)
        path = os.path.join(self.config.LOG_DIR,
                            f"vlm_input_{int(time.time() * 1000)}.png")
        scaled.save(path)

        # 构造 OCR 文字上下文：VLM 只做决策，坐标由 OCR 反查
        ocr_texts = "\n".join(
            f"{i}. {r.get('text', '')}" for i, r in enumerate(ocr_results, 1)
        )
        prompt = prompt_template.format(
            ocr_texts=ocr_texts or "（OCR 未识别到文字）", page_url=page_url)

        try:
            response_text = self.vlm_client.ask(path, prompt)
        except Exception as e:
            return {"action": "error", "reason": f"VLM调用失败: {e}"}

        self.last_vlm_raw = response_text
        decision = self.vlm_client.parse_decision(response_text)
        print(f"[VLM] 原始返回: {response_text}")
        print(f"[VLM] 解析结果: {json.dumps(decision, ensure_ascii=False)}")

        action = decision.get("action")
        if action not in ("click", "wait", "terminate", "need_human"):
            return {"action": "error", "reason": "VLM校验失败"}
        try:
            confidence = float(decision.get("confidence", 0))
        except (TypeError, ValueError):
            confidence = 0.0
        print(f"[VLM] action={action}, confidence={confidence:.2f}")
        # need_human / terminate 不受 confidence 限制；只有 click 才要求足够置信
        if action == "click" and confidence < self.config.VLM_CONFIDENCE_THRESHOLD:
            return {"action": "error", "reason": "VLM置信度过低"}

        # wait / terminate / need_human 无需定位，直接返回
        if action != "click":
            return {"action": action,
                    "target": decision.get("target_text", ""),
                    "confidence": confidence,
                    "reason": decision.get("reason")}

        # click：在 OCR 结果中反查 target_text，得到精确点击坐标
        target_text = (decision.get("target_text") or "").strip()
        if not target_text:
            return {"action": "error", "reason": "VLM未给出目标文字"}
        located = self.ocr_engine.locate_by_text(ocr_results, target_text)
        if located is None:
            print(f"[OCR] 反查失败: 未在 OCR 结果中找到 \"{target_text}\"")
            return {"action": "error",
                    "reason": f"OCR未定位到目标文字: {target_text}"}
        cx, cy = self.ocr_engine.get_center_point(located["bbox"])
        print(f"[OCR] 反查成功: \"{target_text}\" -> 匹配 \"{located['text']}\" @ ({cx}, {cy})")
        return {"action": "click", "x": cx, "y": cy,
                "target": located["text"], "confidence": confidence,
                "reason": decision.get("reason")}
