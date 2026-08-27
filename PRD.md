# PRD：基于 Playwright + PaddleOCR 的课程学习自动化脚本

## 一、项目概述

| 项目 | 说明 |
|------|------|
| **目标** | 自动完成网页课程学习流程（翻页、点击按钮、答题、处理视频） |
| **输入** | 课程网页 URL |
| **输出** | 课程完成状态确认 |
| **核心能力** | 截图识别 -> 文字定位 -> 智能点击 -> 异常处理 |
| **运行环境** | Windows 11 + Python 3.10+ + RTX 3060 Laptop (6GB 显存) |
| **关键依赖** | Playwright (msedge)、PaddleOCR (GPU)、Ollama + qwen3-vl:4b (可选/备用) |

---

## 二、全局配置常量

真实平台域名 / 具体 API 特征从本地 `config_platform.py` 读取（不进仓库），下方为 `config.py` 与 `config_platform.py` 中生效的配置汇总：

```
# —— config.py 常量 ——
MAX_PAGES = 100                    # 单课程最大页数，防止死循环
MIN_DELAY_SEC = 3                  # 两次操作之间的最小间隔（秒）
MAX_DELAY_SEC = 15                 # 两次操作之间的最大间隔（秒）
VIDEO_POLL_INTERVAL_MS = 15000     # 视频"是否播完"的轮询间隔（毫秒）
VIDEO_WAIT_TIMEOUT_MS = 1200000    # 视频等待播完总超时（20 分钟），超时转人工
CLICK_JITTER_PX = 3                # 点击落点中心附近的随机偏移（CSS 像素）
ENABLE_JS_CLICK_FALLBACK = True    # 真实输入点不中时，是否用 JS element.click() 兜底（iframe 课程页必需）
PROGRESS_REQUEST_GRACE_MS = 1200   # 点击后无进度请求时，多久回退到 URL/截图变化判断

OCR_CONFIDENCE_THRESHOLD = 0.6     # OCR 置信度低于此值不再作为候选（字距大时置信度被拉低，放宽到 0.6）
VLM_CONFIDENCE_THRESHOLD = 0.4     # VLM click 决策置信度低于此值拒绝执行（小模型置信度普遍偏低）
MAX_CLICKS_PER_RUN = 300           # 单次运行最大点击次数
MAX_RELOAD_COUNT = 2               # 自动刷新上限（当前主循环已不再触发 reload，保留配置）
ENABLE_VLM = True                  # 是否启用 VLM；False 时所有"思考"页直接转人工
ESC_KEY = "Escape"                 # 紧急停止热键（说明用；实际由 Ctrl+C 触发 KeyboardInterrupt）

QUESTION_KEYWORDS = ["单选", "多选", "判断", "问答", "题目", "哪些", "下列", "哪项"]

# 目标按钮匹配类别：start -> next -> submit -> guide_click
TARGET_BUTTONS = {
    "start": ["开始学习", "继续学习", "进入课程", "点击开始"],
    "next":  ["下一页", "下一题", "下一步", "继续", "下一节", "下一章"],
    "submit":["提交", "确定", "确认"],
    "guide_click": ["点击了解", "点击查看", "点击进入", "点击学习", "点击打开", "点击播放"],
}
GUIDE_CLICK_PREFIX = "点击"         # guide_click 放宽：OCR 文字"以'点击'开头"即视为引导按钮

NEXT_BUTTON_CLASS_HINTS = ["next-btn", "next", "btn-next"]  # 翻页按钮 DOM class 特征

END_TEXTS = ["课程的学习已完成", "学习完成", "课程完成", "结束"]  # 结束正文（不用裸"已完成"）

# 无 VLM 模式的"返回"按钮保底（反诈案例页等纯展示页）
ENABLE_BACK_FALLBACK = True
BACK_BUTTON_KEYWORDS = ["返回"]
BACK_BUTTON_Y_RATIO = 0.4          # "返回"的 y 必须大于 视口高度 * 0.4（视口下半部分）

BROWSER_CHANNEL = "msedge"
VIEWPORT_WIDTH = 414               # H5 课程页只有中间一小块，用手机竖屏消除两侧留白
VIEWPORT_HEIGHT = 896
DEVICE_SCALE_FACTOR = 1            # 必须为 1，否则有头模式截图闪动
IS_MOBILE = True
USER_AGENT = "Mozilla/5.0 (iPhone; CPU iPhone OS 15_7 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/15.7 Mobile/15E148 Safari/604.1"
VLM_IMAGE_WIDTH = 414              # 与 VIEWPORT 一致，不再做双尺度缩放/坐标换算
VLM_IMAGE_HEIGHT = 896
OLLAMA_BASE_URL = "http://localhost:11434"
OLLAMA_MODEL = "qwen3-vl:4b"       # 视觉模型名
VLM_TIMEOUT = 60                   # VLM 单次推理超时（秒）
PROFILE_DIR = "./edge_profile"     # 持久化登录态的用户数据目录
LOG_DIR = "./logs"                 # 日志与截图输出目录

# —— config_platform.py（本地，不进仓库）——
PLATFORM_DOMAIN = "<平台域名>"
TARGET_URL = "https://<平台域名>/"
ALLOWED_DOMAINS = ["<平台域名>", "localhost", "127.0.0.1"]
COURSE_DETAIL_URL_MARK = "/course/detail"   # 详情页 URL 特征，用于"往回跳即结束"与列表页判断
COURSE_FINISH_URL_MARK = "/wk/comment"      # 完成/结束页 URL 特征（视频播完/课程学完自动跳转）
COURSE_FINISHED_TEXT = "课程的学习已完成"     # 结束页固定正文，用于严格匹配判定结束
PROGRESS_API_MARKS = [...]                  # "推进生效"的 API 特征（翻页/答题提交），可空
```

