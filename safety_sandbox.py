#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""模块 4：SafetySandbox —— 安全沙箱（PRD 第三节 模块4）"""

import hashlib
import io
import time
from urllib.parse import urlparse


class SafetySandbox:
    def __init__(self, config=None):
        self.config = config
        self.operation_count = 0
        self.last_operation_time = 0
        self.history_hashes = []

    def validate_url(self, current_url):
        # 域名白名单校验
        try:
            domain = urlparse(current_url).netloc.split(":")[0]
        except Exception:
            return (False, f"URL解析失败: {current_url}")
        if domain not in self.config.ALLOWED_DOMAINS:
            return (False, f"URL偏离白名单: {domain}")
        return (True, "")

    def validate_coordinates(self, x, y, viewport_width, viewport_height):
        # 坐标边界校验
        if not (0 < x < viewport_width and 0 < y < viewport_height):
            return (False, f"坐标越界: ({x}, {y})")
        return (True, "")

    def validate_rate_limit(self):
        # 操作频率限制校验
        now = time.time()
        if self.last_operation_time > 0:
            elapsed = now - self.last_operation_time
            if elapsed < self.config.MIN_DELAY_SEC:
                return (False, "操作过于频繁")
            if elapsed >= self.config.MAX_DELAY_SEC:
                # 间隔偏大：可能之前卡住，仅记录警告
                pass
        self.last_operation_time = now
        return (True, "")

    def validate_operation_count(self):
        # 操作上限校验
        self.operation_count += 1
        if self.operation_count > self.config.MAX_CLICKS_PER_RUN:
            return (False, "超过最大操作次数")
        return (True, f"操作次数: {self.operation_count}/{self.config.MAX_CLICKS_PER_RUN}")

    def validate_no_repeat(self, screenshot_hash):
        # 重复操作检测：连续 3 次截图 hash 相同视为死循环
        self.history_hashes.append(screenshot_hash)
        if len(self.history_hashes) > 5:
            self.history_hashes = self.history_hashes[-5:]
        if len(self.history_hashes) >= 3 and len(set(self.history_hashes[-3:])) == 1:
            return (False, "连续操作后页面无变化，可能陷入死循环")
        return (True, "")

    def check_all(self, page):
        # 每次循环只做 URL 白名单校验（S1）。
        # 操作频率（S3）/ 坐标（S2）/ 操作次数（S4）/ 重复检测（S5）
        # 都放在真正"点击"前由主循环单独调用，避免"等待"循环被频率校验误拦截。
        ok, reason = self.validate_url(page.url)
        if not ok:
            return (False, reason)
        return (True, "")

    def hash_image(self, image):
        # 公开方法：计算截图 PNG 字节的 MD5，供重复检测（S5）使用
        buf = io.BytesIO()
        image.save(buf, format="PNG")
        return hashlib.md5(buf.getvalue()).hexdigest()
