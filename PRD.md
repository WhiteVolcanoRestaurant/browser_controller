# PRD：基于 Playwright + PaddleOCR 的课程学习自动化脚本

## 一、项目概述

| 项目 | 说明 |
|------|------|
| **目标** | 自动完成网页课程学习流程（翻页、点击按钮、答题） |
| **输入** | 课程网页 URL |
| **输出** | 课程完成状态确认 |
| **核心能力** | 截图识别 -> 文字定位 -> 智能点击 -> 异常处理 |
| **运行环境** | Windows 11 + Python 3.10+ + RTX 3060 Laptop (6GB 显存) |
| **关键依赖** | Playwright (msedge)、PaddleOCR (GPU)、Ollama + llava-phi3 (备用) |

---

## 二、全局配置常量

```
MAX_PAGES = 100                    # 单课程最大页数，防止死循环
MIN_DELAY_SEC = 5                  # 两次操作之间的最小间隔（秒）
MAX_DELAY_SEC = 15                 # 两次操作之间的最大间隔（秒）
OCR_CONFIDENCE_THRESHOLD = 0.7     # OCR 置信度低于此值触发 VLM 兜底
VLM_CONFIDENCE_THRESHOLD = 0.4     # VLM 置信度低于此值拒绝执行（llava-phi3 小模型置信度偏低，适当放宽）
MAX_CLICKS_PER_RUN = 300           # 单次运行最大点击次数
ESC_KEY = "Escape"                 # 紧急停止热键
ALLOWED_DOMAINS = ["<平台域名>", "localhost", "127.0.0.1"]   # 真实域名在本地 config_platform.py 配置，不进仓库
QUESTION_KEYWORDS = ["单选", "多选", "判断", "问答", "题目", "哪些", "下列", "以下", "哪项"]
END_TEXTS = ["已完成", "学习完成", "课程完成", "结束"]   # 课程完成判定文本
TARGET_BUTTONS = {
    "start": ["开始学习", "继续学习", "进入课程"],
    "next":  ["下一页", "下一题", "下一步", "继续", "下一节", "下一章"],
    "submit":["提交", "确定", "确认"],
}
NEXT_BUTTON_CLASS_HINTS = ["next-btn", "next", "btn-next"]  # 翻页按钮 DOM class 特征
MAX_RELOAD_COUNT = 2                 # 单次运行自动刷新上限（防封号）
COURSE_DETAIL_URL_MARK = "/course/detail"  # 详情页 URL 特征，用于"往回跳即结束"
ENABLE_AUTO_COURSE_SELECTION = True        # 自动选择无绿色角标的未完成必修课
COURSE_LIST_URL_MARK = "#/course"          # 课程列表路由特征
REQUIRED_COURSE_TAB_NAME = "必修课"         # 仅处理必修课，不进入选修/考试
BROWSER_CHANNEL = "msedge"
VIEWPORT_WIDTH = 414               # H5 课程页只有中间一小块，用手机竖屏消除两侧留白
VIEWPORT_HEIGHT = 896
DEVICE_SCALE_FACTOR = 1            # 必须为 1，否则有头模式截图闪动
IS_MOBILE = True
USER_AGENT = "Mozilla/5.0 (iPhone; CPU iPhone OS 15_7 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/15.7 Mobile/15E148 Safari/604.1"
VLM_IMAGE_WIDTH = 414              # 与 VIEWPORT 一致，不再做双尺度缩放/坐标换算
VLM_IMAGE_HEIGHT = 896
OLLAMA_BASE_URL = "http://localhost:11434"   # Ollama 服务地址
OLLAMA_MODEL = "llava-phi3"                 # 视觉模型名
VLM_TIMEOUT = 60                            # VLM 单次推理超时（秒）
PROFILE_DIR = "./edge_profile"              # 持久化登录态的用户数据目录（避免每次重新登录）
TARGET_URL = "https://<平台域名>/"   # 默认主页；真实值在本地 config_platform.py
LOG_DIR = "./logs"                          # 日志与截图输出目录
```

---

## 三、模块定义

### 模块 1：BrowserController（浏览器控制器）

**职责**：封装 Playwright 的所有浏览器操作，提供截图、导航、点击、等待等原子操作。

**类方法定义：**