---

## 三、模块定义

### 模块 1：BrowserController（浏览器控制器）

**职责**：封装 Playwright 的所有浏览器操作，提供截图、导航、点击、等待、视频检测、进度验证等原子操作。核心原则：**DOM 只做无副作用观察（读可见元素、边界），实际操作统一走浏览器输入层；JS 合成点击仅作 iframe 兜底**。

**主要方法：**

```
class BrowserController:

    __init__(channel=None, headless=False, viewport_width=None, viewport_height=None, use_stealth=True):
        # 启动 Edge（launch_persistent_context 复用 edge_profile 登录态）
        # 设置手机竖屏视口 414x896 + iPhone UA + 移动端 touch 支持
        # deviceScaleFactor 必须为 1（否则有头模式截图闪动）
        # 未安装 playwright-stealth 时自动跳过指纹伪装
        # 返回 self

    set_logger(logger):
        # 注入 ActionLogger，让 click 阶段的命中/保底诊断也写入 action_log.jsonl

    navigate(url):
        # 打开 URL（networkidle 失败回退 domcontentloaded，最多重试 3 轮），返回 page

    reload():
        # 刷新当前页（保留登录态）。当前主循环已不再调用（遗留方法）

    screenshot(full_page=False):
        # 截图返回 PIL.Image，同时保存 debug_page_{timestamp}.png 并记录 last_screenshot_path

    click(x, y):
        # 以 OCR/DOM 给出的坐标为入口，执行一次浏览器输入层点击：
        # 1. 坐标加 CLICK_JITTER_PX 随机偏移
        # 2. _human_move：贝塞尔曲线拟人化移动鼠标
        # 3. _log_click_target：elementFromPoint 只读查询命中元素并打印（iframe 内切 frame 查）
        # 4. _real_click：移动端 touch+mouse 双发（真实移动端触摸本就产生 touch+合成 mouse）
        # 5. ENABLE_JS_CLICK_FALLBACK 开启时 _js_click 追加 JS element.click() 兜底（切 frame）
        # 返回 True/False

    find_text_element_center(keywords):
        # DOM 兜底：在可见文本节点/元素中找关键词，返回中心坐标（过滤屏幕外隐藏元素，从下到上取最靠下）

    find_next_button():
        # 按 NEXT_BUTTON_CLASS_HINTS 跨 iframe 定位翻页按钮，只认"活动页(.page-active/.page.active)内、
        # 可见、未遮挡、未禁用"的元素；返回 (x, y) 主文档坐标

    detect_video():
        # 跨 iframe 检测"可见 + 有真实内容"的 <video>（过滤隐藏/占位/视口外/空壳视频）
        # 返回 has_video / paused / ended / playing / duration / currentTime / readyState

    try_play_video():
        # 收集全部可见播放控件候选（含 video 本体），逐个点击试错，轮询最多 3 秒确认 playing

    wait_for_video_end(poll_interval_ms=15000, timeout_ms=None, logger=None):
        # 轮询等待视频播完：每 15 秒检测一次并截图进日志，直到 ended / 视频消失 / 出现翻页按钮
        # 返回 video_ended / video_gone / next_available / timeout

    wait(ms):
        # 等待指定毫秒数

    wait_for_network_idle(timeout=30000):
        # 等待所有网络请求完成，超时返回 False

    wait_for_progress(timeout_ms=120000, prev_url=None):
        # 等待"推进"信号（人工介入后判断页面是否变化）：
        # 信号 1 = 命中 PROGRESS_API_MARKS 且请求+响应都出现；信号 2 = URL 变化；信号 3 = 用户按 Enter 唤醒

    read_key():
        # 非阻塞读取一个按键（Windows msvcrt），供"暂停/继续(p)"与"人工唤醒(Enter)"共用

    images_changed(img1, img2, threshold=8.0):
        # 降采样 48x48 比较灰度差，判断页面内容是否显著变化（点击验证的兜底信号）

    click_and_verify(x, y, before_image=None, prev_url=None, timeout_ms=6000):
        # 点击并验证"是否真的推进"：验证顺序 API(请求+响应) > URL 变化 > 截图内容变化
        # 返回 (changed: bool, why: str)

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

**主要方法：**

```
class OCREngine:

    __init__(use_gpu=True, lang="ch", show_log=False):
        # 延迟导入 PaddleOCR，依次尝试 指定模式 -> CPU -> 最小参数，兼容不同版本
        # 返回 self

    recognize(image):
        # 输入 PIL.Image / numpy；先 2 倍放大再识别（小字更准），GPU 失败自动降级 CPU 重试
        # 返回 [{text, bbox, confidence}, ...]，识别失败返回 []

    compact_text(text):
        # 去掉文本内所有空白（OCR 字距大时会插空格，如"继  续"），供匹配统一使用

    filter_by_keywords(ocr_results, keywords, prefix=None):
        # 模糊匹配（text 包含关键词），匹配前去空白、排除否定形式（"不"+关键词）
        # prefix 额外命中"以 prefix 开头"的文字（如"点击翻转"以"点击"开头）
        # 按 y 坐标降序返回（从下到上，推进按钮通常在页面底部）

    locate_by_text(ocr_results, target_text):
        # VLM 给出目标文字后反查 bbox；双方去空白后做双向包含匹配，返回最佳匹配或 None

    get_center_point(bbox):
        # 四点坐标 -> 中心点 (center_x, center_y)
