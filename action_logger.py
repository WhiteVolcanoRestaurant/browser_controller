#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""模块 6：ActionLogger —— 操作日志器（PRD 第三节 模块6）"""

import json
import os
from datetime import datetime, timezone


class ActionLogger:
    def __init__(self, log_file="./logs/action_log.jsonl"):
        self.log_file = log_file
        os.makedirs(os.path.dirname(os.path.abspath(log_file)), exist_ok=True)
        self._fh = open(log_file, "a", encoding="utf-8")

    def log(self, step, action, details):
        # 追加写入一行 JSON 日志，同时打印到控制台
        details = dict(details or {})
        page_url = details.pop("page_url", None)
        if page_url is None:
            page_url = details.pop("url", "")
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "step": step,
            "action": action,
            "page_url": page_url,
            "details": details,
        }
        line = json.dumps(entry, ensure_ascii=False)
        self._fh.write(line + "\n")
        self._fh.flush()
        print(line)

    def close(self):
        try:
            self._fh.close()
        except Exception:
            pass