```
class BrowserController:

    init(channel="msedge", headless=False, viewport_width=414, viewport_height=896,
         user_agent=<iPhone Safari 移动端 UA>, device_scale_factor=1, is_mobile=True):
        # 启动 Edge 浏览器实例
        # 设置视口为手机竖屏 414x896（消除 H5 页面两侧留白，让 OCR/VLM 只关注课程卡片区域）
        # deviceScaleFactor 必须为 1，否则有头模式截图闪动
        # 注入 iPhone Safari UA，强制课程平台 H5 渲染成手机端布局
        # headed 模式下通过 CDP 调整外层窗口大小，避免窗口仍保持 1920x1080
        # 返回 self

    navigate(url):
        # 打开指定 URL
        # 等待页面加载完成（networkidle 状态）
        # 返回 page 对象

    reload():
        # 刷新当前页（保留登录态），用于死循环分级降级恢复
        # 返回是否成功

    screenshot(full_page=False):
        # 截取当前页面截图，返回 PIL.Image
        # 同时保存为 debug_page_{timestamp}.png，并把路径记录到 self.last_screenshot_path
        # （供日志台账关联截图）

    click(x, y):
        # 点击的核心：以 OCR 坐标为入口，用 DOM 反查真实可点击元素并点击。
        # 1. _human_move(x, y)：贝塞尔曲线拟人化移动鼠标（视觉像真人）
        # 2. 判断 elementFromPoint 命中的是主文档元素还是 iframe：
        #    - 命中 iframe：切到对应 frame，在 iframe 内部重新 elementFromPoint 定位
        #    - 命中普通元素：直接在主文档定位
        # 3. 向上找可点击祖先（a/button/input/label/select），派发 touch + click
        # 4. 回退：用 page.touchscreen.tap / mouse.click 按坐标真实点击
        # 返回 True/False

    find_text_element_center(keywords):
        # DOM 兜底：在主文档可见文本中找关键词，返回中心坐标（过滤屏幕外隐藏元素）
        # 当 OCR 匹配不到按钮时使用

    find_next_button():
        # 按 NEXT_BUTTON_CLASS_HINTS 里的 class（next-btn/next）跨 iframe 定位翻页按钮
        # 解决"下一页/继续/下一步"文字变化但 class 恒定的情况

    detect_video():
        # 跨 iframe 检测 <video> 的 paused/playing 状态
        # 用于识别"视频播放器页"（播放按钮是图标 OCR 识别不到）

    try_play_video():
        # 只观察常见播放按钮位置，再通过浏览器输入层点击并读取播放状态
        # 多数浏览器禁止无手势自动播放，可能失败，此时提醒用户手动点播放

    wait(ms):
        # 等待指定毫秒数

    wait_for_network_idle(timeout=30000):
        # 等待所有网络请求完成，超时返回 False

    get_current_url():
        # 返回当前页面 URL 字符串

    get_viewport_size():
        # 返回 (width, height) 元组

    close():
        # 关闭浏览器
```

---

### 模块 2：OCREngine（OCR 引擎）

**职责**：封装 PaddleOCR 的文字检测与识别，输出"文字内容 + 坐标 + 置信度"。

**类方法定义：**

```
class OCREngine:

    init(use_gpu=True, lang="ch", show_log=False):
        # 初始化 PaddleOCR
        # use_gpu=True 启用 RTX 3060 加速
        # lang="ch" 使用中文模型
        # 首次运行自动下载检测模型和识别模型
        # 返回 self

    recognize(image):
        # 输入：PIL.Image 或 numpy array
        # 执行 OCR 推理
        # 返回格式：
        # [
        #   {
        #     "text": "开始学习",
        #     "bbox": [[x1,y1], [x2,y2], [x3,y3], [x4,y4]],  # 四点坐标
        #     "confidence": 0.97
        #   },
        #   ...
        # ]
        # 如果识别失败返回空列表 []

    filter_by_keywords(ocr_results, keywords):
        # 输入：OCR 结果列表 + 关键词列表
        # 对每条 OCR 结果，检查 text 是否包含任一关键词（模糊匹配）
        # 返回匹配到的结果列表，按置信度降序排列

    locate_by_text(ocr_results, target_text):
        # 输入：OCR 结果列表 + VLM 给出的目标文字
        # 忽略空格后做双向包含匹配，返回最佳匹配（含 bbox），找不到返回 None
        # 用于 VLM 决策后的"文字反查坐标"，避免 VLM 直接输出坐标定位不准

    get_center_point(bbox):
        # 输入：四点坐标 [[x1,y1],[x2,y2],[x3,y3],[x4,y4]]
        # 返回中心点 (center_x, center_y)
        # center_x = (x1 + x2 + x3 + x4) / 4
        # center_y = (y1 + y2 + y3 + y4) / 4
```