```

---

### 模块 3：DecisionEngine（决策引擎）

**职责**：根据 OCR 结果与页面 URL 决策下一步动作。核心策略：**合并按钮候选池（类别优先、同类从下到上）+ 结束/题目检测 + VLM 兜底（输出候选队列）+ 返回按钮保底**。候选队列按来源区分：OCR 关键词候选（`source=ocr`）、DOM 可见翻页元素（`source=dom`，由 main.py 优先注入）、VLM 语义推理候选（`source=vlm`）。

**主要方法：**

```
class DecisionEngine:

    __init__(ocr_engine, vlm_client, config):
        # 注入 OCR / VLM / 配置；vlm_ready 由 main.py 启动时健康检查写入
        # 返回 self

    decide(screenshot, ocr_results, page_url):
        # 核心决策函数（产出 OCR 来源候选队列）：
        # 步骤 0：COURSE_FINISHED_TEXT 严格短语匹配（如"课程的学习已完成"）→ terminate（优先于按钮）
        # 步骤 1：合并 start/next/submit/guide_click 为候选池（类别优先、同类从下到上，去重），source=ocr
        #   最高类别是 start/next → 直接 click（跳过结束/题目检测，保持"下一页优先于结束/题目"语义）
        #   最高类别是 submit/guide_click → 先做结束检测、题目检测（题目页"提交"必须先走 VLM 读题）
        # 步骤 2：无按钮候选时的结束检测（END_TEXTS）
        # 步骤 3：无按钮候选时的题目检测（QUESTION_KEYWORDS → VLM 读题作答）
        # 步骤 4：无 VLM 保底——ENABLE_BACK_FALLBACK 且详情页且"返回"在视口下半部分 → click 返回（source=ocr）
        # 步骤 5：OCR 空 → wait（登录页/未渲染）；否则 wait（未匹配到任何目标）

    _collect_button_candidates(ocr_results, groups, limit=5):
        # 合并多类别候选：类别优先（groups 顺序）、同类从下到上；同一坐标只保留一次
        # guide_click 额外用 GUIDE_CLICK_PREFIX 前缀放宽

    _build_candidates(matched, limit=3):
        # OCR 匹配结果 -> 候选点击坐标列表（过滤低置信度，最多 limit 个），用于多候选试错

    _call_vlm_fallback(screenshot, ocr_results, page_url=""):
        # 题目页 VLM 兜底（读题作答）；vlm_ready=False 直接转 need_human

    semantic_fallback(screenshot, ocr_results, page_url=""):
        # 语义兜底：让 VLM 判断"推进按钮"（引导语/图片按钮）；只输出 click/need_human

    _vlm_query(screenshot, ocr_results, page_url, prompt_template):
        # 截图缩放保存 -> 构造 prompt（携带截图 + OCR 文字）-> 调 VLM -> 解析 targets 队列
        # -> 逐个反查 OCR 坐标构造 candidates（source=vlm），主循环按序试错
