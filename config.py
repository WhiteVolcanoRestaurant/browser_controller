#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""全局配置常量（PRD 第二节：全局配置常量）"""

import os

# 项目根目录
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# 单课程最大页数，防止死循环
MAX_PAGES = 100

# 两次操作之间的间隔（秒）
MIN_DELAY_SEC = 3
MAX_DELAY_SEC = 15

# 点击落点在目标中心附近的轻微随机偏移（CSS 像素）。
# 偏移只用于避免机械地重复命中同一像素；最终坐标仍受视口边界和元素命中检查约束。
CLICK_JITTER_PX = 3

# 点击后若短时间内没有出现进度请求，尽快回退到 URL/截图变化判断，
# 避免普通卡片交互为等待一个不存在的 next 请求而停顿数秒。
PROGRESS_REQUEST_GRACE_MS = 1200

# OCR 置信度低于此值触发 VLM 兜底。
# 0.6 而非 0.7：按钮文字字距大时 OCR 会在字间插入空格（如"继  续"），
# 识别置信度常被拉低到 0.6x，去空格匹配成功后仍应允许点击。
OCR_CONFIDENCE_THRESHOLD = 0.6

# VLM 置信度低于此值拒绝执行（小模型置信度普遍偏低，适当放宽）
VLM_CONFIDENCE_THRESHOLD = 0.4

# 单次运行最大点击次数
MAX_CLICKS_PER_RUN = 300

# 单次运行最多自动刷新页面次数，超过则停止运行。
# 反复 reload 是明显的脚本特征，容易触发风控/封号，必须设上限。
# 注意：reload 会重置课程页的交互进度（如知识卡片查看状态），触发前应先走 VLM/人工。
MAX_RELOAD_COUNT = 2

# 是否启用 VLM（Ollama）。设为 False 可完全跳过 VLM，所有需要"思考"的页面直接转人工介入。
# 适合不想跑本地大模型/显存不足的用户。
ENABLE_VLM = True

# 紧急停止热键（说明用；实际由 Ctrl+C 触发的 KeyboardInterrupt 处理）
ESC_KEY = "Escape"

# ============================================================
# 平台私有配置（域名 / 具体 API 特征），从本地 config_platform.py 读取。
# config_platform.py 已被 .gitignore 排除、不会提交到仓库，
# 避免真实平台域名与接口名在公开仓库中被检索到。
# 未配置时使用占位域名并提示先运行 python setup_local.py。
# ============================================================
try:
    from config_platform import (  # noqa: F401
        PLATFORM_DOMAIN,
        TARGET_URL,
        ALLOWED_DOMAINS,
        COURSE_DETAIL_URL_MARK,
        PROGRESS_API_MARKS,
    )
    _PLATFORM_CONFIGURED = True
except ImportError:
    PLATFORM_DOMAIN = "your-platform.example.com"  # 占位符，勿当真值使用
    TARGET_URL = "https://your-platform.example.com/"
    ALLOWED_DOMAINS = []
    COURSE_DETAIL_URL_MARK = "/course/detail"
    PROGRESS_API_MARKS = []
    _PLATFORM_CONFIGURED = False

# 本地调试白名单始终保留
for _d in ("localhost", "127.0.0.1"):
    if _d not in ALLOWED_DOMAINS:
        ALLOWED_DOMAINS.append(_d)

if not _PLATFORM_CONFIGURED:
    print("[配置] 未找到本地平台配置 config_platform.py，正在使用占位域名。")
    print("[配置] 请先运行 python setup_local.py 填写课程平台信息后再启动。")

# 题目关键词，命中则触发 VLM 兜底。
# 注意：不要放"选择"这种太宽泛的词（内容文本"尽量不要选择货到付款"会误判成题目）。
# 也不用"以下"——正文"只要做到以下几点就能防骗"含"以下"，会被误判成题目页。
QUESTION_KEYWORDS = ["单选", "多选", "判断", "问答", "题目", "哪些", "下列", "哪项"]

# 目标按钮匹配优先级：start -> next -> submit -> guide_click
# guide_click：反诈案例页常见的"点击了解/查看/进入"引导语按钮（如"点击了解经过"）。
# 短语命中之外，GUIDE_CLICK_PREFIX="点击" 会额外命中"以'点击'开头"的按钮文字
#（如"点击翻转""点击返回"）；正文句子（"骗子引诱点击陌生链接..."）不以"点击"开头，
# 不会被误命中，"不点击"等否定形式也不满足前缀。匹配顺序排在 submit 之后。
TARGET_BUTTONS = {
    "start": ["开始学习", "继续学习", "进入课程", "点击开始"],
    "next": ["下一页", "下一题", "下一步", "继续", "下一节", "下一章"],
    "submit": ["提交", "确定", "确认"],
    "guide_click": ["点击了解", "点击查看", "点击进入", "点击学习", "点击打开", "点击播放"],
}

