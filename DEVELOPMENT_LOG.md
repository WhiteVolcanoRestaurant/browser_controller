# 开发记录与踩坑总结

> 本文记录「基于 Playwright + PaddleOCR + Ollama 的课程学习自动化脚本」在课程平台（域名与接口特征见本地 `config_platform.py`，不写入仓库）上从 0 到跑通的完整过程、踩过的坑、以及最终采用的方案。供后续维护与同类项目参考。

## 一、当前状态（开发进度总结）

**核心链路已跑通，处于"可运行、边用边调优"阶段。**

已完成并验证：
1. **登录 → 选课 → 详情页自动翻页 → 答题 → 视频 → 完成** 全链路可跑通。
2. **iframe 内点击**：课程内容在全屏 iframe 里，已用 frame API 切进内部定位并点击（此前多次失败的根因）。
3. **API 监听**：`page.on("request")` 捕获本地配置的推进接口特征（翻页 / 答题提交，见 `config_platform.py` 的 `PROGRESS_API_MARKS`），用于判断"推进（翻页、提交）是否生效"。已用 `debug_api_listen.py` 实测通过。
4. **VLM 双提示词**：题目作答 + 语义兜底（找推进按钮），抽取公共部分、加位置提示。
5. **分级降级恢复**：等待 → DOM 重定位 → VLM 语义兜底 → reload（最后手段）→ 人工（监听 API 自动继续）。
6. **VLM 健康检查 + 跳过机制**：启动时 `check_health()`，`--no-vlm` / `ENABLE_VLM=False` 可跳过。
7. **可视化台账**：`report.py` 生成 `report.html`，含困难样本（含 VLM 返回内容）。

仍需验证/打磨：
- 知识卡片类交互页（逐个点"请点击查看"）VLM 的定位准确度。
- VLM 语义兜底在小模型 llava-phi3 上的稳定命中率。
- `images_changed` 降采样阈值（当前 8.0）在真实页面的适配。

## 二、核心架构决策

1、**VLM 不输出坐标，只输出目标文字**：VLM 返回 `action + target_text`，再由 OCR 结果反查 `target_text` 的 bbox 得到精确坐标。避免视觉模型定位不准。