---

### 模块 3：DecisionEngine（决策引擎）

**职责**：根据 OCR 识别结果，匹配目标按钮并计算点击坐标。按优先级依次尝试：关键词匹配 -> VLM 兜底。

**类方法定义：**

```
class DecisionEngine:

    init(ocr_engine, vlm_client, config):
        # 注入 OCR 引擎和 VLM 客户端
        # 加载全局配置
        # 返回 self

    decide(screenshot, ocr_results, page_url):
        # 核心决策函数。按以下优先级决策（注意：结束检测最优先，翻页按钮优先于题目检测）：
        #
        # 步骤 0：结束检测 —— 命中 END_TEXTS（已完成/学习完成…）直接 terminate
        #
        # 步骤 1：优先匹配"推进进度"按钮（start/next）
        #   学习内容页最明确的信号。必须放在题目检测之前，
        #   否则内容页正文里的"选择/哪些"等词会被误判成题目页。
        #
        # 步骤 2：题目检测 —— 没有翻页按钮时，命中 QUESTION_KEYWORDS 才走 VLM
        #   VLM 只负责"大脑"决策（判断该点哪个选项），不输出坐标；
        #   返回 action + target_text，再由 OCR 反查 bbox 得到精确坐标。
        #
        # 步骤 3：submit 按钮（提交/确认/确定）—— 非题目页的确认按钮
        #
        # 步骤 4：无目标 —— 返回 wait

    _call_vlm_fallback(screenshot, ocr_results):
        # 调用本地 VLM 进行兜底决策。
        #
        # 1. 截图保存：当前视口已是手机竖屏 414x896，无需再缩到 1280x720；
        #    如尺寸不同则做等比缩放，保证坐标和 OCR 为同一坐标系。
        # 2. 把 OCR 结果拼接成带编号的文字列表作为 prompt 上下文
        # 3. 构造 prompt（见上方步骤 4），要求 VLM 只输出 target_text，禁止输出坐标
        # 4. 发送 POST 请求到 http://localhost:11434/api/chat
        #    model: llava-phi3
        #    messages: [user: prompt + 截图base64]
        #    format: "json"
        #    temperature: 0.1
        #    num_predict: 512
        # 5. 等待响应（超时 60 秒）
        # 6. 从响应文本中解析 JSON（提取 action, target_text, confidence）
        # 7. 校验 action 白名单 / confidence 阈值
        # 8. action == "click" 时：
        #    调用 ocr_engine.locate_by_text(ocr_results, target_text) 反查 bbox
        #    找不到 -> 返回 {"action": "error", "reason": "OCR未定位到目标文字"}
        #    找到 -> 计算中心点返回 {"action": "click", "x": cx, "y": cy, ...}
        # 9. 返回解析后的决策

    _build_candidates(matched, limit=3):
        # 把 OCR 匹配结果转成候选点击坐标列表（按置信度降序，最多 limit 个）。
        # 用于"误匹配时点一个无反应就换下一个命中位置"的多候选试错。
        # 例如正文"找辅导员确认"误命中"确认"时，仍保留真正的"下一页"候选，逐个试错。

    semantic_fallback(screenshot, ocr_results, page_url):
        # 语义兜底：OCR 匹配不到标准翻页按钮（下一页/继续）时，
        # 让 VLM 判断页面上是否存在"能推进课程进度"的可点击元素。
        # 针对"看看有哪些新型诈骗""点击词云查看""知识卡片"这类引导语/图片按钮。
        # 与题目兜底使用不同的 prompt（VLM_NAV_RULES），只输出 click/need_human 两种动作。
        # vlm_ready=False 时直接返回 need_human（不发起任何网络请求）。
        # 注意：此方法由 main 循环在"连续 wait 未匹配 + DOM 兜底也找不到 + 无视频"时调用，
        #      不在 decide() 内部自动触发，避免过度调用拖慢主循环。
```

