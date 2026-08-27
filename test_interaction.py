#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""浏览器观察与输入层回归测试，不启动 OCR/VLM。"""

import unittest
from pathlib import Path

from playwright.sync_api import sync_playwright

import config
from browser_controller import BrowserController
from flow_state import FlowState, FlowStateMachine


class FlowStateTests(unittest.TestCase):
    def test_normal_path_and_vlm_before_human(self):
        flow = FlowStateMachine()
        for state in (
                FlowState.OBSERVE, FlowState.DECIDE, FlowState.ACT,
                FlowState.VERIFY, FlowState.OBSERVE, FlowState.DECIDE,
                FlowState.VLM_REASONING, FlowState.HUMAN):
            flow.transition(state)
        self.assertEqual(flow.state, FlowState.HUMAN)

    def test_illegal_direct_boot_to_human_is_rejected(self):
        with self.assertRaises(RuntimeError):
            FlowStateMachine().transition(FlowState.HUMAN)


class BrowserInteractionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pw = sync_playwright().start()
        cls.browser = cls.pw.chromium.launch(
            channel=config.BROWSER_CHANNEL, headless=True)
        cls.context = cls.browser.new_context(
            viewport={"width": 414, "height": 896},
            is_mobile=True, has_touch=True)
        cls.page = cls.context.new_page()
        cls.controller = BrowserController.__new__(BrowserController)
        cls.controller.page = cls.page
        cls.controller.viewport_width = 414
        cls.controller.viewport_height = 896
        cls.controller.is_mobile = True

    @classmethod
    def tearDownClass(cls):
        cls.context.close()
        cls.browser.close()
        cls.pw.stop()

    def test_img_next_must_be_active_and_visible(self):
        self.page.set_content("""
          <style>.page{display:none}.page.active{display:block}</style>
          <section class='page'><img class='btn-next' style='width:80px;height:40px'></section>
          <section class='page active'>
            <img id='target' class='btn-next' style='display:none;width:80px;height:40px'>
          </section>
        """)
        self.assertIsNone(self.controller.find_next_button())
        self.page.evaluate("document.querySelector('#target').style.display='block'")
        found = self.controller.find_next_button()
        self.assertIsNotNone(found)
        self.assertEqual(found[1]["tag"], "IMG")

    def test_browser_input_is_single_and_trusted(self):
        self.page.set_content("""
          <button id='target' style='width:160px;height:80px'>按钮</button>
          <script>
            window.clicks = [];
            target.addEventListener('click', e => clicks.push(e.isTrusted));
          </script>
        """)
        box = self.page.locator("#target").bounding_box()
        self.assertTrue(self.controller.click(
            box["x"] + box["width"] / 2,
            box["y"] + box["height"] / 2))
        self.assertEqual(self.page.evaluate("window.clicks"), [True])

    def test_progress_requires_request_and_response(self):
        old_marks = config.PROGRESS_API_MARKS
        config.PROGRESS_API_MARKS = [{"name": "测试", "url_marks": ["/progress/next"]}]
        try:
            self.page.route("**/progress/next", lambda route: route.fulfill(status=204))
            self.page.set_content("""
              <button id='target' style='width:160px;height:80px'
                onclick="fetch('https://course.test/progress/next', {method:'POST'})">下一页</button>
            """)
            box = self.page.locator("#target").bounding_box()
            changed, reason = self.controller.click_and_verify(
                box["x"] + box["width"] / 2,
                box["y"] + box["height"] / 2,
                timeout_ms=2000)
            self.assertTrue(changed)
            self.assertTrue(reason.startswith("progress_response:"), reason)
        finally:
            self.page.unroute("**/progress/next")
            config.PROGRESS_API_MARKS = old_marks

    def test_text_fallback_finds_course_list_return_inside_iframe(self):
        self.page.set_content("""
          <iframe id="course" style="width:390px;height:500px;border:0"
            srcdoc="<button style='margin-top:300px;width:240px;height:60px'>返回课程列表</button>">
          </iframe>
        """)
        self.page.wait_for_timeout(100)
        found = self.controller.find_text_element_center(["返回课程列表"])
        self.assertIsNotNone(found)
        self.assertTrue(found[1].get("frame"))
        self.assertIn("返回课程列表", found[1]["text"])

    def test_course_selector_chooses_first_unpassed_required_course(self):
        self.page.set_content("""
          <style>
            [role=tab], .van-collapse-item__title, .img-texts-item {
              display:block; width:360px; min-height:48px; margin:4px;
            }
          </style>
          <div role="tab" aria-selected="true" class="van-tab van-tab--active">
            <span class="completion"><em>1</em>/3</span><span class="name">必修课</span>
          </div>
          <div role="tab"><span class="completion"><em>0</em>/60</span>
            <span class="name">选修课</span></div>
          <div role="tab"><span class="completion"><em>0</em>/1</span>
            <span class="name">在线考试</span></div>
          <section class="van-collapse-item">
            <div class="van-collapse-item__title" aria-expanded="true">
              <span class="text">防范诈骗</span><span class="count"><b>1</b>/2</span>
            </div>
            <ul>
              <li class="img-texts-item passed"><h5 class="title">绿色角标课程</h5></li>
              <li class="img-texts-item"><h5 class="title">未完成必修课</h5></li>
            </ul>
          </section>
          <section class="elective"><li class="img-texts-item">
            <h5 class="title">选修课不应被选择</h5></li></section>
        """)
        result = self.controller.find_unfinished_required_course()
        self.assertEqual(result["action"], "click")
        self.assertEqual(result["selector_action"], "select_course")
        self.assertEqual(result["target"], "未完成必修课")
        self.assertEqual(result["category"], "防范诈骗")

    def test_course_selector_uses_top_to_bottom_page_order(self):
        self.page.set_content("""
          <style>
            [role=tab], .van-collapse-item__title, .img-texts-item {
              display:block; width:360px; min-height:48px; margin:4px;
            }
          </style>
          <div role="tab" aria-selected="true" class="van-tab--active">
            <span class="completion">1/5</span><span class="name">必修课</span>
          </div>
          <section class="van-collapse-item">
            <div class="van-collapse-item__title" aria-expanded="true">
              <span class="text">上方未完成分类</span><span class="count">1/3</span>
            </div>
            <li class="img-texts-item"><h5 class="title">最上方未完成课程</h5></li>
            <li class="img-texts-item"><h5 class="title">第二门未完成课程</h5></li>
            <li class="img-texts-item passed"><h5 class="title">已完成课程</h5></li>
          </section>
          <section class="van-collapse-item">
            <div class="van-collapse-item__title" aria-expanded="true">
              <span class="text">下方未完成分类</span><span class="count">0/1</span>
            </div>
            <li class="img-texts-item"><h5 class="title">下方分类课程</h5></li>
          </section>
        """)
        result = self.controller.find_unfinished_required_course()
        self.assertEqual(result["action"], "click")
        self.assertEqual(result["category"], "上方未完成分类")
        self.assertEqual(result["target"], "最上方未完成课程")
        self.assertEqual(result["category_order"], 1)
        self.assertEqual(result["course_order"], 1)

    def test_course_selector_expands_incomplete_category_first(self):
        self.page.set_content("""
          <div role="tab" aria-selected="true" class="van-tab--active"
               style="height:50px;width:360px">
            <span class="completion">22/60</span><span class="name">必修课</span>
          </div>
          <section class="van-collapse-item">
            <div class="van-collapse-item__title" aria-expanded="false"
                 style="height:60px;width:360px">
              <span class="text">安全文化</span><span class="count">2/2</span>
            </div>
          </section>
          <section class="van-collapse-item">
            <div class="van-collapse-item__title" aria-expanded="false"
                 style="height:60px;width:360px">
              <span class="text">防范诈骗</span><span class="count">15/22</span>
            </div>
          </section>
        """)
        result = self.controller.find_unfinished_required_course()
        self.assertEqual(result["action"], "click")
        self.assertEqual(result["selector_action"], "expand_category")
        self.assertEqual(result["target"], "防范诈骗")

    def test_course_selector_switches_back_to_required_tab(self):
        self.page.set_content("""
          <div role="tab" style="height:60px;width:120px">
            <span class="completion">22/60</span><span class="name">必修课</span>
          </div>
          <div role="tab" aria-selected="true" class="van-tab--active"
               style="height:60px;width:120px">
            <span class="completion">0/60</span><span class="name">选修课</span>
          </div>
          <div role="tab" style="height:60px;width:120px">
            <span class="completion">0/1</span><span class="name">在线考试</span>
          </div>
        """)
        result = self.controller.find_unfinished_required_course()
        self.assertEqual(result["action"], "click")
        self.assertEqual(result["selector_action"], "activate_required_tab")
        self.assertEqual(result["target"], "必修课")

    def test_course_selector_stops_when_required_courses_complete(self):
        self.page.set_content("""
          <div role="tab" style="height:60px;width:120px">
            <span class="completion">60/60</span><span class="name">必修课</span>
          </div>
          <div role="tab" aria-selected="true" class="van-tab--active"
               style="height:60px;width:120px">
            <span class="completion">0/60</span><span class="name">选修课</span>
          </div>
        """)
        result = self.controller.find_unfinished_required_course()
        self.assertEqual(result["action"], "complete")
        self.assertIn("60/60", result["reason"])

    def test_course_selector_rejects_inconsistent_category_state(self):
        self.page.set_content("""
          <div role="tab" aria-selected="true" class="van-tab--active"
               style="height:60px;width:360px">
            <span class="completion">1/3</span><span class="name">必修课</span>
          </div>
          <section class="van-collapse-item">
            <div class="van-collapse-item__title" aria-expanded="true"
                 style="height:60px;width:360px">
              <span class="text">防范诈骗</span><span class="count">1/2</span>
            </div>
            <li class="img-texts-item passed" style="height:60px;width:360px">
              <h5 class="title">已完成课程</h5>
            </li>
          </section>
        """)
        result = self.controller.find_unfinished_required_course()
        self.assertEqual(result["action"], "need_human")
        self.assertIn("没有找到无绿色角标", result["reason"])

    def test_test_page_orders_simple_then_unlocked_image(self):
        self.page.goto(Path("test_page.html").resolve().as_uri())
        self.page.locator("#page-1 .btn").click()
        self.page.locator("#page-2 .btn").click()
        self.page.wait_for_selector("#page-2-image.active")

        visible_next = self.controller.find_next_button()
        self.assertIsNotNone(visible_next)
        (x, y), meta = visible_next
        self.assertEqual(meta["tag"], "IMG")
        self.assertTrue(self.controller.click(x, y))
        self.page.wait_for_selector("#page-3.active")

        # 前置卡片未完成时，DOM 中虽已有 img.btn-next，但必须视为不可操作。
        self.assertIsNone(self.controller.find_next_button())
        cards = self.page.locator("#page-3 .card-item")
        for index in range(cards.count()):
            cards.nth(index).click()
        unlocked_next = self.controller.find_next_button()
        self.assertIsNotNone(unlocked_next)
        self.assertEqual(unlocked_next[1]["tag"], "IMG")


if __name__ == "__main__":
    unittest.main()