2、**决策分层**（[decision_engine.py](file:///c:/prog_file/code_with_vsc/browser_controller/decision_engine.py)）：
- ps：为什么不是按照”步骤 0 结束检测：命中 `END_TEXTS`（已完成/学习完成…）→ `terminate`。”提前结束课程，是因为遇到了一节课，参考案例17。
- 步骤 1 翻页按钮：`start → next` 的 OCR 关键词匹配。**优先于结束检测与题目检测**——阶段性完成页"恭喜你，你已完成了本微课"+"下一页"会优先点"下一页"，而不是误判成课程结束。
- 步骤 2 结束检测：无可点翻页按钮时，命中 `END_TEXTS`（课程的学习已完成…）→ `terminate`。结束页正文是"课程的学习已完成"，按钮"返回列表"可能与其它页面内容冲突，不用按钮文字判定。
- 步骤 3 题目检测：命中 `QUESTION_KEYWORDS`（多选/判断/哪些…）→ VLM 做题。
- 步骤 4 提交按钮：`submit` 关键词匹配。
- 步骤 5 引导点击：`guide_click`（点击了解/点击查看/点击进入…）——标准翻页/提交都没有时，点页面底部的"点击 xxx"引导元素（反诈案例页常见）。排 submit 之后、wait 之前，是无 VLM 模式下推进的最后机会。
- 步骤 6 兜底：OCR 空则 wait，非题目无按钮则 wait。

3、**移动端视口**：`VIEWPORT 414x896` + iPhone UA，消除 H5 页面两侧留白，OCR 只关注课程卡片区域，识别率更高。

## 三、踩过的坑（按时间顺序）

### 1、OCR 为空时误触发 VLM → 报错退出
- **现象**：登录页 OCR 识别 0 条文字，旧逻辑把「OCR 为空」当成「需要 VLM 兜底」，导致 VLM 报错或找不到目标，直接 shutdown。
- **根因**：登录页还没渲染/未登录，本就不该做决策。
- **解法**：OCR 为空时直接 `wait`，并加「登录页 URL 含 login 时等待用户手动登录」的前置判断。

### 2、页面闪动刷新
- **现象**：每截一次屏，画面就「铺满窗口一下又缩回」。
- **根因**：`deviceScaleFactor=2` 会让 Chromium 屏幕放大 2x 显示、截图时又回到 1:1 读回，导致闪烁（Playwright 已知问题）。
- **解法**：`DEVICE_SCALE_FACTOR` 必须为 1。

### 3、「操作过于频繁」隔一条 block 一条
- **根因**：`validate_rate_limit` 只在「通过」时更新时间戳，「拦截」时不更新，导致通过/拦截交替。
- **解法**：把频率校验从「每轮循环」移到「真正点击前」，避免 wait 循环被误拦截。

### 4、死循环直接 close 浏览器
- **现象**：连续无变化就 `break` + `close()`，丢失登录态、不给恢复机会。
- **解法**：改为「分级降级」——加长等待 → DOM 重定位 → reload 刷新 → 人工介入 → 才关闭；reload 设上限（`MAX_RELOAD_COUNT`）防封号。

### 5、识别到"已完成"却不退出
- **根因**：结束检测只写在 click 分支的 3.8，`decide()` 里没有，导致"已完成"落到最后的 `wait` 永远循环。
- **解法**：把结束检测提到 `decide()` 最前面（步骤 0）。**（后续细化：结束检测改为排在翻页按钮匹配之后、且只认"课程的学习已完成"等正文，见坑 17。）**

### 6、【核心坑】课程内容在 iframe 里，点击穿透失败
- **现象**：日志 `命中 IFRAME -> 点击 <IFRAME> 中心`，点的是 iframe 中心空白，按钮没反应。
- **根因**：`document.elementFromPoint` 只能看到主文档 DOM，命中的是 iframe 元素本身，穿不透 iframe 内部的 `<a><img>` 按钮。
- **解法**：用 Playwright 的 frame API——`_frame_at()` 找到覆盖坐标的 iframe，`frame.evaluate()` 切进 iframe 内部重新定位并派发点击。

### 7、图片按钮 DOM 里没有文字
- **现象**："开始学习"是 `<a><img>`，OCR 识别的是图片像素文字，DOM 文本节点里没有"开始学习"。
- **影响**：靠 textContent 的 DOM 兜底找不到它，只能靠 OCR 坐标反查。

### 8、「继续」没进 next +「不确定」误匹配「确定」
- **现象**：问卷页卡在"继续"按钮；且系统把"不确定"当成"确定"去点。
- **根因**：
  1. `next` 关键词列表缺"继续"（翻页词会变：下一页/继续/下一步）。
  2. `filter_by_keywords` 用 `k in text` 子串匹配，"**不确定**"包含"确定"被误命中 submit。
- **解法**：
  1. `next` 补"继续/下一节/下一章"。
  2. `filter_by_keywords` 加「否定形式排除」：若 text 含 "不"+关键词（如"不确定"），跳过。

### 9、视频播放器页（OCR 识别不到播放按钮）
- **现象**：课程里嵌视频，默认不自动播放，需要点播放按钮；播放按钮是图形图标 OCR 识别不到；播放中画面无文字按钮，一直"未匹配到任何目标"。后续测试又暴露三个新问题：① 检测到视频却没正确等待播完；② 没正确开始播放；③ 把动态页里的隐藏 `<video>` 误判成视频播放器。
- **根因**：
  1. 播放按钮是图标（非文字），OCR 只认文字；播放中视频画面是动态帧，没有可点文字。
  2. 旧 `detect_video()` 只要页面存在任意 `<video>` 元素就返回 has_video，不判断可见性/是否有真实内容，导致隐藏/占位/背景视频被误判。
  3. 旧等待逻辑写死 `browser.wait(10000)`，没有"等到 ended"的实现；`wait_for_video_playing` 是死代码，且它等的是"开始播放"而非"播完"。
  4. 旧 `try_play_video()` 只点第一个候选、点完只等 600ms，平台播放按钮 class 不匹配或加载慢就误判"没开始"。
- **解法**（[browser_controller.py](file:///c:/prog_file/code_with_vsc/browser_controller/browser_controller.py) / [flow_state.py](file:///c:/prog_file/code_with_vsc/browser_controller/flow_state.py) / [main.py](file:///c:/prog_file/code_with_vsc/browser_controller/main.py) / [config.py](file:///c:/prog_file/code_with_vsc/browser_controller/config.py)）：
  1. `detect_video()` 只认「可见 + 有真实内容」的 video，并新增返回 ended/duration/currentTime/readyState（过滤规则详见下方 9.1）。
  2. `try_play_video()` 收集全部可见播放控件候选（含 `video` 本体），逐个点击试错，每次点击后轮询最多 3 秒确认 playing。
  3. 新增 `wait_for_video_end()`：每 `VIDEO_POLL_INTERVAL_MS`(15s) 检测一次是否播完并截图写 `video_polling` 日志，整体循环即进程保活；`VIDEO_WAIT_TIMEOUT_MS`(20min) 超时转人工。
  4. 状态机新增 `VIDEO` 状态：`WAIT → VIDEO → OBSERVE/HUMAN`，明确"视频播放/等待播完"阶段。
  5. main.py 的 wait 分支改为进入 `VIDEO` 状态并调用 `wait_for_video_end`，删掉写死的 `wait(10000)`。

### 9.1、detect_video 判断规则与数字常量（后续调精度有迹可循）
`detect_video()` 的判定目标：只认「可见 + 有真实内容」的 `<video>`，过滤三类干扰——隐藏/占位视频、完全在视口外的视频、空壳 `<video>`（无 src、连元数据都没加载）。命中第一个"可见且真实"的 video 即返回（含 iframe 内）。各阈值含义：

1. **宽高 < 2px 过滤**：课程主播放器通常占满卡片宽度（几百 px），而"1px 探针/占位 video"是预加载用的不可见元素。取 `< 2` 而非 `<= 0`，是把 1px 探针一并排除，同时容忍亚像素级 CSS 缩放误差。
2. **opacity <= 0.05 过滤**：隐藏视频常用 `opacity:0` 而非 `display:none`（为了保持加载），也有接近 0 的淡入淡出帧。0.05 与项目里 `_find_by_class` / `find_text_element_center` 的可见性判断保持一致（同一个"肉眼不可见"口径）。
3. **视口外过滤**：`r.top<0 || r.left<0 || r.top>=innerHeight || r.left>=innerWidth` 只判断"完全在屏幕外"，不要求"完整在屏幕内"，因为主播放器可能有一小部分被布局截断但仍可见可播放；完全越界的是轮播预加载的下一屏或 CSS 移出屏幕的隐藏视频。
4. **readyState >= 1（HAVE_METADATA）**：`readyState 0 = HAVE_NOTHING`（连元数据都没有，是空壳占位）；`>=1` 说明已加载出时长/尺寸，可证明是真实有内容的视频。不用更严的 `>=2`（HAVE_CURRENT_DATA），因为 paused 且未预加载时可能停在 1，过严会漏检。
5. **isFinite(duration) && duration > 0**：直播流 duration 为 Infinity、未加载元数据时 duration 为 NaN，两者都不算"有真实时长"，要排除。
6. **有源（currentSrc || src）**：currentSrc 是浏览器实际解析出的源（含 blob:，JS 动态赋值后才有值），src 是标签属性，任一非空都说明不是空壳。

> 调精度时优先看这些阈值：若真实课程视频被漏检，先怀疑 `readyState>=1` 或 `宽高<2` 过严；若仍误判"有视频"，先怀疑是否还有别的可见 `<video>`（如背景视频）没被 content 判断拦住。

### 10、Page 没有 wait_for_request 方法（API 监听完全失效）
- **现象**：点了"下一页"脚本毫无反应，`wait_for_progress` 永远超时。
- **根因**：误用了不存在的 `page.wait_for_request()`，抛 AttributeError 被 `except: pass` 吞掉。
- **解法**：`page.on("request")` 注册事件 + `page.wait_for_timeout` 驱动事件循环轮询；点击验证用 `expect_request` 包裹点击。已用 `debug_api_listen.py` 实测：翻页 / 答题提交接口均可捕获。

### 11、点击无效直接 reload，重置了学习进度
- **现象**：知识卡片页（4 个"请点击查看"卡片，全点完才能"下一页"），OCR 误点"全部查看后才可以继续进行课程"提示文字，3 次无效后 reload，把已查看进度清零。
- **根因**：分级降级链（等待→DOM重定位→reload→人工）里没有 VLM 这一环；reload 会重置页面交互状态，却排在人工之前。
- **解法**：降级链改为 5 级：等待→DOM重定位→**VLM语义兜底**→reload（最后手段）→人工（监听 API 自动继续）。

### 12、VLM 无健康检查、无跳过机制
- **现象**：启动前从不检测 Ollama 是否可用；不想用 VLM 的用户没有开关。
- **解法**：启动时 `check_health()`（不可用自动降级无 VLM 模式）；`--no-vlm` 命令行参数 + `ENABLE_VLM` 配置项；`DecisionEngine.vlm_ready=False` 时所有 VLM 调用直接转 need_human。

### 13、列表页被语义兜底幻觉出"推进按钮"
- **现象**：在课程列表页（`#/course?projectType=...`），语义兜底让 VLM 判断推进按钮，VLM 把某个课程卡片幻觉成"点击词云查看防骗要点"，点了无效还反复触发 reload，重置了进度。
- **根因**：语义兜底本为"详情页/内容页的翻页按钮"设计，用在列表页上，VLM 会在课程列表上幻觉出"推进按钮"。
- **解法**：语义兜底触发前先判断 URL——不含 `COURSE_DETAIL_URL_MARK`（`/course/detail`）即列表页，直接 `need_human`（提示用户选课），不走语义兜底。

### 14、点击验证信号太窄，误判"无反应"
- **现象**："开始学习"按钮 `<a><img>` 被点击（`clicked=True`），但页面 URL 不变、也不发翻页上报接口，`wait_for_progress` 超时误判"无反应"，反复重试。
- **根因**：验证推进只看「API 变化 + URL 变化」，漏掉"页面内容变了但 URL 不变、API 不发"的情况（如封面→内容）。
- **解法**：新增 `images_changed()` 截图兜底——降采样到 48x48 比较灰度差，容忍动画微小变化，只对"封面→内容"这种显著变化敏感。`click_and_verify` 的验证顺序：API > URL > 截图变化。

### 15、多候选试错（误匹配的兜底）
- **现象**：正文"找辅导员确认"含"确认"，误命中 submit，点击无反应后直接死循环。
- **根因**：同一关键词可能命中多个 OCR 位置，但旧逻辑只取第一个（置信度最高）点，点错就卡死。
- **解法**：`_build_candidates()` 返回同一关键词命中的多个位置，main 循环逐个 `click_and_verify`，点一个无反应就换下一个候选，直到某个真正生效。

### 16、反诈案例页"点击了解经过"匹配不到 → 无 VLM 卡人工；正文关键词陷阱
- **现象**：测试日志（step 83）OCR 识别到"刚出高铁站…""遭遇诈骗了""点击了解经过"(y=683 页面底部)，但 `TARGET_BUTTONS` 无"点击 xxx"类词 → 未匹配 → 无 VLM 模式直接 `need_human`。
- **根因**：翻页/提交关键词表只覆盖标准按钮词（下一页/继续/提交/确定），没有反诈案例页常见的"点击了解经过"这类**引导语按钮**；而裸"点击"太宽泛，正文"骗子引诱点击陌生链接"也会命中，误点风险大。
- **解法**（[config.py](file:///c:/prog_file/code_with_vsc/browser_controller/config.py) / [ocr_engine.py](file:///c:/prog_file/code_with_vsc/browser_controller/ocr_engine.py) / [decision_engine.py](file:///c:/prog_file/code_with_vsc/browser_controller/decision_engine.py)）：
  1. 新增 `guide_click` 关键词组，**用短语不用裸"点击"**（点击了解/点击查看/点击进入/点击学习/点击打开/点击播放），避免命中正文里的"引诱点击"。
  2. 匹配顺序排在 submit 之后、wait 之前（步骤 3.5），无 VLM 模式下推进的最后一次机会。
  3. **全部匹配改为"从下到上"排序**（置信度不好量化，直接用位置）：`filter_by_keywords` 按 y 坐标降序、DOM 兜底 `find_text_element_center`/`find_next_button` 取最靠下命中。依据：推进按钮通常在页面底部、正文在上方，先点最靠下的候选可避开正文误匹配。
- **已知局限**：正文含"确认"（如"转账前需要再三确认"）仍会先命中 submit"确认"（坑 8/15 同源，submit 关键词过宽），抢在 guide_click 之前被点击；若页面底部真实按钮也含 submit 关键词（如"确认提交"），从下到上排序会优先点到底部按钮。后续可考虑收紧 submit 关键词（排除"再三确认"类上下文）。
- **回归测试**：`test_page.html` 第 3 页加入"反诈案例（关键词陷阱回归页）"——正文含"骗子引诱点击陌生链接""转账前需要再三确认收款人身份"，底部按钮"点击了解经过"。

### 17、阶段性完成页"你已完成了本微课"+"下一页"被误判课程结束直接 terminate
- **现象**：真实日志（step 19）页面 OCR："恭喜你""你已完成了本微课""下面让我们看看你掌握的如何吧~""上一页""下一页"。旧逻辑结束检测（`END_TEXTS` 含裸"已完成"）优先级最高，命中"你已完成了本微课"→ `terminate`，跳过"下一页"。
- **根因**：
  1. 结束检测排在翻页按钮匹配**之前**（坑 5 的旧方案），"已完成"裸词又太宽泛——阶段性文案"你已完成了本微课"（后面还有"下一页"进测验）被当成课程结束。
  2. 真正的课程结束页是正文"课程的学习已完成"+按钮"返回列表"；"返回列表"与其它页面内容冲突，不能当判定词。
- **解法**（[config.py](file:///c:/prog_file/code_with_vsc/browser_controller/config.py) / [decision_engine.py](file:///c:/prog_file/code_with_vsc/browser_controller/decision_engine.py)）：
  1. **翻页按钮匹配提到结束检测之前**：页面同时存在"完成文案"和"下一页"时，优先点"下一页"（有可点翻页按钮就不判结束）。
  2. `END_TEXTS` 去掉裸"已完成"，改为以正文"课程的学习已完成"为准（保留"学习完成/课程完成/结束"）。
  3. 验证：阶段性完成页 → click "下一页"(325,722)；结束页"课程的学习已完成"+返回列表 → terminate。

### 19、课程结束页有"继续学习"按钮 → 结束判定被"翻页按钮优先"跳过（坑 17 的反面）
- **现象**：视频课播完后 URL 从 `/course/detail` 跳到 `/wk/comment`（完成/评论页），OCR 识别到"课程的学习已完成"+"继续学习"+"下一课"+"返回列表"。脚本点了"继续学习"（no_change 无效），最后靠 VLM 点"返回列表"才切到下一课，全程没触发 terminate。
- **根因**：坑 17 把"翻页按钮匹配"提到"结束检测"之前。完成页上的"继续学习"命中 start 关键词，`decide()` 直接 `return click`，跳过了"课程的学习已完成"的结束检测。
- **解法**（[config_platform.py](file:///c:/prog_file/code_with_vsc/browser_controller/config_platform.py) / [config.py](file:///c:/prog_file/code_with_vsc/browser_controller/config.py) / [main.py](file:///c:/prog_file/code_with_vsc/browser_controller/main.py) / [decision_engine.py](file:///c:/prog_file/code_with_vsc/browser_controller/decision_engine.py)）：
  1. `config_platform.py` 新增 `COURSE_FINISH_URL_MARK="/wk/comment"`（完成页 URL 特征）与 `COURSE_FINISHED_TEXT="课程的学习已完成"`（结束页固定正文）。
  2. `_is_course_finished_jump()` 增加"跳到完成页 URL"也算结束（`reached_finish`）：视频播完自动跳转完成页即可触发 `completed`，不依赖 OCR。
  3. `decide()` 步骤 0：`COURSE_FINISHED_TEXT` 严格短语匹配时直接 `terminate`（优先于按钮匹配）。坑 17 的阶段性完成页"你已完成了本微课"不含"课程的学习已完成"完整短语，不会被误伤。

### 18、OCR 字距大时在字间插空格（"继  续"）→ 匹配不到按钮
- **现象**：真实日志（step 13）OCR 识别到"继  续"（字间有空格），`filter_by_keywords` 的 `k in text` 子串匹配对不上"继续"，无 VLM 模式卡 need_human。
- **根因**：按钮文字两个字间距过大时，PaddleOCR 会在字间插入空格；且该按钮置信度被拉低到 0.64，低于 `OCR_CONFIDENCE_THRESHOLD`（0.7）又被候选过滤。
- **解法**（[ocr_engine.py](file:///c:/prog_file/code_with_vsc/browser_controller/ocr_engine.py) / [decision_engine.py](file:///c:/prog_file/code_with_vsc/browser_controller/decision_engine.py) / [config.py](file:///c:/prog_file/code_with_vsc/browser_controller/config.py)）：
  1. 新增 `compact_text()`：匹配前去掉文本内所有空白（含全角空格）。`filter_by_keywords`、`locate_by_text`、`decide()` 的 `all_text`（END_TEXTS / QUESTION_KEYWORDS 判定）统一使用。
  2. `OCR_CONFIDENCE_THRESHOLD` 0.7 → 0.6：字距大时置信度被拉低到 0.6x，去空格匹配成功后应允许点击。
  3. `QUESTION_KEYWORDS` 移除"以下"：正文"只要做到以下几点就能防骗"含"以下"，会被误判成题目页（预先存在的问题，与本次同页暴露）。
  4. 验证：原日志页 → click "继  续"(307,719)。

### 20、重构点击层删除 iframe 处理，回归坑 6，脚本完全无法推进
- **现象**：master 在「重构点击层并校验进度响应」（5002467）之后，线上课程详情页
  点击全部 `no_change`；日志 `命中元素 <IFRAME>` 后 `touch+mouse` 点不中；开启
  JS 兜底后 `JS 保底点击 <DIV> cls='viewport'>`，点的是 iframe 父容器而非按钮。
- **根因**：5002467 把 `click()` 从「命中 IFRAME → `_frame_at()` 切 frame →
  `_CLICK_JS`（元素吸附 + `t.click()`）」改成了纯输入层 tap/click，一并删掉了
  iframe 处理与兜底。而演进史阶段 3/4 早已验证：纯输入层在移动端模拟下穿透
  iframe 失效。等于把坑 6 的解法整个删掉，重新踩回坑 6。
- **解法**（browser_controller.py / config.py / main.py）：
  1. `_js_click()` 与 `_log_click_target()` 命中 iframe 时先 `_frame_at()` 切进
     frame，用内部坐标 `(x-ox, y-oy)` 再 `elementFromPoint` + `element.click()`。
  2. 新增 `ENABLE_JS_CLICK_FALLBACK`（默认 True）：真实输入后追加 JS 合成 click 兜底，
     否则 iframe 课程页无法推进。
  3. `_real_click` 移动端恢复 touch+mouse 双发（真实移动端触摸本就产生 touch + 合成 mouse）。
  4. 新增 `read_key()` 支持按 p 暂停/继续；命中/保底诊断写入 action_log.jsonl
     （`click_hit` / `js_click`）。
- **教训**：重构点击层时，坑 6 的 iframe 处理是「推进课程」的命脉，不能随
  「DOM 无副作用观察 + 输入层点击」的抽象一并删掉；iframe 场景必须保留 frame API 切帧。

## 四、点击定位的演进史（重要经验）

| 阶段 | 做法 | 结果 |
|---|---|---|
| 1 | `page.mouse.click(OCR坐标)` | 坐标未穿透 iframe/有缩放，点偏 |
| 2 | JS `elementFromPoint().click()` | 主文档只命中 iframe 元素，穿透不了 |
| 3 | 定位元素中心 + `page.mouse/touchscreen` 穿透点击 | 移动端模拟下穿透仍失效 |
| 4 | 命中 iframe 就用原始坐标穿透 | iframe 内外缩放导致坐标对不上 |
| 5 | frame API 切进 iframe 内部 `elementFromPoint` + `.click()` | 能推进，但属于 JavaScript 直接激活 |
| 6 | **DOM/OCR 只给坐标，Playwright 输入层单次 tap/click** | ✅ 当前方案，不再伪造 TouchEvent 或调用 element.click() |

**结论**：DOM 用于无副作用观察，操作统一走浏览器输入层；移动模式只发送一次 touch，桌面模式只发送一次 mouse。截图像素、CSS 视口、iframe 与 DPR 仍需保持一致。

## 五、关键配置（config.py）

| 配置 | 值 | 说明 |
|---|---|---|
| `VIEWPORT_WIDTH/HEIGHT` | 414 / 896 | 手机竖屏，消除留白 |
| `DEVICE_SCALE_FACTOR` | 1 | 必须为 1，否则截图闪动 |
| `VLM_CONFIDENCE_THRESHOLD` | 0.4 | llava-phi3 小模型置信度偏低，放宽 |
| `MAX_RELOAD_COUNT` | 2 | 自动刷新上限，防封号 |
| `COURSE_DETAIL_URL_MARK` | `/course/detail` | 详情页 URL 特征，用于「往回跳即结束」 |
| `NEXT_BUTTON_CLASS_HINTS` | next-btn/next/btn-next | 翻页按钮 class 特征 |
| `TARGET_BUTTONS["guide_click"]` | 点击了解/查看/进入… | 引导语按钮（反诈案例页），短语匹配防"引诱点击"误命中 |

## 六、后续优化方向

1、**利用 `next-btn` class 定位翻页**（已实现）：翻页按钮 class 恒定（next-btn），比 OCR 文字（下一页/继续/下一步会变）更可靠。已加 `find_next_button()` 作为 DOM 兜底。

2、**监听网络 API**（已实现）：`wait_for_progress()` 与 `click_and_verify()` 同时观察匹配请求和响应；两者都出现才记为 `progress_response`。不解析、不构造 next 正文，消息仍由页面自身生成。

3、**可视化统计台账**（已实现）：`python report.py` 解析 `action_log.jsonl` 生成 `logs/report.html`，展示统计概览 + 困难样本（带截图）。困难样本判定：
   - `vlm_failed`（**VLM 校验后依然失败**，附 VLM 原始返回内容）—— 最核心的困难样本，见下方「困难样本定义」。
   - `click_no_effect`（点击无效）
   - `blocked`（被沙箱拦截）
   - 连续 ≥2 次 `wait` 且 reason 含"未匹配到任何目标"（OCR 识别到文字但匹配不到按钮）
   - 按「识别文字」去重，相似样本取一张。

## 六·五、困难样本定义（明确口径）

**困难样本 = 自动化链路（OCR → DOM → VLM）都无法独立推进、需要人工或二次分析介入的页面。**

判定优先级（满足任一即为困难样本）：
1. **`vlm_failed`**：经过 VLM 校验（语义兜底/题目作答）后，仍无法成功推进（VLM 给了错误目标 / 点击无效 / VLM 直接放弃）。**必须记录 VLM 的实际返回内容**，供复盘"VLM 到底看成了什么"。
2. **`click_no_effect`**：点击后页面/API/截图均无变化。
3. **`blocked`**：被安全沙箱拦截（坐标越界/死循环/频率）。
4. **连续 ≥2 次 `wait` 未匹配**：OCR 识别到文字但反复匹配不到任何按钮（换行/图标/语义引导按钮）。

日志落点：`vlm_failed` 事件由 [main.py](file:///c:/prog_file/code_with_vsc/browser_controller/main.py) 分级降级第 3 级记录，字段含 `vlm_raw`（VLM 原始返回）+ `ocr_texts`（当页 OCR 文本）。`report.py` 会单独展示这些样本的 VLM 返回内容。

## 七、仍未解决的难点（值得持续记录）

1、**按钮文字换行导致 OCR 拆词**：例如"怎么做到的"被拆成"怎么做"+"到的?"两行，脚本无法把两段拼成完整按钮名，导致匹配不到目标。这是 OCR 的固有局限，需靠 next-btn class 定位或跨行文本合并来缓解。

2、**知识卡片类交互页**（需逐个点击"请点击查看"卡片才能解锁"下一页"）：VLM 语义兜底一次只能给出一个目标，需多轮循环逐个点完。若 VLM 找不准卡片位置，会走人工。属于重点困难样本。

## 八、调试小技巧

1、`[CLICK]` / `[DOM]` 的定位日志是 `print` 到终端的，**不在 action_log.jsonl 里**，排查点击问题要看终端输出。

2、`debug_ocr.py` 可单独对某张截图跑 OCR（含 1x/1.5x/2x 多尺度 + 亮度检测），用于快速判断「是截图空白还是 OCR 没识别出来」。

3、OCR 结果乱码（"鎴戜滑閮芥槸"）只是 jsonl 文件被终端按 GBK 读导致的显示问题，不影响实际逻辑。

## 九、本地回归测试（test_page.html + test_flow.py）

`test_page.html` 按难度递增模拟：文字按钮 → 可见的无文字 `img.btn-next` → 完成四张卡片后才显示的图片按钮 → OCR 陷阱 → 题目页。正常翻页会向本地 `/progress/next` 发请求并收到 204 响应。

快速回归浏览器输入层与状态机：

    .\.venv\Scripts\python.exe -m unittest -v test_interaction.py

跑全流程（自动起本地服务器，无需再手动 `python -m http.server`）：

    python test_flow.py              # 默认：VLM 启动时健康检查，不可用自动降级
    python test_flow.py --no-vlm     # 跳过 VLM，多选题转人工
    python test_flow.py --port 8000  # 指定服务器端口（默认自动选空闲端口）

说明：

1、`test_flow.py` 自动完成「起服务器 → 打开 http://127.0.0.1:<port>/test_page.html → 跑完整流程 → 关服务器」。

2、测试页第 5 页"多选题"：有 Ollama 时 VLM 自动作答；无 VLM 时会停住等人工作答，脚本检测到翻页后自动继续（与生产逻辑一致）。

3、走到「已完成」页即判定流程跑通、自动退出；Ctrl+C 随时停止，服务器自动关闭。

4、**为何不用 .bat**：此前的 `start.bat` / `test_flow.bat` 双击会秒退出（venv 路径或终端上下文问题），已删除，统一用 `python main.py` / `python test_flow.py` 启动，`--no-vlm` / `--port` 等参数也更灵活。
