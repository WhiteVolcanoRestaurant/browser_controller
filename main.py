#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""主入口：组装各模块并运行核心工作流（PRD 第四节）"""

import argparse
import os
import random
import sys

# 【强制规则】重定向 PaddleOCR 模型缓存目录到当前纯英文项目路径，
# 避免 Windows 中文用户名目录导致 PaddleOCR 底层 C++ 引擎加载模型失败。
# 必须在导入 paddleocr 相关模块（ocr_engine 等）之前设置。
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
os.environ["USERPROFILE"] = PROJECT_ROOT
os.environ["HOME"] = PROJECT_ROOT

import config
from action_logger import ActionLogger
from browser_controller import BrowserController
from decision_engine import DecisionEngine
from flow_state import FlowState, FlowStateMachine
from ocr_engine import OCREngine
from safety_sandbox import SafetySandbox
from vlm_client import VLMClient


def parse_args():
    parser = argparse.ArgumentParser(
        description="基于 Playwright + PaddleOCR 的课程学习自动化脚本")
    parser.add_argument("course_url", nargs="?", default=config.TARGET_URL,
                        help="课程网页 URL（默认 %(default)s）")
    parser.add_argument("--no-vlm", action="store_true",
                        help="跳过 VLM（不调用 Ollama），所有需要思考的页面直接转人工介入")
    return parser.parse_args()


def _is_course_finished_jump(prev_url, curr_url):
    # 从课程详情页跳回非详情页（列表页），判定为"课程完成自动跳转"
    return (config.COURSE_DETAIL_URL_MARK in (prev_url or "")
            and config.COURSE_DETAIL_URL_MARK not in (curr_url or ""))


def _wait_for_next_lesson(browser, prev_detail_url):
    # 正常完成一节网课后，不退出脚本，等待用户手动打开下一节；返回新的详情页 URL。
    print("\n" + "=" * 60)
    print("[本节已完成] 等待你在浏览器中打开下一节网课...")
    print("打开下一节后脚本会自动继续；按 Ctrl+C 可退出。")
    while True:
        browser.wait(5000)
        cur = browser.get_current_url() or ""
        if (config.COURSE_DETAIL_URL_MARK in cur
                and cur != (prev_detail_url or "")):
            print(f"[继续] 检测到新课程详情页: {cur}")
            return cur


def _manual_wait(browser, page_url):
    # 人工介入：暂停自动操作，等用户手动完成本页（按 Enter 或页面自然变化）。
    changed, why = browser.wait_for_progress(timeout_ms=180000, prev_url=page_url)
    if changed and why == "user_enter":
        print("[继续] 用户按 Enter 唤醒，立即重新识别当前页面。")
    elif changed:
        print(f"[继续] 检测到 {why}，页面已变化，继续自动处理。")
    else:
        print("[提示] 等待超时，继续循环检测...")