---

### 模块 4：SafetySandbox（安全沙箱）

**职责**：在每次操作执行前进行安全校验，所有操作必须通过沙箱才能执行。这是防止 AI 瞎搞的核心防线。

**类方法定义：**

```
class SafetySandbox:

    init(config):
        # 注入全局配置
        # 初始化操作计数器 = 0
        # 初始化上次操作时间戳 = 0
        # 初始化历史截图列表（用于重复检测，最多保留 5 张）
        # 返回 self

    validate_url(current_url):
        # 域名白名单校验。
        # 1. 提取 current_url 的域名部分
        # 2. 检查域名是否在 ALLOWED_DOMAINS 中
        # 3. 如果不在 -> 返回 (False, "URL偏离白名单: xxx")
        # 4. 如果在 -> 返回 (True, "")

    validate_coordinates(x, y, viewport_width, viewport_height):
        # 坐标边界校验。
        # 1. 检查 0 < x < viewport_width
        # 2. 检查 0 < y < viewport_height
        # 3. 如果任一条件不满足 -> 返回 (False, "坐标越界: (x, y)")
        # 4. 如果全部通过 -> 返回 (True, "")

    validate_rate_limit():
        # 操作频率限制校验。
        # 1. 计算当前时间 - 上次操作时间戳
        # 2. 如果间隔 < MIN_DELAY_SEC -> 返回 (False, "操作过于频繁")
        # 3. 如果间隔 >= MAX_DELAY_SEC -> 记录警告（可能之前卡住了）
        # 4. 更新上次操作时间戳 = 当前时间
        # 5. 返回 (True, "")

    validate_operation_count():
        # 操作上限校验。
        # 1. 操作计数器 +1
        # 2. 如果计数器 > MAX_CLICKS_PER_RUN -> 返回 (False, "超过最大操作次数")
        # 3. 返回 (True, f"操作次数: {计数器}/{MAX_CLICKS_PER_RUN}")

    validate_no_repeat(screenshot_hash):
        # 重复操作检测。
        # 1. 将当前截图的 hash 与历史截图列表对比
        # 2. 如果连续 3 次点击后截图相似度 > 95%（hash 相同）
        #    -> 返回 (False, "连续操作后页面无变化，可能陷入死循环")
        # 3. 将当前 hash 加入历史列表（保留最近 5 个）
        # 4. 返回 (True, "")

    check_all(page, screenshot):
        # 执行全部校验。按顺序调用以上所有方法。
        # 任一校验失败 -> 立即返回 (False, failure_reason)
        # 全部通过 -> 返回 (True, "")
```

---

### 模块 5：VLMClient（视觉大模型客户端）

**职责**：封装与本地 Ollama 的 VLM 通信。

**类方法定义：**

```
class VLMClient:

    init(base_url="http://localhost:11434", model="llava-phi3", timeout=60):
        # 存储 Ollama 地址和模型名
        # timeout 设为 60 秒（VLM 推理较慢）
        # 返回 self

    check_health():
        # 检查 VLM 服务是否可用。
        # 1. GET http://localhost:11434/api/tags
        # 2. 检查返回的模型列表是否包含 self.model
        # 3. 返回 True/False

    ask(screenshot_path, prompt):
        # 发送截图到 VLM 获取决策。
        # 1. 读取截图文件，转为 base64 字符串
        # 2. 构造请求体：
        #    {
        #      "model": "llava-phi3",
        #      "messages": [
        #        {
        #          "role": "user",
        #          "content": prompt,
        #          "images": [base64_string]
        #        }
        #      ],
        #      "stream": false,
        #      "format": "json",
        #      "options": {
        #        "temperature": 0.1,
        #        "num_predict": 512
        #      }
        #    }
        # 3. POST 到 http://localhost:11434/api/chat
        # 4. 超时 60 秒
        # 5. 返回 response.json()["message"]["content"]（纯文本）

    parse_decision(response_text):
        # 从 VLM 返回的文本中解析 JSON 决策。
        # 1. 在 response_text 中查找 JSON 代码块（```json ... ``` 或 ``` ... ```）
        # 2. 提取 JSON 内容并解析
        # 3. 校验必需字段：action (string), confidence (float)
        # 4. 如果 action 是 "click"，额外校验 target_text 非空（VLM 不输出坐标）
        # 5. 返回解析后的 dict，解析失败返回 {"action": "error", "reason": "JSON解析失败"}
```