# guide_click 的放宽规则：OCR 文字"以'点击'开头"即可视为引导点击按钮
#（覆盖"点击翻转"等不在关键词表里的按钮）。只用前缀不用长度启发式：
# 正文句子不以"点击"开头（如"骗子引诱点击陌生链接..."），不会被误命中。
GUIDE_CLICK_PREFIX = "点击"

# 翻页按钮的 DOM class 特征（含这些 class 的元素视为"换页/继续"按钮），
# 用于在 OCR 文字变化（如"继续"代替"下一页"）时仍能可靠定位翻页控件。
NEXT_BUTTON_CLASS_HINTS = ["next-btn", "next", "btn-next"]

# 微课结束判定文本。
# 结束页正文是"课程的学习已完成"，按钮"返回列表"可能与其它页面内容冲突，
# 不能用按钮文字判定，只能以正文"课程的学习已完成"为准。
# 注意：不能用裸"已完成"——阶段性文案"你已完成了本微课"（后接"下一页"进测验）
# 会误判成课程结束直接 terminate。
END_TEXTS = ["课程的学习已完成", "学习完成", "课程完成", "结束"]

# 无 VLM 模式下的"返回"按钮保底（反诈案例页等纯展示页）。
# 页面没有任何标准推进按钮（下一页/继续/提交/点击xxx）时，底部唯一的"返回"
# 通常是"回到上一级继续学习"，点击可推进课程流程（VLM 语义兜底也常判断点它）。
# 开启后，决策引擎在 guide_click 之后、wait 之前尝试点击"返回"。
# 注意：故意不放进 TARGET_BUTTONS——DOM 兜底会遍历 TARGET_BUTTONS.values()，
# 而 DOM 兜底没有位置过滤，会把顶部导航栏的"返回"（退出按钮）也当作候选。
ENABLE_BACK_FALLBACK = True
BACK_BUTTON_KEYWORDS = ["返回"]
# "返回"按钮的 y 坐标必须大于 视口高度 * BACK_BUTTON_Y_RATIO（位于视口下半部分）。
# 底部"返回"通常是"回到上一级继续学习"；顶部"返回"是导航/退出按钮，不能点。
BACK_BUTTON_Y_RATIO = 0.4

# 浏览器配置：H5 课程页只有中间一小块，直接用手机视口，
# 避免 1920x1080 的两侧留白干扰 OCR / VLM 定位，同时截图更小、OCR/VLM 更快。
BROWSER_CHANNEL = "msedge"
VIEWPORT_WIDTH = 414   # iPhone 12 Pro 逻辑宽度（竖屏）
VIEWPORT_HEIGHT = 896  # 竖屏长屏，保证一屏能看到 H5 卡片 + 下一页按钮
DEVICE_SCALE_FACTOR = 1  # 必须为 1：deviceScaleFactor>1 时，有头模式每次截图都会
                          # 触发 Chromium 放大→还原，导致页面闪动（Playwright 已知问题）。
IS_MOBILE = True        # 开启移动端 UA / touch 支持
# iPhone 13 iOS 15 Safari UA，让课程平台 H5 渲染成手机端布局而不是桌面端居中
USER_AGENT = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 15_7 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/15.7 Mobile/15E148 Safari/604.1"
)

# 持久化登录态的用户数据目录（复用 edge_profile，无需每次重新登录）
PROFILE_DIR = os.path.join(BASE_DIR, "edge_profile")

# Ollama VLM 配置（testVLM.py 与主流程 VLMClient 均从这里读取实际模型）
OLLAMA_BASE_URL = "http://localhost:11434"
OLLAMA_MODEL = "qwen3-vl:4b"
VLM_TIMEOUT = 60
# VLM 输入改成手机竖屏比例，避免再做双尺度缩放；
# OCR/VLM 都在同一尺寸坐标系下，定位更准、显存占用也更小。
VLM_IMAGE_WIDTH = 414
VLM_IMAGE_HEIGHT = 896

# 日志目录（绝对路径）
LOG_DIR = os.path.join(BASE_DIR, "logs")
