# browser\_controller

基于 **Playwright + PaddleOCR + Ollama VLM** 的网页课程自动化脚本：在使用者本人对课程内容理解的基础上，辅助完成课程学习流程（翻页、点击按钮、答题、处理视频）。

> ⚠️ **早期开发版本（Early Stage）**，主要面向协作开发者，当前仅在某单一平台做测试。核心链路已跑通，但仍有若干已知局限（见 [开发进度](#三开发进度)）。
>
> ⚠️ **合规与免责声明 (Disclaimer)**
>
> 1. **技术研究目的**：本项目（browser\_controller）的设计初衷仅为探讨 Playwright 浏览器自动化、PaddleOCR 图像识别以及 VLM 视觉大模型的综合应用，作为协同推理思想验证项目之一。代码仅供开发者本地学习与测试自动化技术，**不针对任何特定教育或培训平台**。
> 2. **禁止非法与商业用途**：严禁任何人将本项目用于任何形式的商业盈利（包括但不限于代刷课、售卖脚本、提供代看服务等），严禁用于破坏各平台的防作弊及公平机制。
> 3. **风险自担**：使用者在使用本项目时，须自行确认是否违反目标平台的用户服务协议。**因使用本工具导致的任何后果（包括但不限于账号封禁、成绩/学分作废、法律追责等），均由使用者本人自行承担**，本项目开发者不承担任何直接或间接的连带责任。
> 4. **无偿赠与及无服务承诺**：本项目全开源免费。如果在底部通过赞赏码或平台对开发者进行支持，该行为属于**完全自愿的无偿赠与**。开发者**不提供**任何特定平台的适配、售后支持、代挂服务或答疑保证。

核心分工：**OCR/VLM 理解画面**，**DOM 做定位**（观察可见元素、边界，并据此主动找出最高优先级的翻页按钮 `find_next_button`，见下方决策优先级），**实际操作统一走 Playwright 输入层执行**（ps：实际上在测euivs，由于iframe导致计算像素一直不对，点击永远点不到正确的位置，目前主要还是依赖 JS 调用click()发生点击事件）。页面自己的处理程序负责生成进度请求，脚本不构造或重放请求侦听到的网络请求。

***

## 一、技术栈

| 层         | 技术                                        | 用途                      |
| --------- | ----------------------------------------- | ----------------------- |
| 浏览器自动化    | Playwright（复用系统 Edge）                     | 导航、截图、点击、iframe 切换、网络监听 |
| 文字识别      | PaddleOCR 2.7.3 + PaddlePaddle 2.6.2（GPU） | 识别页面文字 + 坐标 + 置信度       |
| 视觉大模型（可选） | Ollama + qwen3-vl:4b                      | 题目作答、语义兜底（判断"推进按钮"）     |
| 图像处理      | Pillow                                    | 截图缩放、降采样相似度比较           |
| 日志/台账     | JSONL + 静态 HTML                           | 操作审计 + 困难样本可视化          |

***

## 二、架构

### 模块职责

| 文件                                                        | 职责                                                        |
| --------------------------------------------------------- | --------------------------------------------------------- |
| [main.py](main.py)                                        | 主入口：主循环、多候选试错升级、need\_human、视频处理、VLM 健康检查、暂停控制       |
| [alert.py](alert.py)                                      | 人工介入提醒：声音/弹窗、启动自检、"不再弹窗"持久化（HUMAN\_ALERT\_\* 配置）      |
| [flow\_state.py](flow_state.py)                           | 显式工作流状态：观察、决策、操作、验证、VLM、视频、人工与完成                        |
| [config.py](config.py)                                    | 全局配置：按钮关键词、阈值、视口；平台域名/API 特征从本地 `config_platform.py` 桥接读取 |
| [config\_platform.example.py](config_platform.example.py) | 平台配置模板（占位符）；真实平台信息只写本地 `config_platform.py`，不进仓库          |
| [setup\_local.py](setup_local.py)                         | 交互式生成本地平台配置 `config_platform.py`（只留本地、不上云）                |
| [browser\_controller.py](browser_controller.py)           | 浏览器控制：截图、iframe 点击、DOM 兜底、视频检测、API 监听、进度验证、暂停控制      |
| [ocr\_engine.py](ocr_engine.py)                           | PaddleOCR 封装：识别、关键词过滤（从下到上/前缀放宽）、文字反查坐标             |
| [decision\_engine.py](decision_engine.py)                 | 决策引擎：按钮候选池合并 → 结束/题目检测 → VLM 双提示词 → 返回保底               |
| [vlm\_client.py](vlm_client.py)                           | Ollama 客户端：健康检查、请求、JSON 解析                                |
| [safety\_sandbox.py](safety_sandbox.py)                   | 安全沙箱：URL 白名单、坐标边界、频率、次数                              |
| [action\_logger.py](action_logger.py)                     | JSONL 操作日志                                                |
| [report.py](report.py)                                    | 日志 → `logs/report.html` 可视化台账                             |

### 数据流

```
navigate
  → screenshot → OCR 识别（产出文字/坐标，供候选队列与反查）
  → 决策生成候选队列（按来源区分）：
      ├─ dom ：活动页可见可操作的 btn-next（find_next_button，优先级最高）
      ├─ ocr ：关键词候选池 start/next/submit/guide_click（类别优先、同类从下到上）
      └─ vlm ：语义推理/题目作答，一次返回多个候选目标（targets 队列，减少 VLM 调用）
      ├─ 无候选 → DOM 兜底（可见文字 + 活动页 btn-next class）
      └─ 仍无候选 → 语义兜底（VLM 判断推进按钮；列表页直接 need_human）
  → 安全校验（URL 白名单 / 坐标 / 频率 / 次数）
  → click（每轮只操作一个候选；候选失败后换下一个，不重复调用 VLM）
      ├─ 进度请求已发出且收到响应 → 生效（否则看 URL/截图变化）
      └─ 无效 → 试下一候选 → VLM 语义推理 → 人工
```

**决策优先级**（[main.py](main.py) 主循环，DOM 最优先；其后才是 [decision\_engine.py](decision_engine.py) 的 `decide()`）：

1. **DOM 翻页按钮（最高优先级）**：`find_next_button()` 命中「活动页内 + 可见 + 未遮挡 + 未禁用」的 `btn-next` → 直接点击，**跳过后面所有 OCR/VLM 决策**（class 恒定比 OCR 文字更可靠）。
2. **结束页固定正文**：命中 `COURSE_FINISHED_TEXT`（"课程的学习已完成"）→ `terminate`
3. **按钮候选池（OCR）**：合并 `start/next/submit/guide_click`（类别优先、同类从下到上）
   - 最高类别是 `start/next` → 直接点击（跳过结束/题目检测）
   - 最高类别是 `submit/guide_click` → 先做结束/题目检测（题目页"提交"先走 VLM 读题）
4. **结束检测**：命中 `END_TEXTS`（"课程的学习已完成/学习完成/课程完成/结束"）→ `terminate`
5. **题目检测**：命中 `QUESTION_KEYWORDS` → VLM 读题作答
6. **返回保底**：无 VLM 时底部"返回"（视口下半部分）可点 → `click`
7. **兜底**：无结果 → `wait`（OCR 空 / wait / error 时再走 DOM 兜底，见下方数据流）

`find_next_button` 的具体校验逻辑与边界见 [PRD.md](PRD.md) 模块 1。

***

## 三、开发进度

### ✅ 已完成（可跑通）

1. 全链路：登录 → 选课 → 详情页翻页 → 答题 → 视频 → 完成，主循环可连续运行多节。
2. iframe 内点击（frame API 切进 iframe 内部定位并点击 + JS 合成点击兜底）。
3. 按钮候选池合并（start/next/submit/guide_click 类别优先、同类从下到上），多候选逐个试错。
4. API 监听：翻页 / 答题提交接口特征（本地 `config_platform.py` 配置），用于判断"推进是否生效"。
5. VLM 双提示词：题目作答 + 语义兜底（找推进按钮），共用公共头尾、各自规则；一次返回候选目标队列（`targets`），减少 VLM 调用。
6. 显式状态机：观察 → 决策 → 单次操作 → 验证；失败先试下一候选，再走 VLM，最后人工。
7. 视频页处理：`detect_video` 过滤隐藏/占位/视口外/空壳视频；`try_play_video` 候选试错；`wait_for_video_end` 轮询等播完。
8. 课程结束判定：结束页固定正文（`COURSE_FINISHED_TEXT`）+ 完成页 URL 特征（`COURSE_FINISH_URL_MARK`），不靠裸"已完成"。
9. VLM 健康检查 + `--no-vlm` / `ENABLE_VLM=False` 跳过机制。
10. 无 VLM 保底：底部"返回"按钮保底（`ENABLE_BACK_FALLBACK`）+ guide_click 前缀放宽（`GUIDE_CLICK_PREFIX`）。
11. 列表页识别：非详情页直接 need\_human，避免 VLM 在课程列表上幻觉。
12. 可视化台账：`report.py` 生成 `report.html`，含困难样本（附 VLM 返回内容）。
13. 本地回归测试：`test_flow.py` + `test_page.html` + `test_interaction.py`（不连真实平台）。

### 🚧 已知局限（待打磨）

1. **知识卡片类交互页**：需逐个点卡片解锁下一页，VLM 语义兜底一次只给一个目标，需多轮循环，准确度待验证。
2. **`images_changed` 阈值**（当前 8.0）：截图相似度判断的灰度差阈值需按真实页面适配；卡片翻转等"内容有变但灰度差小"的场景可能误判 no_change。
3. **OCR 按钮换行拆词**：如"怎么做到的"被拆成两行，无法拼成完整按钮名（靠 next-btn class 缓解）。
4. **平台深度耦合**：URL 特征、按钮文案、iframe、翻页/答题 API 名称均为单一平台定制，平台改版需适配。

### ⬜ 未实现 / 后续方向

1. 自动从列表页挑选未完成课程继续（当前列表页停住等用户选课）。
2. 跨行文本合并，缓解 OCR 拆词问题。
3. 用相似度比较（而非 hash 精确比对）做更稳的重复检测。
4. 接入 DeepSeek 视觉推理 API，按需处理复杂样本以节省 token（规划中）。

***

## 四、环境要求

- **OS**：Windows 10/11（依赖 msedge；macOS/Linux 需自行调整）
- **Python**：3.10+（本项目 `venv/` 为 3.11）
- **浏览器**：Microsoft Edge（`playwright install msedge` 复用系统 Edge）
- **GPU（可选但推荐）**：NVIDIA + CUDA 11.8（目标环境 RTX 3060 Laptop 6GB）；无 GPU 自动降级 CPU
- **Ollama（可选）**：仅启用 VLM 时需 `http://localhost:11434`

***

## 五、快速开始（开发环境）

```powershell
# 1. 克隆并进入项目（任选一个源）
git clone https://gitee.com/heshuyucode/browser_controller.git
#   备用镜像（GitHub 私人仓库，需有访问权限）：
#   git clone https://github.com/WhiteVolcanoRestaurant/browser_controller.git
cd browser_controller

# 2. 创建并激活虚拟环境
python -m venv venv
venv\Scripts\activate

# 3. 安装依赖
pip install -r requirements.txt

# 4. 安装 Edge 浏览器驱动
playwright install msedge

# 5.（可选）安装 Ollama 并拉取 VLM 模型
#   https://ollama.com 下载安装后：
ollama pull qwen3-vl:4b
ollama serve

# 6. 生成本地平台配置（只留在本地、不上云）
#    真实平台域名与具体 API 特征写进 config_platform.py，
#    该文件已被 .gitignore 排除，不会提交到公开仓库。
python setup_local.py
#    （或手动复制模板：copy config_platform.example.py config_platform.py 后填写）

# 7. 运行（不传 URL 时默认打开 config_platform.py 中的主页）
python main.py
python main.py "https://<你的课程平台主页>/课程地址"
# 跳过 VLM（无 Ollama / 显存不足时）
python main.py "https://<你的课程平台主页>/课程地址" --no-vlm

# 8. 本地回归测试（不连真实平台，自动起服务器跑通 test_page.html 全流程）
python test_flow.py
#    --no-vlm 跳过 VLM（多选题转人工）；--port 8000 指定端口
python test_flow.py --no-vlm
```

> **中文用户名注意**：Windows 用户名含中文（如 `C:\Users\打工`）会导致 PaddleOCR 底层 C++ 引擎加载模型失败。`main.py` / `ocr_engine.py` 已通过重定向 `USERPROFILE`/`HOME` 到项目根目录规避，**不要删除这两段前置代码**。

***

## 六、常用功能与辅助工具

### 核心运行

| 命令                            | 用途                |
| ----------------------------- | ----------------- |
| `python main.py URL`          | 主流程自动学习（默认启用 VLM） |
| `python main.py URL --no-vlm` | 跳过 VLM，思考页直接转人工   |
| `python test_flow.py`         | 本地测试页全流程测试（自动起服务器，无需手动 `http.server`） |

### 调试工具

| 文件                                           | 用途                                                               |
| -------------------------------------------- | ---------------------------------------------------------------- |
| [report.py](report.py)                       | 解析 `logs/action_log.jsonl` → `logs/report.html` 可视化台账（统计 + 困难样本） |
| [debug\_ocr.py](debug_ocr.py)                | 单独对某张截图跑 OCR（多尺度 + 亮度检测），排查"识别不到"                                |
| [debug\_api\_listen.py](debug_api_listen.py) | 监听翻页/答题 API 请求，验证推进信号                                            |
| [testVLM.py](testVLM.py)                     | 单独测试 Ollama VLM 连通性与返回格式（复用主流程做题链路）                       |
| [test\_flow.py](test_flow.py)                 | 本地测试页全流程测试：自动起服务器 → 跑通 test\_page.html → 关服务器 |
| [test\_page.html](test_page.html)            | 本地测试页（11 段分级流程，配合 `python test_flow.py` 使用）                        |

### 人工介入提醒（可选）

默认陷入"需要人工介入"时只在终端打印提示（`[需人工介入]`）。若希望脚本主动用声音 / 弹窗引起注意，可在 [config.py](config.py) 开启：

| 配置 | 默认 | 说明 |
| ---- | ---- | ---- |
| `HUMAN_ALERT_ENABLE` | `False` | 总开关，设为 `True` 后声音/弹窗提醒才生效 |
| `HUMAN_ALERT_SOUND` | `True` | 播放提示音（Windows 用系统通知音效，柔和、异步不阻塞） |
| `HUMAN_ALERT_POPUP` | `True` | 弹小提示窗提醒转人工介入 |
| `HUMAN_ALERT_STARTUP_CHECK` | `True` | 启动时自检一次声音/弹窗，可当场确认并调整音量 |

- **弹窗内置"不再弹窗"选项**：在提示窗里勾选后，脚本会把 `config.py` 的 `HUMAN_ALERT_POPUP` 写回为 `False`（持久化），此后再遇人工介入不再弹窗；恢复只需把该值改回 `True`。弹窗界面也会注明这一点，方便你到 config 里手动管理。
- **音量调整**：提示音音量跟随系统"通知"音效，可在 `设置 → 系统 → 声音 → 音量混合器` 或"通知音量"里调整。

### 日志与截图

- 操作日志：`logs/action_log.jsonl`（每步 JSON 行）
- 页面截图：`logs/debug_page_{ts}.png`（含 OCR 时刻）
- VLM 输入：`logs/vlm_input_{ts}.png`

> ⚠️ **截图占用磁盘空间较大**：为方便 debug，脚本每轮主循环都会把当前页面截图保存到 `logs/` 目录（`debug_page_*.png`），VLM 调用时还会额外保存 `vlm_input_*.png`。跑一次完整课程会产生大量 PNG，可能占几百 MB 甚至上 GB 空间。`logs/` 已加入 `.gitignore` 不会提交，但**建议定期清理**（如 `Remove-Item logs\*.png`），或在长时间无人值守运行时留意磁盘占用。

***

## 七、适配新平台 / 扩展

脚本深度耦合单一平台，改平台时需调整以下配置：

| 配置                           | 位置                                                   | 说明                                         |
| ---------------------------- | ---------------------------------------------------- | ------------------------------------------ |
| 域名 / 主页 URL / 详情页特征 / 完成页特征 / API 特征 | 本地 [config\_platform.py](config_platform.example.py) | 真实平台信息，**不进仓库**；改平台只需改这里                   |
| `TARGET_BUTTONS`             | [config.py](config.py)                               | 按钮关键词（start/next/submit/guide_click），翻页词会变（下一页/继续/下一步） |
| `GUIDE_CLICK_PREFIX`         | [config.py](config.py)                               | guide_click 前缀放宽（OCR 文字以"点击"开头即视为引导按钮） |
| `QUESTION_KEYWORDS`          | [config.py](config.py)                               | 题目触发词（单选/多选/判断/哪些…），勿放"选择"等宽泛词             |
| `END_TEXTS`                  | [config.py](config.py)                               | 课程完成判定正文（不用裸"已完成"）                          |
| `NEXT_BUTTON_CLASS_HINTS`    | [config.py](config.py)                               | 翻页按钮 class 特征（比 OCR 文字更稳）                  |
| `COURSE_DETAIL_URL_MARK`     | [config\_platform.py](config_platform.example.py)    | 详情页 URL 特征（用于"往回跳即结束"与列表页判断）               |
| `COURSE_FINISH_URL_MARK`     | [config\_platform.py](config_platform.example.py)    | 完成/结束页 URL 特征（视频播完/课程学完自动跳转）               |
| `COURSE_FINISHED_TEXT`       | [config\_platform.py](config_platform.example.py)    | 结束页固定正文（严格匹配判定结束）                        |
| `ALLOWED_DOMAINS`            | [config\_platform.py](config_platform.example.py)    | 域名白名单                                      |

详细踩坑与技术演进见 [DEVELOPMENT\_LOG.md](DEVELOPMENT_LOG.md)。

***

## 八、目录结构

```
browser_controller/
├── main.py                # 主入口：主循环、候选试错升级、need_human、视频处理、暂停控制
├── alert.py               # 人工介入提醒：声音/弹窗、启动自检、"不再弹窗"持久化
├── flow_state.py          # 工作流状态机（观察/决策/操作/验证/VLM/视频/人工/完成）
├── config.py              # 全局配置常量（平台信息从 config_platform 桥接读取）
├── config_platform.example.py  # 平台配置模板（占位符，可提交）
├── config_platform.py          # 本地平台配置（真实域名/API，勿提交）
├── setup_local.py              # 本地平台配置引导脚本（交互式，不上云）
├── browser_controller.py  # 浏览器控制：截图/iframe点击/DOM兜底/视频/API监听/进度验证
├── ocr_engine.py          # PaddleOCR 封装
├── decision_engine.py     # 决策引擎（候选池 + VLM 双提示词 + 返回保底）
├── vlm_client.py          # Ollama VLM 客户端
├── safety_sandbox.py      # 安全沙箱
├── action_logger.py       # JSONL 日志
├── report.py              # 可视化台账生成
├── debug_ocr.py / debug_api_listen.py / testVLM.py / open_url.py  # 调试工具
├── test_page.html         # 本地测试页（11 段分级流程）
├── test_flow.py           # 本地测试页全流程测试（自动起服务器）
├── test_interaction.py    # 浏览器输入层/状态机回归测试（unittest，不启动 OCR/VLM）
├── requirements.txt       # Python 依赖
├── PRD.md                 # 产品需求
├── DEVELOPMENT_LOG.md     # 开发踩坑记录
└── README.md
```

***

## 九、协作约定

1. **不要提交敏感/运行时产物**：`edge_profile/`（登录态）、`appdata/`、`.paddleocr/`、`logs/`、`api*.txt`（含 token/cookie/sign）均已在 [.gitignore](.gitignore) 中排除。
2. **不要删除中文用户名规避代码**：`main.py` / `ocr_engine.py` 顶部的 `USERPROFILE`/`HOME` 重定向是必要的。
3. **改平台适配优先改** **`config.py`**，其次才动 `decision_engine.py` / `browser_controller.py` 的具体逻辑。
4. **关键调试日志在终端**：`[CLICK]` / `[DOM]` / `[VLM]` 定位日志是 `print` 到 stdout 的，不写入 `action_log.jsonl`。

***

## 十、相关文档

- [PRD.md](PRD.md) —— 产品需求、模块定义、核心工作流、安全约束、验收标准
- [DEVELOPMENT\_LOG.md](DEVELOPMENT_LOG.md) —— 踩坑记录、点击定位演进史、配置说明

***

## 十一、赞助与支持（可选）

本项目为个人学习与研究项目，开发与调试（本地大模型、OCR、浏览器自动化测试）有一定成本。
如果你觉得本项目有帮助，欢迎自愿赞助鼓励，金额随意、**不强求噢！**：

ps：deepseek涨完价根本不敢在白天用QAQ，周一中午用v4pro一轮对话3分钟就烧了14块钱，现在只敢在深夜谷期盯着api账单瑟瑟发抖，天才程序员陨落（哭。。。）！

- **爱发电**：[点击前往](https://afdian.com/)（`TODO：正在申请爱发电创作者ing....`）
- **微信**（微信赞助）：扫描下方二维码。

<img src="wechat_pay_qr.png" alt="微信赞助码" width="220" />