---

### 模块 6：ActionLogger（操作日志器）

**职责**：记录每一步操作的完整信息，写入 JSONL 文件用于审计和调试。

**类方法定义：**

```
class ActionLogger:

    init(log_file="./logs/action_log.jsonl"):
        # 确保 logs/ 目录存在
        # 打开 log_file 用于追加写入
        # 返回 self

    log(step, action, details):
        # 写入一条操作日志。
        # 日志格式（每行一个 JSON）：
        # {
        #   "timestamp": "2026-08-21T10:30:00.000Z",
        #   "step": 1,
        #   "action": "click",
        #   "page_url": "https://<平台域名>/...",
        #   "details": {
        #     "target": "开始学习",
        #     "x": 495,
        #     "y": 635,
        #     "confidence": 0.97
        #   }
        # }
        # 1. 构造日志 dict
        # 2. 序列化为 JSON 字符串
        # 3. 追加写入 log_file，换行
        # 4. 同时打印到控制台（stdout）
```

---

## 四、核心工作流（主循环）

```
主函数 main(course_url, enable_vlm=True, enable_auto_course_selection=True):

    # 1. 初始化所有模块
    browser = BrowserController(channel="msedge", headless=False)
    ocr = OCREngine(use_gpu=True)
    vlm = VLMClient()
    decision = DecisionEngine(ocr, vlm, config)
    sandbox = SafetySandbox(config)
    logger = ActionLogger()

    # 1.1 VLM 健康检查（enable_vlm 且 config.ENABLE_VLM 时）
    vlm_ready = vlm.check_health()   # 不可用则自动降级"无 VLM 模式"，思考页直接转人工
    decision.vlm_ready = vlm_ready

    # 2. 打开课程页面 + 登录页等待
    page = browser.navigate(course_url)
    if "login" in page.url.lower():
        # 登录页：等待用户手动登录，不进主循环（避免反复截图导致页面闪动）
        while "login" in page.url.lower():
            browser.wait(5000)

    # 3. 主循环
    page_count = 0
    no_progress_count = 0        # 连续"点击无进展"计数，驱动分级降级
    reload_count = 0             # 累计自动刷新次数（防封号）
    consecutive_wait_count = 0   # 连续"未匹配"次数，驱动语义兜底
    prev_url = ""

    while page_count < MAX_PAGES:

        # 3.0 检测 URL 自动跳转（平台课程完成/视频结束会跳页）
        if prev_url and page.url != prev_url:
            no_progress_count = 0
            if _is_course_finished_jump(prev_url, page.url):
                # 从详情页跳回列表页 → 本课完成。
                # 自动选课开启时回到列表决策；关闭时等待用户打开下一节。
                if enable_auto_course_selection:
                    continue
                _wait_for_next_lesson(browser, prev_url)
                continue

        # 3.1 截图
        screenshot = browser.screenshot()

        # 3.2 OCR 识别（失败重试 1 次）
        ocr_results = ocr.recognize(screenshot)
        if not ocr_results:
            browser.wait(1000); ocr_results = ocr.recognize(screenshot)

        # 3.3 决策
        if enable_auto_course_selection and _is_course_list_page(page.url):
            # 只读取必修页签、分类计数与课程行 passed 类：
            # 切回必修 → 展开首个未完成分类 → 点击首个无绿色角标课程。
            # 必修全部完成即结束，不进入选修课或在线考试。
            decision_result = browser.find_unfinished_required_course()
        else:
            decision_result = decision.decide(screenshot, ocr_results, page.url)

        # 3.3.1 DOM 兜底：OCR 空 / wait / error 时，读 DOM 可见文字 + next-btn class 定位
        # 3.3.2 语义兜底：连续 2 次 wait 未匹配 + DOM 也找不到 + 无视频时，VLM 判断推进按钮；
        #            详情页才允许使用；列表页由确定性 DOM 选课规则处理，不让 VLM 猜测课程状态

        # 3.4 安全校验（URL 白名单 S1，偏离即终止）

        # 3.5 显式状态机执行：
        #   OBSERVE → DECIDE → ACT → VERIFY；一轮只操作一个候选，失败后重新观察
        #   VERIFY 以“匹配请求发出 + 收到响应”为首要成功信号，URL/截图变化为普通交互兜底
        #   wait    → 视频页只观察状态/可见播放控件，不调用 video.play()/element.click()
        #   need_human → VLM 可用时必须先进入 VLM_REASONING，仍无法处理才 HUMAN
        #   terminate  → 自动选课开启时点击“返回课程列表”；关闭时等待用户打开下一节
        #
        # 升级顺序：未失败候选 → 当前活动页可见 btn-next → VLM_REASONING → HUMAN

        page_count += 1

    # 4. 清理资源
    browser.close()
    logger.log(step=page_count, action="shutdown", details={"total_pages": page_count})
```