```

---

### 模块 4：SafetySandbox（安全沙箱）

**职责**：在每次操作执行前做安全校验。频率/坐标/次数校验在"真正点击前"由主循环单独调用，避免等待循环被误拦截。

**主要方法：**

```
class SafetySandbox:

    __init__(config):
        # 注入配置，初始化操作计数器 / 上次操作时间戳 / 历史截图列表
        # 返回 self

    validate_url(current_url):
        # 域名白名单校验，偏离返回 (False, reason)

    validate_coordinates(x, y, viewport_width, viewport_height):
        # 坐标边界校验（0 < x < width 且 0 < y < height）

    validate_rate_limit():
        # 操作频率校验（间隔 < MIN_DELAY_SEC 拦截；每次通过都更新时间戳）

    validate_operation_count():
        # 操作上限校验（> MAX_CLICKS_PER_RUN 拦截）

    check_all(page):
        # 每次循环只做 URL 白名单校验（S1）；其余校验由主循环在点击前单独调用

    validate_no_repeat(screenshot_hash) / hash_image(image):
        # 遗留方法：当前主循环的"重复检测"已改由 click_and_verify 里的 images_changed 实现，
        # 这两个方法不再被调用
```

---

### 模块 5：VLMClient（视觉大模型客户端）

**职责**：封装与本地 Ollama 的 VLM 通信。

**主要方法：**

```
class VLMClient:

    __init__(base_url=None, model=None, timeout=None):
        # 默认 base_url=http://localhost:11434、model=qwen3-vl:4b、timeout=60

    check_health():
        # GET /api/tags，检查模型列表是否包含 self.model，返回 True/False

    ask(screenshot_path, prompt):
        # 读截图转 base64，POST /api/chat 返回纯文本。
        # 请求同时携带截图（images 字段）与 OCR 文字上下文（prompt），即 VLM 能看到实际画面。
        # qwen3 系列：顶层 think=False 关闭思考；已知怪癖 content 为空时回退 message.thinking

    parse_decision(response_text):
        # 从返回文本中解析 JSON 决策；校验 action/confidence 字段；click 时校验 targets 非空
        #（兼容旧字段 target_text，统一归一化为 targets 候选队列）；解析失败返回 {"action": "error"}
```

---

### 模块 6：ActionLogger（操作日志器）

**职责**：记录每一步操作的完整信息，写入 JSONL 文件用于审计和调试。

```
class ActionLogger:

    __init__(log_file):
        # 确保目录存在，打开文件追加写入

    log(step, action, details):
        # 写入一条 JSON 日志（timestamp/step/action/page_url/details），并打印到控制台
```

---

### 模块 7：FlowStateMachine（工作流状态机）

文件：[flow_state.py](flow_state.py)。显式记录观察、决策、操作、验证与升级阶段，检查非法状态跳转并输出可审计的状态记录。

```
class FlowState(str, Enum):
    BOOT / OBSERVE / DECIDE / ACT / VERIFY / WAIT / VIDEO / VLM_REASONING / HUMAN / COMPLETE / ERROR

