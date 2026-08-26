# -*- coding: utf-8 -*-
"""
平台私有配置模板（占位符，可提交仓库）。

复制本文件为 config_platform.py 并填写真实值：
    copy config_platform.example.py config_platform.py
    # 或运行引导脚本：
    python setup_local.py

注意：
- config_platform.py 已被 .gitignore 排除，不会提交到 GitHub / Gitee。
- 请勿把真实平台域名 / 具体 API 名称写进 config.py 或其它会提交的文件。
"""

# 课程平台根域名（仅主机名，如 "example.com"）
PLATFORM_DOMAIN = "your-platform.example.com"

# 课程平台主页（程序未指定 URL 时默认打开）
TARGET_URL = "https://your-platform.example.com/"

# 域名白名单（安全沙箱校验跳转目标用；localhost/127.0.0.1 会被 config.py 强制追加）
ALLOWED_DOMAINS = [
    PLATFORM_DOMAIN,
]

# 课程详情页 URL 特征（用于"往回跳即结束"与"是否在课程详情页"判断）
COURSE_DETAIL_URL_MARK = "/course/detail"

# "推进生效"的 API 特征（判断点击/人工操作后页面是否真的推进了）。
# 列表元素格式：
#   {
#     "name":      日志里显示的别名（如 "翻页"、"答题提交"）
#     "url_marks": URL 必须包含的子串列表（全部命中即算）
#     "body_marks": POST body 必须包含的子串列表（可选；缺省只按 URL 判断）
#   }
# 不知道 API 特征时可为空列表 []，推进验证将退化为「URL 变化 + 截图内容变化」。
PROGRESS_API_MARKS = [
    # {
    #     "name": "翻页",
    #     "url_marks": ["your_api_mark"],
    # },
    # {
    #     "name": "答题提交",
    #     "url_marks": ["your_api_mark"],
    #     "body_marks": ["your_body_mark"],
    # },
]