---

## 五、VLM 兜底详细流程

当 OCR 关键词匹配全部失败，且页面文本中包含题目关键词时，触发 VLM 兜底：

```
_decision_engine._call_vlm_fallback(screenshot, ocr_results):

    1. 截图预处理：
       - 当前视口已为手机竖屏 414x896（与 VIEWPORT 一致），不再缩放到 1280x720；
         如尺寸不同则做等比缩放，保证 OCR 和 VLM 为同一坐标系。
       - 保存为 ./logs/vlm_input_{timestamp}.png

    2. 构造 OCR 文字上下文：
       - 将 ocr_results 拼接为带编号文字列表，例如：
         "1. 判断题
          2. 下列哪项说法正确？
          3. A. 选项一
          4. B. 选项二
          ..."

    3. 构造 prompt（VLM 只输出目标文字，不输出坐标）：
       "你是一个网页课程学习助手。请根据页面截图和下方 OCR 识别出的文字，决定下一步操作。
        【OCR 识别到的文字】...
        请严格按照以下 JSON 格式输出决策：
        {
          "action": "click" 或 "wait" 或 "terminate",
          "target_text": "要点击的目标文字（必须原样复制自 OCR 文字）",
          "reason": "一句话说明理由",
          "confidence": 0.0~1.0的浮点数
        }
        ..."

    4. 调用 VLM：
       response_text = vlm.ask(screenshot_path, prompt)

    5. 解析响应：
       decision = vlm.parse_decision(response_text)

    6. 安全校验：
       - 检查 decision["action"] 是否在白名单 ["click", "wait", "terminate"]
       - 检查 confidence >= VLM_CONFIDENCE_THRESHOLD
       - 任一检查失败 -> 返回 {"action": "error", "reason": "VLM校验失败"}

    7. 反查坐标（核心：眼睛定位，大脑决策）：
       - 如果 action 是 "click"：
         - target_text = decision["target_text"]
         - located = ocr_engine.locate_by_text(ocr_results, target_text)
         - 找不到 -> 返回 {"action": "error", "reason": "OCR未定位到目标文字"}
         - 找到 -> cx, cy = ocr_engine.get_center_point(located["bbox"])

    8. 返回：
       {"action": "click", "x": cx, "y": cy,
        "target": located["text"], "confidence": decision["confidence"],
        "reason": decision["reason"]}
```

### 语义兜底（第二套 VLM 提示词）

当 OCR 匹配不到标准翻页按钮（下一页/继续/下一步）、DOM 兜底也找不到、且页面无视频时，触发语义兜底，让 VLM 判断页面上是否有"能推进课程进度"的可点击元素：

```
_decision_engine.semantic_fallback(screenshot, ocr_results, page_url):

    1. 触发条件（main 循环内）：
       - 连续 >= 2 次 wait 且 reason 含"未匹配"
       - DOM 兜底（可见文字 + next-btn class）都找不到
       - detect_video() 无视频
       - 页面 URL 含 COURSE_DETAIL_URL_MARK（列表页不触发；列表页走必修课 DOM 选择器）

    2. 使用独立的 prompt（VLM_NAV_RULES）：
       - 只允许输出 click / need_human 两种 action（不需要 wait/terminate）
       - 提示 VLM："这类元素通常是页面中靠下方、唯一明显的按钮或引导点击文字，
         例如'点击xx查看xxxx''看看有哪些xxxx'"
       - 纯内容展示页 → need_human，并让 VLM 说明对页面内容的理解

    3. 返回 click 时：仍需通过 ocr_engine.locate_by_text 反查坐标（眼睛定位）。
       反查失败 → need_human（不会输出错误坐标）。

    4. 与题目兜底的关系：
       - 题目兜底（VLM_QUESTION_RULES）：读题作答，输出 click/wait/terminate/need_human。
       - 语义兜底（VLM_NAV_RULES）：找推进按钮，只输出 click/need_human。
       - 两者共用公共开头/结尾（VLM_COMMON_HEAD / VLM_COMMON_TAIL），仅"决策规则"不同。
```

