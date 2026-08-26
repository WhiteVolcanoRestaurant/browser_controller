#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""模块 5：VLMClient —— 封装与本地 Ollama 的 VLM 通信（PRD 第三节 模块5）"""

import base64
import json
import re

import requests

import config


class VLMClient:
    def __init__(self, base_url=None, model=None, timeout=None):
        self.base_url = (base_url or config.OLLAMA_BASE_URL).rstrip("/")
        self.model = model or config.OLLAMA_MODEL
        self.timeout = timeout or config.VLM_TIMEOUT

    def check_health(self):
        # 检查 /api/tags 返回的模型列表是否包含 self.model
        try:
            resp = requests.get(f"{self.base_url}/api/tags", timeout=10)
            data = resp.json()
            names = [m.get("name", "") for m in data.get("models", [])]
            return any(self.model in n or n.startswith(self.model) for n in names)
        except Exception:
            return False

    def ask(self, screenshot_path, prompt):
        # 读取截图转 base64，POST /api/chat 获取纯文本回复
        with open(screenshot_path, "rb") as f:
            b64 = base64.b64encode(f.read()).decode("utf-8")
        payload = {
            "model": self.model,
            "messages": [
                {"role": "user", "content": prompt, "images": [b64]}
            ],
            "stream": False,
            "format": "json",
            "options": {"temperature": 0.1, "num_predict": 512},
        }
        resp = requests.post(f"{self.base_url}/api/chat", json=payload, timeout=self.timeout)
        resp.raise_for_status()
        return resp.json()["message"]["content"]

    def parse_decision(self, response_text):
        # 从 VLM 返回文本中解析 JSON 决策，失败返回 error
        m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", response_text, re.DOTALL)
        if not m:
            m = re.search(r"(\{.*\})", response_text, re.DOTALL)
        if not m:
            return {"action": "error", "reason": "JSON解析失败"}
        try:
            data = json.loads(m.group(1))
        except Exception:
            return {"action": "error", "reason": "JSON解析失败"}
        if "action" not in data or "confidence" not in data:
            return {"action": "error", "reason": "缺少必需字段"}
        # VLM 不再输出坐标：click 时校验 target_text 非空，坐标由 OCR 反查
        if data["action"] == "click" and not (data.get("target_text") or "").strip():
            return {"action": "error", "reason": "click缺少target_text"}
        return data
