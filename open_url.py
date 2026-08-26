#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
最小框架：只打开目标 URL，并复用 edge_profile 中的登录状态（无需重新登录）。
不包含任何逻辑判断、点击、监听等功能。
运行后浏览器保持打开，直到手动关闭窗口或按 Ctrl+C 退出。
"""
import asyncio
import os
import sys

from playwright.async_api import async_playwright

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import config  # noqa: E402

TARGET_URL = config.TARGET_URL  # 默认主页在本地 config_platform.py 中配置
EDGE_CHANNEL = "msedge"  # 使用本地 Microsoft Edge
PROFILE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "edge_profile")


async def main():
    async with async_playwright() as p:
        # 持久化上下文：复用 edge_profile 的登录状态
        context = await p.chromium.launch_persistent_context(
            user_data_dir=PROFILE_DIR,
            channel=EDGE_CHANNEL,
            headless=False,
        )
        page = context.pages[0] if context.pages else await context.new_page()
        await page.goto(TARGET_URL, wait_until="domcontentloaded", timeout=60000)
        print(f"已打开: {page.url}")
        # 保持浏览器打开，不做任何其它操作
        while True:
            await asyncio.sleep(3600)


if __name__ == "__main__":
    asyncio.run(main())