---

## 六、安全约束完整清单

以下约束在代码中必须硬编码实现，禁止通过配置关闭：

| 约束编号 | 约束名称 | 具体规则 | 违反时动作 |
|---------|---------|---------|-----------|
| S1 | 域名白名单 | page.url 的域名必须在 ALLOWED_DOMAINS 中 | 立即停止脚本 |
| S2 | 坐标边界 | 点击坐标必须满足 0 < x < viewport_width 且 0 < y < viewport_height | 拒绝执行该次点击 |
| S3 | 操作频率 | 两次操作间隔 >= MIN_DELAY_SEC (5秒) | 跳过本次操作，等待 |
| S4 | 操作上限 | 单次运行点击次数 <= MAX_CLICKS_PER_RUN (300) | 终止脚本 |
| S5 | 重复检测 | 点击后页面无变化（连续计数），走分级降级：加长等待 → DOM 重定位 → VLM 语义兜底 → reload（上限 MAX_RELOAD_COUNT）→ 人工介入 | 分级恢复，超限才停止 |
| S6 | VLM 输出校验 | VLM 返回的 action 必须在白名单（click/wait/terminate/need_human），click 时必须给出 target_text 且能在 OCR 结果中定位到 | 拒绝执行，记录日志 |
| S7 | 禁止文件系统写入 | 脚本中不得出现 os.remove / shutil / subprocess / os.system | 代码审查时检查 |
| S8 | 禁止外部导航 | 不得调用 page.goto() 跳转到白名单以外的 URL | 代码审查时检查 |
| S9 | JS 执行仅限定位/点击 | page.evaluate/frame.evaluate 仅用于 DOM 定位与点击（elementFromPoint/click），不得执行任意未审核逻辑 | 代码审查时检查 |
| S10 | 紧急停止 | 监听 Ctrl+C 键盘事件，捕获 KeyboardInterrupt | 立即关闭浏览器并退出 |

---

## 七、异常处理策略

| 异常类型 | 触发条件 | 处理策略 |
|---------|---------|---------|
| OCR 识别失败 | ocr.recognize() 返回空列表或抛出异常 | 重试 1 次，仍失败则进入 VLM 兜底 |
| VLM 调用超时 | POST 请求超过 60 秒未响应 | 重试 1 次，仍超时则等待 5 秒后回到截图步骤 |
| VLM JSON 解析失败 | 返回文本中无法提取有效 JSON | 将原始文本写入日志，等待 3 秒后重试 |
| 网络请求失败 | page.goto() 或 wait_for_network_idle() 超时 | 重试 1 次，仍失败则记录错误并继续 |
| 浏览器崩溃 | Playwright 抛出 ConnectionError | 记录错误，尝试重新 navigate 到当前 URL，最多重试 3 次 |
| 用户中断 | 用户按下 Ctrl+C | 捕获 KeyboardInterrupt，关闭浏览器，保存日志，正常退出 |

---

## 八、日志输出规范

控制台日志格式（每行一条，带时间戳前缀）：

