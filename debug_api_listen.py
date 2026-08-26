#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""验证 wait_for_progress 的 API 监听能力（page.on 版本）。

用 setTimeout 触发导航/图片请求（一定发出），验证 page.on("request") 能否捕获
本地配置的推进 API 特征（config_platform.py 的 PROGRESS_API_MARKS）。

用法：
    python debug_api_listen.py
"""

import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import config  # noqa: E402
from browser_controller import BrowserController  # noqa: E402


def main():
    if not config.PROGRESS_API_MARKS:
        print("[错误] config_platform.py 未配置 PROGRESS_API_MARKS，无法验证 API 监听。")
        print("       请先运行 python setup_local.py 填写 API 特征。")
        return

    browser = BrowserController(channel=config.BROWSER_CHANNEL, headless=True)
    try:
        browser.page.goto("about:blank")

        # 验证 1：setTimeout 触发 <img>（用配置的第一个 URL 特征构造请求）
        marks = config.PROGRESS_API_MARKS
        first_url_mark = marks[0]["url_marks"][0]
        first_name = marks[0].get("name", "?")
        browser.page.evaluate(f"""
        setTimeout(() => {{
          const img = document.createElement('img');
          img.src = 'https://{config.PLATFORM_DOMAIN}/api/{first_url_mark}/v1/next';
          document.body.appendChild(img);
        }}, 1500);
        """)
        print(f"[验证1] 已安排 img 触发 {first_url_mark}，开始等待...")
        changed, why = browser.wait_for_progress(timeout_ms=8000, prev_url=None)
        print(f"[验证1] 结果: 捕获={changed}, 原因={why}")

        # 验证 2：fetch POST 触发 body 特征（body 含配置的 body_marks）
        second_mark = marks[1] if len(marks) > 1 else None
        if second_mark and second_mark.get("body_marks"):
            body_mark = second_mark["body_marks"][0]
            second_name = second_mark.get("name", "?")
            body = "service=xxx.xxx." + body_mark + "&answers=%5B1%5D&questionId=abc"
            browser.page.evaluate(f"""
            setTimeout(() => {{
              fetch('https://{config.PLATFORM_DOMAIN}/router', {{
                method: 'POST',
                mode: 'no-cors',
                headers: {{'Content-Type': 'application/x-www-form-urlencoded'}},
                body: {body!r}
              }}).catch(e => {{}});
            }}, 1500);
            """)
            print(f"[验证2] 已安排 {body_mark} POST，开始等待...")
            changed2, why2 = browser.wait_for_progress(timeout_ms=8000, prev_url=None)
            print(f"[验证2] 结果: 捕获={changed2}, 原因={why2}")
        else:
            changed2, why2, second_name = False, "跳过", "?"

        print("\n" + "=" * 60)
        print("验证汇总：")
        print(f"  1. {first_name}({first_url_mark}) 捕获={changed}  {'通过' if changed else '失败'}")
        print(f"  2. {second_name} 捕获={changed2} {'通过' if changed2 else '失败'}")
    finally:
        browser.close()


if __name__ == "__main__":
    main()