class FlowStateMachine:
    transition(next_state, reason):
        # 校验合法跳转（非法跳转抛 RuntimeError），状态变化用分隔线显眼输出
```

---

## 四、核心工作流（主循环）

```
main(course_url, enable_vlm=True):

    # 1. 初始化模块
    browser / ocr / vlm / decision / sandbox / logger / flow(FlowStateMachine)

    # 1.1 VLM 健康检查（enable_vlm 且 config.ENABLE_VLM 时）
    vlm_ready = vlm.check_health()   # 不可用自动降级"无 VLM 模式"，思考页直接转人工
    decision.vlm_ready = vlm_ready

    # 2. 打开课程页面 + 登录页等待
    page = browser.navigate(course_url)
    if "login" in page.url.lower():
        等待用户手动登录（不进主循环，避免登录页反复截图闪动）

    # 3. 主循环
    while page_count < MAX_PAGES:
        # 3.0 暂停控制：按 p 键切换暂停/继续
        flow.transition(OBSERVE)

        # 3.0 检测 URL 自动跳转（平台课程完成/视频结束会跳页）
        if prev_url and current_url != prev_url:
            重置 no_progress_count / failed_candidates / consecutive_wait_count
            if _is_course_finished_jump(prev_url, current_url):
                # 详情页退回列表页 / 跳到完成页 URL → 判定本课完成 → 等用户打开下一节
                _wait_for_next_lesson(browser, prev_url); continue

        # 3.1 截图 + 3.2 OCR（失败重试 1 次），逐条打印 OCR 并写日志

        # 3.3 决策（候选队列按来源区分：dom / ocr / vlm）
        flow.transition(DECIDE, "根据 OCR 与 DOM 生成候选")
        dom_next = browser.find_next_button()   # DOM：活动页可见可操作的 btn-next 优先级最高（source=dom）
        if dom_next: decision_result = click(dom_next, source=dom)
        else:        decision_result = decision.decide(screenshot, ocr_results, page.url)
                     # OCR：关键词候选池（source=ocr）/ VLM：语义推理候选队列（source=vlm）

        # 3.3.1 DOM 兜底：OCR 空 / wait / error 时，读可见文字 + next-btn class 定位
        # 3.3.2 语义兜底：连续 >=3 次"未匹配"且非列表页且无视频时，VLM 判断推进按钮
        # 3.3.3 统一人工门禁：非 VLM 产生的 need_human，VLM 可用时先 _vlm_before_human 推理

        # 3.4 安全校验（URL 白名单 S1，偏离即终止）

        # 3.5 执行（一次观察只操作一个候选，失败后重新观察）
        #   click    -> candidates 逐个 click_and_verify；无效则记 failed_candidates，
        #               全部无效时走 VLM_REASONING，VLM 目标仍无效 -> HUMAN
        #   wait     -> 视频页进入 VIDEO（try_play_video + wait_for_video_end）；否则 wait 5s
        #   need_human -> HUMAN（wait_for_progress 监听 API/URL/Enter 自动继续）
        #   terminate  -> COMPLETE -> _wait_for_next_lesson 等用户打开下一节
        #   error      -> break
        #   升级顺序：未失败候选 -> 活动页可见 btn-next -> VLM_REASONING -> HUMAN

        page_count += 1

    # 4. 清理：browser.close() + 写 shutdown 日志
