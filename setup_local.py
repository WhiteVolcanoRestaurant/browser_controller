#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
本地平台配置引导脚本（配置只留在本地，不上云）。

用法：
    python setup_local.py

流程：
1. 交互式填写：平台域名 / 主页 URL / 详情页 URL 特征 / API 特征
2. 生成 config_platform.py（已被 .gitignore 排除，不会提交到 GitHub / Gitee）

如何找到 API 特征？
- 浏览器按 F12 打开开发者工具 → Network 面板；
- 手动点击"下一页/提交答案"，观察发出的请求；
- 把接口 URL 中稳定出现的关键子串填进去（如 "your_api_mark"）。
"""

import os
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
OUT_FILE = os.path.join(BASE_DIR, "config_platform.py")


def ask(prompt, default=""):
    if default:
        prompt = f"{prompt} [{default}]"
    try:
        v = input(f"> {prompt}: ").strip()
    except (EOFError, KeyboardInterrupt):
        print("\n[已取消]")
        sys.exit(1)
    return v or default


def main():
    print("=" * 56)
    print(" 本地平台配置引导（生成 config_platform.py，不上云）")
    print("=" * 56)

    if os.path.exists(OUT_FILE):
        print(f"[提示] 已存在 {os.path.basename(OUT_FILE)}，将覆盖。")

    domain = ask("课程平台根域名（如 example.com）").strip().lower()
    if not domain:
        print("[错误] 域名不能为空，已取消。")
        sys.exit(1)

    default_url = f"https://{domain}/"
    target_url = ask("课程平台主页 URL", default_url).strip()
    detail_mark = ask("课程详情页 URL 特征（用于判断是否在详情页）", "/course/detail").strip()

    print("\n[可选] API 特征（回车跳过；不知道就留空，推进验证会退化为 URL/截图变化）")
    print("每行一组，格式： 名称 url特征 [body特征]  （空格分隔，body 可省略）")
    print("示例： 翻页 your_api_mark ；答题提交 your_api_mark your_body_mark")
    print("输入空行结束：")
    marks = []
    while True:
        line = input("> API: ").strip()
        if not line:
            break
        parts = line.split()
        if len(parts) == 2:
            marks.append({"name": parts[0], "url_marks": [parts[1]]})
        elif len(parts) >= 3:
            marks.append({"name": parts[0], "url_marks": [parts[1]], "body_marks": parts[2:]})
        else:
            print("  格式不对，请按： 名称 url特征 [body特征]")

    content = _render(domain, target_url, detail_mark, marks)
    with open(OUT_FILE, "w", encoding="utf-8") as f:
        f.write(content)

    print(f"\n[完成] 已生成 {OUT_FILE}")
    print("       该文件已被 .gitignore 排除，不会提交到仓库。")
    print("       现在可以运行： start.bat  或  python main.py")


def _render(domain, target_url, detail_mark, marks):
    header = (
        "# -*- coding: utf-8 -*-\n"
        "# 本地平台私有配置（勿提交仓库；由 setup_local.py 生成）。\n"
        "# 本文件已被 .gitignore 排除，不会上传到 GitHub / Gitee。\n\n"
    )
    body = []
    body.append(f'PLATFORM_DOMAIN = {domain!r}')
    body.append("")
    body.append(f"# 课程平台主页（程序未指定 URL 时默认打开）")
    body.append(f"TARGET_URL = {target_url!r}")
    body.append("")
    body.append("# 域名白名单（localhost/127.0.0.1 会被 config.py 强制追加）")
    body.append("ALLOWED_DOMAINS = [")
    body.append(f"    PLATFORM_DOMAIN,")
    body.append("]")
    body.append("")
    body.append("# 课程详情页 URL 特征（用于\"往回跳即结束\"与\"是否在详情页\"判断）")
    body.append(f"COURSE_DETAIL_URL_MARK = {detail_mark!r}")
    body.append("")
    body.append('# "推进生效"的 API 特征（判断点击/人工操作后页面是否真的推进了）')
    if marks:
        body.append("PROGRESS_API_MARKS = [")
        for m in marks:
            body.append("    {")
            body.append(f"        \"name\": {m['name']!r},")
            body.append(f"        \"url_marks\": [{', '.join(repr(u) for u in m['url_marks'])}],")
            if m.get("body_marks"):
                body.append(f"        \"body_marks\": [{', '.join(repr(b) for b in m['body_marks'])}],")
            body.append("    },")
        body.append("]")
    else:
        body.append("PROGRESS_API_MARKS = []  # 未配置，推进验证退化为 URL/截图变化")
    body.append("")
    return header + "\n".join(body)


if __name__ == "__main__":
    main()
