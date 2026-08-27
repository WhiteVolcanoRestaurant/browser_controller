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

    def test_browser_input_is_trusted_touch_and_mouse(self):
        # 点击必须走浏览器输入层（isTrusted=true），移动端 touch+mouse 双发，
        # 覆盖依赖任一事件类型的按钮（DOM 合成点击 isTrusted=false 会被风控识别）。
        # 本测试与 ENABLE_JS_CLICK_FALLBACK 无关，临时关闭该开关以验证纯可信输入。
        old_fallback = config.ENABLE_JS_CLICK_FALLBACK
        config.ENABLE_JS_CLICK_FALLBACK = False
        try:
            self.page.set_content("""
              <button id='target' style='width:160px;height:80px'>按钮</button>
              <script>
                window.seen = [];
                ['touchstart', 'mousedown', 'click'].forEach(function (t) {
                  target.addEventListener(t, function (e) { seen.push([t, e.isTrusted]); });
                });
              </script>
            """)
            box = self.page.locator("#target").bounding_box()
            self.assertTrue(self.controller.click(
                box["x"] + box["width"] / 2,
                box["y"] + box["height"] / 2))
            seen = self.page.evaluate("window.seen")
            kinds = [s[0] for s in seen]
            self.assertTrue(all(s[1] for s in seen))
            self.assertIn("touchstart", kinds)
            self.assertIn("mousedown", kinds)
            self.assertIn("click", kinds)
        finally:
            config.ENABLE_JS_CLICK_FALLBACK = old_fallback

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
