#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""可视化统计台账：解析 logs/action_log.jsonl 生成 logs/report.html。

用法：
    python report.py

产物：
    logs/report.html —— 浏览器打开即可查看统计概览 + 困难样本（带截图）。

困难样本判定：
    1. click_no_effect —— 点击后页面无变化（点到了但没生效）
    2. blocked —— 被安全沙箱拦截（坐标越界 / 死循环 / 频率超限）
    3. 连续 >=2 次 wait 且 reason 含"未匹配到任何目标" —— OCR 识别到文字、
       但反复匹配不到任何按钮（正是"人类觉得可点、脚本不认识"的难点）
"""

import json
import os
from collections import Counter
from datetime import datetime

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
LOG_DIR = os.path.join(PROJECT_ROOT, "logs")
LOG_FILE = os.path.join(LOG_DIR, "action_log.jsonl")
OUT_FILE = os.path.join(LOG_DIR, "report.html")


def load_events():
    events = []
    if not os.path.exists(LOG_FILE):
        return events
    with open(LOG_FILE, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                events.append(json.loads(line))
            except Exception:
                continue
    return events


def _basename(path):
    return os.path.basename(path) if path else None


def _nearest_ocr(events, idx):
    """从 idx 向前找最近的 ocr 事件，返回 (texts, screenshot_path)。"""
    texts, screenshot = [], None
    for k in range(idx, max(-1, idx - 12), -1):
        d = events[k].get("details") or {}
        if d.get("screenshot") and screenshot is None:
            screenshot = d["screenshot"]
        if d.get("texts") and not texts:
            texts = d["texts"]
        if texts and screenshot:
            break
    return texts, screenshot


def analyze(events):
    counter = Counter(e.get("action") for e in events)

    hard = []
    seen = set()

    def add(kind, reason, texts, screenshot, step, ts, vlm_raw=None):
        key = (kind, "|".join(sorted(texts)) if texts else "")
        if key in seen:
            return
        seen.add(key)
        hard.append({
            "kind": kind,
            "reason": reason,
            "texts": texts,
            "screenshot": _basename(screenshot),
            "step": step,
            "ts": ts,
            "vlm_raw": vlm_raw,
        })

    def _is_fail(e):
        a = e.get("action")
        r = (e.get("details") or {}).get("reason", "")
        return (a == "click_no_effect" or a == "blocked"
                or (a == "wait" and "未匹配" in r))

    # 先单独收集 vlm_failed（VLM 校验后仍失败 → 必然困难样本，且带 VLM 返回内容）
    for e in events:
        if e.get("action") == "vlm_failed":
            d = e.get("details") or {}
            texts, shot = d.get("ocr_texts"), None
            if not shot:
                _, shot = _nearest_ocr(events, events.index(e))
            add("VLM验证后仍失败",
                f"VLM 校验后依然无法推进：{d.get('reason', '')}",
                texts or [], shot, e.get("step"), e.get("timestamp"),
                vlm_raw=d.get("vlm_raw", ""))

    i, n = 0, len(events)
    while i < n:
        if not _is_fail(events[i]):
            i += 1
            continue

        # 累积同一页的"连续失败段"（click_no_effect / blocked / wait未匹配）
        j = i
        fail_types = []
        while j < n and _is_fail(events[j]):
            fail_types.append(events[j].get("action"))
            j += 1

        run_len = j - i
        # 只有"连续 >=2 次失败"或"包含点击无效"才算困难样本（单个 wait 不算，避免误报）
        if run_len >= 2 or "click_no_effect" in fail_types:
            texts, shot = _nearest_ocr(events, j - 1)
            if "click_no_effect" in fail_types:
                target = "?"
                for k in range(i, j):
                    if events[k].get("action") == "click_no_effect":
                        target = (events[k].get("details") or {}).get("target", "?")
                        break
                kind = "反复点击无效"
                reason = f"同一页反复点击「{target}」无效果（连续 {run_len} 次失败）"
            elif "blocked" in fail_types:
                kind = "被拦截"
                reason = (events[j - 1].get("details") or {}).get("reason", "被安全沙箱拦截")
            else:
                kind = "识别不到目标"
                reason = "OCR 识别到文字但反复未匹配到任何按钮（疑似换行/图标按钮）"
            add(kind, reason, texts, shot, events[i].get("step"), events[i].get("timestamp"))
        i = j

    return counter, hard


def _fmt_ts(ts):
    try:
        dt = datetime.fromisoformat(ts)
        return dt.strftime("%H:%M:%S")
    except Exception:
        return ts or ""


def render_html(counter, hard):
    total = sum(counter.values())
    stat_items = [
        ("总事件", total),
        ("点击", counter.get("click", 0)),
        ("点击无效", counter.get("click_no_effect", 0)),
        ("等待", counter.get("wait", 0)),
        ("被拦截", counter.get("blocked", 0)),
        ("人工介入", counter.get("need_human", 0)),
        ("完成/终止", counter.get("completed", 0) + counter.get("terminated", 0)),
        ("困难样本", len(hard)),
    ]

    cards = "\n".join(
        f'<div class="stat"><div class="num">{v}</div><div class="label">{k}</div></div>'
        for k, v in stat_items
    )

    if hard:
        rows = []
        for s in hard:
            texts_html = "、".join(s["texts"][:12]) if s["texts"] else "（无 OCR 文字）"
            img_html = (
                f'<img src="{s["screenshot"]}" alt="截图" loading="lazy">'
                if s["screenshot"] else '<div class="noimg">无截图</div>'
            )
            vlm_html = ""
            if s.get("vlm_raw"):
                vlm_raw_escaped = (s["vlm_raw"].replace("&", "&amp;").replace("<", "&lt;")
                                   .replace(">", "&gt;"))
                vlm_html = (
                    f'<div class="vlmraw"><div class="vlmraw-title">VLM 返回内容：</div>'
                    f'<pre>{vlm_raw_escaped}</pre></div>'
                )
            rows.append(
                f'<div class="sample">'
                f'<div class="shot">{img_html}</div>'
                f'<div class="meta">'
                f'<div class="badge">{s["kind"]}</div>'
                f'<div class="why">原因：{s["reason"]}</div>'
                f'<div class="ts">step {s["step"]} · {_fmt_ts(s["ts"])}</div>'
                f'<div class="texts">{texts_html}</div>'
                f'{vlm_html}'
                f'</div></div>'
            )
        samples_html = "\n".join(rows)
    else:
        samples_html = '<div class="empty">没有识别到困难样本，运行状态良好。</div>'

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>课程自动化脚本 · 可视化台账</title>
<style>
  * {{ box-sizing: border-box; }}
  body {{ font-family: -apple-system, "PingFang SC", "Microsoft YaHei", sans-serif;
         margin: 0; background: #f5f6f8; color: #1f2329; }}
  header {{ background: #1f2329; color: #fff; padding: 20px 28px; }}
  header h1 {{ margin: 0 0 4px; font-size: 20px; }}
  header p {{ margin: 0; color: #9aa0a6; font-size: 13px; }}
  .wrap {{ max-width: 1100px; margin: 20px auto; padding: 0 20px; }}
  .stats {{ display: flex; flex-wrap: wrap; gap: 12px; margin-bottom: 24px; }}
  .stat {{ background: #fff; border-radius: 12px; padding: 16px 20px; min-width: 110px;
           box-shadow: 0 1px 4px rgba(0,0,0,.06); }}
  .stat .num {{ font-size: 26px; font-weight: 700; }}
  .stat .label {{ color: #6b7280; font-size: 13px; margin-top: 2px; }}
  h2 {{ font-size: 17px; margin: 24px 0 12px; }}
  .sample {{ display: flex; gap: 16px; background: #fff; border-radius: 12px; padding: 14px;
             box-shadow: 0 1px 4px rgba(0,0,0,.06); margin-bottom: 14px; }}
  .shot img {{ width: 160px; border-radius: 8px; border: 1px solid #e5e7eb; }}
  .noimg {{ width: 160px; height: 100px; display: flex; align-items: center; justify-content: center;
            background: #f3f4f6; border-radius: 8px; color: #9ca3af; font-size: 12px; }}
  .meta {{ flex: 1; }}
  .badge {{ display: inline-block; background: #fef2f2; color: #dc2626; border-radius: 6px;
            padding: 2px 8px; font-size: 12px; margin-bottom: 6px; }}
  .why {{ font-size: 14px; margin-bottom: 4px; }}
  .ts {{ color: #9ca3af; font-size: 12px; margin-bottom: 6px; }}
  .texts {{ color: #374151; font-size: 13px; line-height: 1.6; }}
  .vlmraw {{ margin-top: 8px; }}
  .vlmraw-title {{ color: #dc2626; font-size: 12px; margin-bottom: 4px; }}
  .vlmraw pre {{ background: #f8fafc; border: 1px solid #e5e7eb; border-radius: 6px;
                 padding: 8px; font-size: 12px; overflow-x: auto; white-space: pre-wrap;
                 word-break: break-all; color: #334155; margin: 0; }}
  .empty {{ color: #6b7280; background: #fff; border-radius: 12px; padding: 30px; text-align: center; }}
</style>
</head>
<body>
<header>
  <h1>课程自动化脚本 · 可视化台账</h1>
  <p>数据来源 logs/action_log.jsonl · 困难样本已按「识别文字」去重（相似取一张）</p>
</header>
<div class="wrap">
  <div class="stats">{cards}</div>
  <h2>困难样本（{len(hard)}）</h2>
  {samples_html}
</div>
</body>
</html>"""


def main():
    events = load_events()
    if not events:
        print(f"[report] 未找到日志: {LOG_FILE}")
        return
    counter, hard = analyze(events)
    html = render_html(counter, hard)
    with open(OUT_FILE, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"[report] 已生成台账: {OUT_FILE}")
    print(f"[report] 总事件 {sum(counter.values())}，困难样本 {len(hard)} 个")


if __name__ == "__main__":
    main()