```

---

## 五、VLM 兜底详细流程

当 OCR 关键词匹配不到标准按钮，且页面命中题目关键词（或语义兜底触发）时，走 VLM：

```
_decision_engine._vlm_query(screenshot, ocr_results, page_url, prompt_template):

    1. 截图预处理：
       - 视口已是 414x896，与 VLM_IMAGE_WIDTH/HEIGHT 一致，直接使用；
         尺寸不同则等比缩放（以竖屏高为基准），保证 OCR/VLM 同一坐标系。
       - 保存为 ./logs/vlm_input_{timestamp}.png

    2. 构造 OCR 文字上下文：把 ocr_results 拼成带编号文字列表

    3. 构造 prompt：公共头(VLM_COMMON_HEAD) + JSON 格式约束 + 规则(VLM_QUESTION_RULES 或
       VLM_NAV_RULES) + 公共尾(VLM_COMMON_TAIL)
       - 题目兜底规则：优先点推进按钮；能确定答案则点正确选项；多选题一次把全部正确选项都放进 targets
         拿不准/开放题 -> need_human；结束提示 -> terminate；否则 wait
       - 语义兜底规则：只输出 click / need_human，判断页面上"能推进进度"的可点击元素
       - targets 是一个按优先级排序的候选目标文字数组（脚本会逐个尝试，降低 VLM 调用次数）

    4. 调用 VLM：response_text = vlm.ask(screenshot_path, prompt)
       （请求同时携带截图 base64 图像 + OCR 文字上下文，VLM 能看到实际画面；qwen3-vl:4b，think=False）

    5. 解析响应：decision = vlm.parse_decision(response_text)
       （click 时归一化为 targets 候选队列，兼容旧字段 target_text）

    6. 校验：action 白名单（click/wait/terminate/need_human）；只有 click 要求
       confidence >= VLM_CONFIDENCE_THRESHOLD（need_human/terminate 不限制）

    7. 反查坐标（VLM 只给文字，坐标由 OCR 反查）：
       - action == "click"：遍历 targets -> ocr_engine.locate_by_text 逐个反查 bbox -> 中心点
       - 构造 candidates 候选队列（去重），第一个反查不到就试下一个；全部失败 -> error（主循环转 need_human）

    8. 返回：{"action": "click", "x": ..., "y": ..., "target": ...,
              "candidates": [...], "confidence": ..., "source": "vlm"}
```

---

## 六、安全约束完整清单

以下约束在代码中硬编码实现，禁止通过配置关闭：

| 约束编号 | 约束名称 | 具体规则 | 违反时动作 |
|---------|---------|---------|-----------|
| S1 | 域名白名单 | page.url 的域名必须在 ALLOWED_DOMAINS 中 | 立即停止脚本 |
| S2 | 坐标边界 | 点击坐标必须满足 0 < x < viewport_width 且 0 < y < viewport_height | 拒绝执行该次点击 |
| S3 | 操作频率 | 两次操作间隔 >= MIN_DELAY_SEC (3秒) | 跳过本次操作，等待 |
| S4 | 操作上限 | 单次运行点击次数 <= MAX_CLICKS_PER_RUN (300) | 终止脚本 |
| S5 | 重复检测 | 点击后页面无变化（click_and_verify 返回 no_change），多候选逐个试错，全部无效转 VLM 推理，仍无效转人工 | 分级升级，超限才转人工 |
| S6 | VLM 输出校验 | action 必须在白名单（click/wait/terminate/need_human），click 时必须给出 targets 候选队列且至少一个能在 OCR 结果中定位到 | 拒绝执行，记录日志 |
| S7 | 禁止文件系统写入 | 脚本中不得出现 os.remove / shutil / subprocess / os.system | 代码审查时检查 |
| S8 | 禁止外部导航 | 不得调用 page.goto() 跳转到白名单以外的 URL | 代码审查时检查 |
| S9 | JS 执行仅限定位/点击 | page.evaluate/frame.evaluate 仅用于 DOM 定位与点击（elementFromPoint/click），不得执行任意未审核逻辑 | 代码审查时检查 |
| S10 | 紧急停止 | 监听 Ctrl+C 键盘事件，捕获 KeyboardInterrupt | 立即关闭浏览器并退出 |

---

## 七、异常处理策略

| 异常类型 | 触发条件 | 处理策略 |
|---------|---------|---------|
| OCR 识别失败 | ocr.recognize() 返回空列表或抛出异常 | 重试 1 次，仍失败则进入 DOM 兜底 |
| VLM 调用失败/超时 | POST 请求超时或抛异常 | 返回 error，主循环转 need_human（不反复重试） |
| VLM JSON 解析失败 | 返回文本中无法提取有效 JSON | 返回 error，主循环转 need_human |
| 网络请求失败 | page.goto() 或 wait_for_network_idle() 超时 | navigate 内部重试，仍失败则记录错误 |
| 浏览器崩溃 | Playwright 抛出异常 | 记录错误，重新 navigate 到当前 URL，最多重试 3 次 |
| 用户中断 | 用户按下 Ctrl+C | 捕获 KeyboardInterrupt，关闭浏览器，保存日志，正常退出 |

---

## 八、日志输出规范

控制台日志格式（每行一条，带前缀；状态机变化用分隔线突出显示）：

```
[VLM] 检查 Ollama 服务（http://localhost:11434, 模型 qwen3-vl:4b）...
[OCR] 1. "开始学习" @ (207, 620) 置信度: 0.97
[候选] 本次点击候选 2 个（来源: ocr）:
       1. "下一页" @ (207,720) 置信度: 0.95
       2. "继续" @ (300,400) 置信度: 0.80