def _candidate_key(candidate):
    """候选标识容忍相邻轮次 OCR 坐标出现少量像素漂移。"""
    return (candidate.get("target", ""),
            int(candidate.get("x", 0)) // 8,
            int(candidate.get("y", 0)) // 8)


def _vlm_before_human(flow, decision, screenshot, ocr_results, page_url, reason):
    """统一升级入口：VLM 可用时先推理，之后才允许转人工。"""
    if not decision.vlm_ready:
        return {"action": "need_human", "reason": reason,
                "source": "vlm_unavailable"}
    flow.transition(FlowState.VLM_REASONING, reason)
    result = decision.semantic_fallback(screenshot, ocr_results, page_url)
    result["source"] = "vlm"
    if result.get("action") == "click":
        return result
    vlm_reason = result.get("reason") or "VLM 未找到可靠的可点击目标"
    return {"action": "need_human",
            "reason": f"{reason}；VLM判断：{vlm_reason}",
            "source": "vlm"}


def main(course_url, enable_vlm=True):
    # 1. 初始化所有模块
    browser = BrowserController(channel=config.BROWSER_CHANNEL, headless=False)
    ocr = OCREngine(use_gpu=True)

    # 1.1 VLM 健康检查：启动时确认 Ollama 可用，不可用则自动降级为"无 VLM 模式"，
    #     避免运行中每次调用都白等 60 秒超时。
    vlm = VLMClient()
    vlm_ready = False
    if enable_vlm and config.ENABLE_VLM:
        print(f"[VLM] 检查 Ollama 服务（{vlm.base_url}, 模型 {vlm.model}）...")
        vlm_ready = vlm.check_health()
        if not vlm_ready:
            print("[VLM] 警告：Ollama 不可用或模型未加载，将跳过所有 VLM 决策，"
                  "需要思考的页面会直接转人工介入。")
            print("[VLM] （可用 `python main.py URL` 先 `ollama serve` + `ollama pull "
                  f"{vlm.model}` 启用；或忽略此提示以无 VLM 模式运行）")
    else:
        print("[VLM] 已按配置/参数跳过 VLM（--no-vlm 或 ENABLE_VLM=False），"
              "需要思考的页面将直接转人工介入。")
    decision = DecisionEngine(ocr, vlm, config)
    decision.vlm_ready = vlm_ready
    sandbox = SafetySandbox(config)
    logger = ActionLogger(os.path.join(config.LOG_DIR, "action_log.jsonl"))
    browser.set_logger(logger)  # 让 click 阶段的命中/保底诊断也写入日志台账
    flow = FlowStateMachine()

    # 两个计数用途不同（正常跳转/页面变动时都会重置）：
    # - no_progress_count：记录当前页面已发生的无效点击，用于日志与人工提示。
    # - consecutive_wait_count：OCR/DOM 均无候选时，连续等待达到阈值后触发 VLM。
    page_count = 0
    no_progress_count = 0  # 连续"点击了但页面无变化"的次数，用于分级降级恢复
    prev_url = ""          # 上一轮页面 URL，用于检测平台自动跳转
    consecutive_wait_count = 0  # 连续"未匹配目标(决策 wait)"的次数，达到阈值触发 VLM 语义兜底
    failed_candidates = set()
    force_vlm_reason = ""
    paused = False  # 按 p 键切换：暂停/继续自动操作
    try:
        # 2. 打开课程页面
        page = browser.navigate(course_url)
        logger.log(step=0, action="navigate", details={"page_url": page.url})

        # 2.1 若落在登录页，等待用户手动登录。
        # 避免在主循环里对登录页反复截图/OCR，导致页面闪动刷新。
        if "login" in (page.url or "").lower():
            print("[INFO] 检测到登录页，请在浏览器中手动完成登录，脚本将自动继续...")
            while "login" in (page.url or "").lower():
                browser.wait(5000)

        # 3. 主循环
        while page_count < config.MAX_PAGES:
            try:
                browser.step = page_count  # 让点击诊断日志能关联到当前页次
                # 3.0 暂停控制：按 p 切换暂停/继续（不影响 Enter 唤醒等其它按键语义）
                key = browser.read_key()
                if key in (b"p", b"P"):
                    paused = not paused
                    print(f"\n[暂停] {'已暂停，按 p 继续' if paused else '已继续'}")
                while paused:
                    browser.wait(400)
                    k = browser.read_key()
                    if k in (b"p", b"P"):
                        paused = False
                        print("[暂停] 已继续")
                        break
                flow.transition(FlowState.OBSERVE, "开始新一轮页面观察")
                # 3.0 检测页面 URL 是否自动跳转（真实平台课程完成/视频结束可能自动跳页）
                current_url = page.url or ""
                if prev_url and current_url != prev_url:
                    print(f"[跳转] 页面 URL 变化: {prev_url} -> {current_url}")
                    # 页面跳转说明有进展，重置无进展计数，避免跳转瞬间被误判为死循环
                    no_progress_count = 0
                    failed_candidates.clear()
                    # 页面已变动，重置"未匹配"计数，避免上一页的累计次数触发 VLM
                    consecutive_wait_count = 0
                    # 往回跳：从详情页跳回列表页，判定本课完成
                    if _is_course_finished_jump(prev_url, current_url):
                        logger.log(step=page_count, action="completed",
                                   details={"page_url": current_url,
                                            "message": "课程完成，自动跳回列表页"})
                        print("[完成] 检测到从详情页跳回列表页，判定本课完成。")
                        # 正常完成：不退出，等待用户打开下一节
                        new_url = _wait_for_next_lesson(browser, prev_url)
                        prev_url = new_url
                        no_progress_count = 0
                        continue
                prev_url = current_url

                # 3.1 截图
                screenshot = browser.screenshot()

                # 3.2 OCR 识别（失败重试 1 次）
                ocr_results = ocr.recognize(screenshot)
                if not ocr_results:
                    browser.wait(1000)
                    ocr_results = ocr.recognize(screenshot)

                # 调试可见：逐条打印 OCR 文字 + 中心坐标 + 置信度
                ocr_locations = []
                for i, r in enumerate(ocr_results, 1):
                    bbox = r.get("bbox") or []
                    conf = r.get("confidence", 0)
                    if bbox:
                        cx, cy = ocr.get_center_point(bbox)
                        ocr_locations.append({
                            "text": r["text"], "x": cx, "y": cy,
                            "confidence": round(float(conf), 3),
                        })
                        print(f"[OCR] {i}. \"{r['text']}\" @ ({cx}, {cy}) 置信度: {conf:.2f}")
                    else:
                        print(f"[OCR] {i}. \"{r['text']}\" 无坐标 置信度: {conf:.2f}")

                logger.log(step=page_count, action="ocr", details={
                    "page_url": page.url,
                    "text_count": len(ocr_results),
                    "texts": [r["text"] for r in ocr_results[:20]],
                    "locations": ocr_locations,
                    "screenshot": browser.last_screenshot_path,
                })

                # 3.3 决策
                flow.transition(FlowState.DECIDE, "根据截图、OCR和DOM生成候选")
                # 当前活动页中已真正可见、未遮挡、未禁用的 btn-next 优先级最高。
                # 隐藏的预置按钮不会通过 find_next_button 的可操作性检查。
                dom_next = browser.find_next_button()
                if dom_next:
                    force_vlm_reason = ""
                    (dx, dy), meta = dom_next
                    decision_result = {
                        "action": "click", "x": dx, "y": dy,
                        "target": meta.get("cls", "btn-next"),
                        "confidence": 0.98,
                        "reason": "活动页存在可见且可操作的翻页元素",
                        "source": "dom_next",
                    }
                else:
                    decision_result = decision.decide(screenshot, ocr_results, page.url)
                if (decision_result.get("source") == "vlm"
                        and flow.state == FlowState.DECIDE):
                    # 题目推理发生在 DecisionEngine 内部，返回后补记显式状态。
                    flow.transition(FlowState.VLM_REASONING, "决策引擎已完成VLM推理")

                if force_vlm_reason:
                    reason = force_vlm_reason
                    force_vlm_reason = ""
                    decision_result = _vlm_before_human(
                        flow, decision, screenshot, ocr_results, page.url, reason)

                # 3.3.1 兜底：如果 OCR 为空/决策是 wait，但页面里确实有"下一步/下一页"等按钮，
                #        用 Playwright 直接读 DOM 渲染层的可见文字定位坐标。
                #        解决视频/iframe 课程页导致 OCR 识别不到文字的问题。
                need_dom_fallback = (
                    not ocr_results
                    or decision_result.get("action") == "wait"
                    or decision_result.get("action") == "error"
                )
                if need_dom_fallback:
                    dom_keywords = []
                    for group in config.TARGET_BUTTONS.values():
                        dom_keywords.extend(group)
                    dom_found = browser.find_text_element_center(dom_keywords)
                    if not dom_found:
                        # 文字兜底失败，尝试按 class（next-btn/next）定位翻页按钮
                        dom_found = browser.find_next_button()
                    if dom_found:
                        (dx, dy), meta = dom_found
                        decision_result = {
                            "action": "click",
                            "x": dx, "y": dy,
                            "target": meta.get("text", meta.get("cls", meta.get("hit", "DOM定位"))),
                            "confidence": 0.95,
                            "reason": f"OCR为空/等待触发兜底，DOM定位到{meta.get('hit', meta.get('tag', '元素'))}",
                            "source": "dom_fallback",
                        }

                # 3.3.2 语义兜底：连续 wait 未匹配、DOM 兜底也找不到、且无视频时，
                #        让 VLM 判断页面上有没有"推进按钮"（引导语/图片按钮）。
                is_unmatched_wait = (
                    decision_result.get("action") == "wait"
                    and "未匹配" in decision_result.get("reason", "")
                )
                if is_unmatched_wait:
                    # 列表页（非详情页）检测：主页/课程列表需要用户选课，直接人工介入，
                    # 不走语义兜底（否则 VLM 会在课程列表上幻觉出"推进按钮"）。
                    if config.COURSE_DETAIL_URL_MARK not in (page.url or ""):
                        decision_result = {"action": "need_human",
                                           "reason": "在课程列表页，请选择要学习的课程"}
                        consecutive_wait_count = 0
                    else:
                        consecutive_wait_count += 1
                        if consecutive_wait_count >= 3:
                            video = browser.detect_video()
                            if not video.get("has_video"):
                                print(f"[语义兜底] 连续 {consecutive_wait_count} 次未匹配，让 VLM 判断推进按钮...")
                                flow.transition(FlowState.VLM_REASONING, "连续未匹配，启动语义推理")
                                semantic = decision.semantic_fallback(screenshot, ocr_results, page.url)
                                if semantic.get("action") in ("click", "need_human"):
                                    decision_result = semantic
                                    consecutive_wait_count = 0
                else:
                    # 决策不是"未匹配 wait"（已匹配到按钮准备点击/其它动作），
                    # 说明未匹配状态解除，重置计数
                    consecutive_wait_count = 0

                # 统一的人工门禁：非 VLM 产生的 need_human，在 VLM 可用时必须先推理。
                if (decision_result.get("action") == "need_human"
                        and decision_result.get("source") not in ("vlm", "vlm_unavailable")):
                    original_reason = decision_result.get("reason", "当前页面无法可靠自动处理")
                    reasoned = _vlm_before_human(
                        flow, decision, screenshot, ocr_results, page.url, original_reason)
                    # 非课程详情页需要用户选择课程；VLM只观察和解释，不自动选项目。
                    if (config.COURSE_DETAIL_URL_MARK not in (page.url or "")
                            and reasoned.get("action") == "click"):
                        decision_result = {
                            "action": "need_human",
                            "reason": f"{original_reason}；VLM已完成观察，非课程详情页不自动选择项目",
                            "source": "vlm",
                        }
                    else:
                        decision_result = reasoned

                # 3.4 通用安全校验（URL 白名单 S1）
                viewport = browser.get_viewport_size()
                ok, reason = sandbox.check_all(page)
                if not ok:
                    logger.log(step=page_count, action="blocked",
                               details={"page_url": page.url, "reason": reason})
                    break  # URL 偏离白名单，终止脚本

                # 3.5 执行操作
                action = decision_result.get("action")
                if action == "click":
                    candidates = decision_result.get("candidates")
                    if not candidates:
                        candidates = [{
                            "x": decision_result["x"], "y": decision_result["y"],
                            "target": decision_result.get("target", "unknown"),
                            "confidence": decision_result.get("confidence", 0),
                        }]

                    # 输出本次点击的全部候选内容（调试/分析用）：
                    # 候选 = 关键词过滤命中的 OCR 文字（最多 3 个）。
                    # 未命中任何关键词的按钮（如"点击翻转"）不会出现在这里，
                    # 此时应检查 config.TARGET_BUTTONS 是否覆盖了该按钮关键词。
                    print(f"[候选] 本次点击候选 {len(candidates)} 个:")
                    for _i, _c in enumerate(candidates, 1):
                        print(f"       {_i}. \"{_c.get('target')}\" @ "
                              f"({_c.get('x')},{_c.get('y')}) "
                              f"置信度: {_c.get('confidence', 0):.2f}")

                    # 保留最新版候选池的排序结果，但一次观察只操作一个候选。
                    available = [c for c in candidates
                                 if _candidate_key(c) not in failed_candidates]
                    if not available:
                        if decision_result.get("source") == "vlm":
                            human_reason = "VLM选择了已验证无效的候选，无法继续可靠操作"
                            flow.transition(FlowState.HUMAN, human_reason)
                            logger.log(step=page_count, action="need_human",
                                       details={"page_url": page.url,
                                                "reason": human_reason})
                            print(f"[需人工介入] {human_reason}")
                            _manual_wait(browser, page.url)
                            failed_candidates.clear()
                            no_progress_count = 0
                            continue
                        force_vlm_reason = "当前页面的视觉候选均已验证无效"
                        browser.wait(random.randint(700, 1300))
                        continue

                    cand = available[0]
                    x, y = cand["x"], cand["y"]
                    ok, reason = sandbox.validate_coordinates(x, y, viewport[0], viewport[1])
                    if not ok:
                        failed_candidates.add(_candidate_key(cand))
                        continue
                    ok, reason = sandbox.validate_rate_limit()
                    if not ok:
                        browser.wait(random.randint(900, 1500))
                        continue
                    ok, reason = sandbox.validate_operation_count()
                    if not ok:
                        flow.transition(FlowState.ERROR, reason)
                        break

                    flow.transition(FlowState.ACT, f"点击候选：{cand.get('target', 'unknown')}")
                    changed, why = browser.click_and_verify(
                        x, y, before_image=screenshot, prev_url=page.url)
                    flow.transition(FlowState.VERIFY, f"点击结果：{why}")
                    logger.log(step=page_count, action="click", details={
                        "page_url": page.url,
                        "target": cand.get("target", "unknown"),
                        "x": x, "y": y,
                        "confidence": cand.get("confidence", 0),
                        "source": decision_result.get("source", "ocr_or_vlm"),
                        "result": why,
                        "candidates": [{
                            "target": _c.get("target"),
                            "x": _c.get("x"), "y": _c.get("y"),
                            "confidence": _c.get("confidence", 0),
                        } for _c in candidates],
                    })

                    if changed:
                        print(f"[点击生效] 检测到 {why}")
                        no_progress_count = 0
                        consecutive_wait_count = 0
                        failed_candidates.clear()
                        browser.wait(int(random.uniform(
                            config.MIN_DELAY_SEC, config.MAX_DELAY_SEC) * 1000))
                    else:
                        failed_candidates.add(_candidate_key(cand))
                        no_progress_count += 1
                        logger.log(step=page_count, action="click_no_effect",
                                   details={"page_url": page.url,
                                            "target": cand.get("target", "unknown"),
                                            "no_progress_count": no_progress_count})
                        if decision_result.get("source") == "vlm":
                            # VLM已经完成推理且目标验证失败，可以直接进入人工，不再循环调用VLM。
                            human_reason = "VLM给出的目标点击后没有产生页面变化"
                            flow.transition(FlowState.HUMAN, human_reason)
                            logger.log(step=page_count, action="need_human",
                                       details={"page_url": page.url,
                                                "reason": human_reason})
                            print("[需人工介入] VLM目标未产生页面变化，请手动完成本页。")
                            _manual_wait(browser, page.url)
                            failed_candidates.clear()
                            no_progress_count = 0
                            continue
                        else:
                            if not any(_candidate_key(c) not in failed_candidates
                                       for c in candidates):
                                force_vlm_reason = "所有视觉候选均未生效"
                        browser.wait(random.randint(700, 1400))
                        continue

                elif action == "wait":
                    reason = decision_result.get("reason", "")
                    flow.transition(FlowState.WAIT, reason or "等待页面变化")
                    # 视频页检测：OCR 匹配不到目标时，可能页面里嵌了视频播放器
                    # （播放按钮是图形图标 OCR 识别不到；播放中画面无文字按钮）。
                    if "未匹配" in reason:
                        video = browser.detect_video()
                        if video.get("has_video"):
                            if video.get("playing"):
                                # 视频正在播放：不打扰，等待播放结束，播放完出现按钮后自动继续
                                logger.log(step=page_count, action="video_playing",
                                           details={"page_url": page.url})
                                browser.wait(10000)
                                continue
                            # 未播放：先尝试自动播放，失败则提醒用户手动点播放
                            played = browser.try_play_video()
                            if played.get("playing"):
                                print("[视频] 已自动触发播放，等待播放结束...")
                                logger.log(step=page_count, action="video_playing",
                                           details={"page_url": page.url, "auto_play": True})
                                browser.wait(10000)
                                continue
                            # 下一轮用最新截图先请求 VLM；VLM仍无法定位时才进入 HUMAN。
                            force_vlm_reason = "检测到视频，但可见播放控件无法通过浏览器输入启动"
                            continue
                    logger.log(step=page_count, action="wait",
                               details={"page_url": page.url, "reason": reason})
                    browser.wait(5000)

                elif action == "need_human":
                    flow.transition(FlowState.HUMAN,
                                    decision_result.get("reason", "需要人工处理"))
                    # 检测到题目但 VLM 无法确定答案：提醒用户手动介入，
                    # 并监听 next API / URL 变化自动感知"用户已操作完成"。
                    logger.log(step=page_count, action="need_human",
                               details={"page_url": page.url,
                                        "reason": decision_result.get("reason")})
                    print("\n" + "=" * 60)
                    print("[需人工介入] 检测到题目但系统无法确定答案。")
                    print(f"原因: {decision_result.get('reason', '未知')}")
                    print("请在浏览器中手动完成此题，脚本检测到翻页后会自动继续（按 Ctrl+C 可退出）。")
                    prev_need_url = page.url
                    changed, why = browser.wait_for_progress(timeout_ms=180000, prev_url=prev_need_url)
                    if changed and why == "user_enter":
                        print("[继续] 用户按 Enter 唤醒，立即重新识别当前页面。")
                    elif changed:
                        print(f"[继续] 检测到 {why}，页面已变化，继续自动处理。")
                        logger.log(step=page_count, action="human_done", details={"reason": why})
                    else:
                        print("[提示] 等待超时，继续循环检测...")
                    browser.wait_for_network_idle(timeout=10000)
                    browser.wait(2000)
                    continue

                elif action == "error":
                    flow.transition(FlowState.ERROR,
                                    decision_result.get("reason", "未知错误"))
                    logger.log(step=page_count, action="error",
                               details={"page_url": page.url, "reason": decision_result.get("reason")})
                    break

                elif action == "terminate":
                    flow.transition(FlowState.COMPLETE, "检测到课程完成")
                    logger.log(step=page_count, action="terminated",
                               details={"page_url": page.url})
                    # 正常完成：不退出，等待用户打开下一节网课
                    new_url = _wait_for_next_lesson(browser, page.url)
                    prev_url = new_url
                    no_progress_count = 0
                    continue

                page_count += 1
            except KeyboardInterrupt:
                raise
            except Exception as e:
                # 浏览器崩溃等异常：尝试重新导航到当前 URL 恢复，最多 3 次
                current_url = getattr(page, "url", "") or course_url
                logger.log(step=page_count, action="error",
                           details={"page_url": current_url, "reason": f"主循环异常: {e}"})
                recovered = False
                for _ in range(3):
                    try:
                        page = browser.navigate(current_url)
                        recovered = True
                        break
                    except Exception:
                        browser.wait(2000)
                if not recovered:
                    break
    finally:
        # 4. 清理资源
        browser.close()
        logger.log(step=page_count, action="shutdown",
                   details={"total_pages": page_count})
        logger.close()


if __name__ == "__main__":
    args = parse_args()
    try:
        main(args.course_url, enable_vlm=not args.no_vlm)
    except KeyboardInterrupt:
        print("\n[中断] 用户按 Ctrl+C 停止，浏览器已关闭，日志已保存。")
        sys.exit(0)