```
[2026-08-21 10:30:00] [INFO] 启动脚本，课程URL: https://<平台域名>/...
[2026-08-21 10:30:02] [INFO] 页面加载完成 | URL: https://<平台域名>/...
[2026-08-21 10:30:02] [OCR] 识别到 12 个文本块
[2026-08-21 10:30:02] [OCR] "开始学习" -> 坐标(480, 620) 置信度: 0.97
[2026-08-21 10:30:02] [DECISION] 匹配到目标: "开始学习" @ (495, 635)
[2026-08-21 10:30:02] [SANDBOX] 校验通过 | 操作次数: 1/300
[2026-08-21 10:30:02] [CLICK] 已点击 (495, 635) | 目标: 开始学习
[2026-08-21 10:30:07] [DELAY] 等待 6.5 秒模拟真人学习...
[2026-08-21 10:30:13] [INFO] 页面加载完成 | URL: https://<平台域名>/...
[2026-08-21 10:30:13] [OCR] 识别到 15 个文本块
[2026-08-21 10:30:13] [OCR] "判断题" -> 坐标(300, 150) 置信度: 0.91
[2026-08-21 10:30:13] [VLM] 检测到题目关键词，触发 VLM 兜底
[2026-08-21 10:30:20] [VLM] 返回: action=click, target_text=选项B文字, confidence=0.88
[2026-08-21 10:30:20] [OCR] 反查定位到"选项B文字" @ (450, 380)
[2026-08-21 10:30:20] [SANDBOX] 坐标(450, 380)在屏幕范围内 OK
[2026-08-21 10:30:20] [CLICK] 已点击 (450, 380) | 目标: 选项B文字
...
[2026-08-21 11:45:00] [INFO] 课程已完成 | 总页数: 42 | 总操作: 87
```

---

## 九、依赖安装清单

```
# Python 依赖
pip install playwright paddleocr paddlepaddle-gpu requests

# Playwright 浏览器驱动（首次运行）
playwright install msedge

# 注意：PaddleOCR 首次运行会自动下载 ch_PP-OCRv4_det 和 ch_PP-OCRv4_rec 模型文件

# Ollama 模型（独立安装，不在 Python 依赖中）
# 1. 下载安装 Ollama: https://ollama.com
# 2. 拉取视觉模型: ollama pull llava-phi3
# 3. 启动服务: ollama serve（后台运行）
```

---

## 十、运行方式

```
# 1. 确保 Ollama 服务正在运行（VLM 兜底需要；不需要 VLM 可跳过）
# 2. 启动脚本，传入课程 URL
python main.py "https://<平台域名>/课程地址"

# 跳过 VLM（不调用 Ollama），所有需要"思考"的页面直接转人工介入：
python main.py "https://<平台域名>/课程地址" --no-vlm
# 或设置 config.py: ENABLE_VLM = False

# 3. 脚本启动后会打开 Edge 浏览器
# 4. 如果页面需要登录，请手动在浏览器中完成登录
# 5. 登录完成后，脚本会自动开始执行
# 6. 按 Ctrl+C 可随时停止脚本

# 生成可视化台账（跑完后，产物 logs/report.html）
python report.py
```

---

## 十一、验收标准

| 验收项 | 标准 |
|--------|------|
| 正常翻页 | 能连续翻页 >= 50 页不中断 |
| OCR 识别 | 按钮文字识别置信度 >= 0.8 时能正确点击 |
| VLM 兜底 | OCR 失败时 VLM 能正确决策目标文字，并通过 OCR 反查定位后点击 |
| 安全校验 | URL 偏离时立即停止，坐标越界时拒绝执行 |
| 操作频率 | 两次操作间隔在 5~15 秒之间 |
| 日志完整 | action_log.jsonl 中每步操作都有记录 |
| 紧急停止 | 按 Ctrl+C 后浏览器在 3 秒内关闭 |
| 无异常写入 | 脚本不写入任何非日志文件到磁盘 |

---

## 十二、实现演进与辅助工具

本项目从 0 到跑通经历了大量迭代，关键技术决策、踩坑记录、点击定位演进史详见 **[DEVELOPMENT_LOG.md](DEVELOPMENT_LOG.md)**（开发记录）。

本 PRD 描述的是「产品需求 + 目标行为」，具体实现细节（如 iframe 定位、视频页处理、分级降级等）以下面三个辅助文件为准：

| 文件 | 作用 |
|------|------|
| `DEVELOPMENT_LOG.md` | 踩坑记录、技术演进史、配置说明 |
| `debug_ocr.py` | 单独对某张截图跑 OCR（多尺度 + 亮度检测），排查"识别不到"问题 |
| `report.py` | 解析 action_log.jsonl 生成 `logs/report.html` 可视化台账（统计概览 + 困难样本 + 截图） |

核心定位分工：**OCR 当眼睛**（识别文字、给大致坐标、判断页面类型），**DOM 当手**（elementFromPoint 反查真实元素、切 iframe 精确定位并点击），**VLM 当大脑**（读题做题、判断拿不准）。