======================================================================
[状态 #3]  observe  ==>  decide
  原因: 根据 OCR 与 DOM 生成候选
======================================================================
[CLICK] 命中元素 <BUTTON> cls='btn-next' (iframe 内) @ (207, 720)
[网络] 已收到进度响应(翻页): HTTP 200
[点击生效] 检测到 progress_response:200
```

日志落盘：`logs/action_log.jsonl`（每步 JSON 行），`report.py` 生成 `logs/report.html` 可视化台账。

---

## 九、依赖安装清单

```
# Python 依赖（见 requirements.txt）
pip install -r requirements.txt

# Playwright 浏览器驱动（首次运行）
playwright install msedge

# 注意：PaddleOCR 首次运行会自动下载检测/识别模型

# Ollama 模型（独立安装，不在 Python 依赖中）
# 1. 下载安装 Ollama: https://ollama.com
# 2. 拉取视觉模型: ollama pull qwen3-vl:4b
# 3. 启动服务: ollama serve（后台运行）
```

---

## 十、运行方式

```
# 1. 生成本地平台配置（只留本地、不上云）
python setup_local.py
#    （或手动：copy config_platform.example.py config_platform.py 后填写）

# 2. 确保 Ollama 服务正在运行（VLM 兜底需要；不需要可跳过）

# 3. 启动脚本（不传 URL 时默认打开 config_platform.py 中的主页）
python main.py
python main.py "https://<平台域名>/课程地址"

# 跳过 VLM（不调用 Ollama），所有需要"思考"的页面直接转人工：
python main.py "https://<平台域名>/课程地址" --no-vlm
# 或设置 config.py: ENABLE_VLM = False

# 4. 脚本启动后打开 Edge 浏览器；如需登录请手动完成，登录后自动继续
# 5. 按 p 暂停/继续，按 Ctrl+C 停止

# 本地回归测试（不连真实平台，自动起服务器跑 test_page.html 全流程）
python test_flow.py
python test_flow.py --no-vlm
python test_flow.py --port 8000

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
| 操作频率 | 两次操作间隔在 3~15 秒之间 |
| 日志完整 | action_log.jsonl 中每步操作都有记录 |
| 紧急停止 | 按 Ctrl+C 后浏览器在 3 秒内关闭 |
| 无异常写入 | 脚本不写入任何非日志文件到磁盘 |

---

## 十二、实现演进与辅助工具

本项目从 0 到跑通经历了大量迭代，关键技术决策、踩坑记录、点击定位演进史详见 **[DEVELOPMENT_LOG.md](DEVELOPMENT_LOG.md)**（开发记录）。

本 PRD 描述的是「产品需求 + 目标行为」，具体实现细节（iframe 定位、视频页处理、候选池、状态机等）以下面文件为准：

| 文件 | 作用 |
|------|------|
| `DEVELOPMENT_LOG.md` | 踩坑记录、技术演进史、配置说明 |
| `debug_ocr.py` | 单独对某张截图跑 OCR（多尺度 + 亮度检测），排查"识别不到"问题 |
| `debug_api_listen.py` | 监听翻页/答题 API 请求，验证推进信号 |
| `report.py` | 解析 action_log.jsonl 生成 `logs/report.html` 可视化台账 |
| `test_flow.py` / `test_page.html` / `test_interaction.py` | 本地回归测试（不连真实平台） |

核心定位分工：**OCR 提供文字与坐标**（识别文字、给大致坐标、判断页面类型、供候选队列与反查定位），**DOM 提供可见/可点击元素与精确定位**（elementFromPoint 反查真实元素、切 iframe），**VLM 看截图并做语义判断**（同时接收截图图像与 OCR 文字，输出候选目标文字，坐标仍由 OCR 反查）。
