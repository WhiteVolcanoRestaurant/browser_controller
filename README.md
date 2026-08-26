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

核心分工：**OCR 当眼睛**（识别文字、给坐标）、**DOM 当手**（elementFromPoint 反查真实元素、切 iframe 精确定位）、**VLM 当大脑**（读题做题、语义兜底决策）。

***

## 一、技术栈

| 层         | 技术                                        | 用途                      |
| --------- | ----------------------------------------- | ----------------------- |
| 浏览器自动化    | Playwright（复用系统 Edge）                     | 导航、截图、点击、iframe 切换、网络监听 |
| 文字识别      | PaddleOCR 2.7.3 + PaddlePaddle 2.6.2（GPU） | 识别页面文字 + 坐标 + 置信度       |
| 视觉大模型（可选） | Ollama + llava-phi3                       | 题目作答、语义兜底（判断"推进按钮"）     |
| 图像处理      | Pillow                                    | 截图缩放、降采样相似度比较           |
| 日志/台账     | JSONL + 静态 HTML                           | 操作审计 + 困难样本可视化          |

***

## 二、架构

### 模块职责

| 文件                                                        | 职责                                                        |
| --------------------------------------------------------- | --------------------------------------------------------- |
| [main.py](main.py)                                        | 主入口：主循环、分级降级恢复、need\_human、视频检测、VLM 健康检查                  |
| [config.py](config.py)                                    | 全局配置：按钮关键词、阈值、视口；平台域名/API 特征从本地 `config_platform.py` 桥接读取 |
| [config\_platform.example.py](config_platform.example.py) | 平台配置模板（占位符）；真实平台信息只写本地 `config_platform.py`，不进仓库          |
| [setup\_local.py](setup_local.py)                         | 交互式生成本地平台配置 `config_platform.py`（只留本地、不上云）                |
| [browser\_controller.py](browser_controller.py)           | 浏览器控制：截图、iframe 点击、DOM 兜底、视频检测、API 监听、reload              |
| [ocr\_engine.py](ocr_engine.py)                           | PaddleOCR 封装：识别、关键词过滤、文字反查坐标                              |
| [decision\_engine.py](decision_engine.py)                 | 决策引擎：关键词匹配 → 题目 VLM → 语义兜底；VLM 双提示词                       |
| [vlm\_client.py](vlm_client.py)                           | Ollama 客户端：健康检查、请求、JSON 解析                                |
| [safety\_sandbox.py](safety_sandbox.py)                   | 安全沙箱：URL 白名单、坐标边界、频率、次数、重复检测                              |
| [action\_logger.py](action_logger.py)                     | JSONL 操作日志                                                |
| [report.py](report.py)                                    | 日志 → `logs/report.html` 可视化台账                             |

### 数据流

```
navigate
  → screenshot
  → OCR 识别
  → decide 决策（结束 > start/next > 题目VLM > submit > wait）
      ├─ 失败 → DOM 兜底（可见文字 + next-btn class）
      └─ 仍失败 → 语义兜底（VLM 判断推进按钮；列表页直接 need_human）
  → 安全校验（URL 白名单 / 坐标 / 频率 / 次数）
  → click（多候选逐个 click_and_verify：API > URL > 截图变化）
      └─ 无效 → 分级降级（等待 → DOM 重定位 → VLM 语义兜底 → reload → 人工）
```

**决策优先级**（[decision\_engine.py](decision_engine.py#L91-L140)）：

1. **结束检测**：命中 `END_TEXTS`（已完成/学习完成…）→ `terminate`
2. **翻页按钮**：`start/next` 关键词（最明确信号，优先于题目检测，避免正文"选择"误判）
3. **题目检测**：命中 `QUESTION_KEYWORDS` → VLM 读题作答
4. **提交按钮**：`submit` 关键词
5. **兜底**：无结果 → `wait`

***

## 三、开发进度

### ✅ 已完成（可跑通）

1. 全链路：登录 → 选课 → 详情页翻页 → 答题 → 视频 → 完成，主循环可连续运行多节。
2. iframe 内点击（frame API 切进 iframe 内部定位并点击，这是此前多次失败的根因）。
3. API 监听：翻页 / 答题提交接口特征（本地 `config_platform.py` 配置），用于判断"推进是否生效"。
4. VLM 双提示词：题目作答 + 语义兜底（找推进按钮），共用公共头尾、各自规则。
5. 分级降级恢复（5 级）：等待 → DOM 重定位 → VLM 语义兜底 → reload（有上限防封号）→ 人工（监听 API 自动继续）。
6. VLM 健康检查 + `--no-vlm` / `ENABLE_VLM=False` 跳过机制。
7. 多候选试错：同一关键词命中多个位置时逐个点击验证。
8. 列表页识别：非详情页直接 need\_human，避免 VLM 在课程列表上幻觉。
9. 可视化台账：`report.py` 生成 `report.html`，含困难样本（附 VLM 返回内容）。

### 🚧 已知局限（待打磨）

1. **知识卡片类交互页**：需逐个点"请点击查看"卡片才能解锁下一页，VLM 语义兜底一次只给一个目标，需多轮循环，准确度待验证。
2. **llava-phi3 命中率**：小模型，题目作答与语义兜底的稳定命中率不稳定。
3. **`images_changed`** **阈值**（当前 8.0）：截图相似度判断的灰度差阈值需按真实页面适配。
4. **OCR 按钮换行拆词**：如"怎么做到的"被拆成两行，无法拼成完整按钮名（可靠 next-btn class 缓解）。
5. **平台深度耦合**：URL 特征、按钮文案、iframe、翻页/答题 API 名称均为单一平台定制，平台改版需适配。

### ⬜ 未实现 / 后续方向

1. 自动从列表页挑选未完成课程继续（当前列表页停住等用户选课）。
2. 跨行文本合并，缓解 OCR 拆词问题。
3. 用相似度比较（而非 hash 精确比对）做更稳的重复检测。

***

## 四、环境要求

- **OS**：Windows 10/11（依赖 msedge；macOS/Linux 需自行调整）
- **Python**：3.10+（本项目 `venv/` 为 3.11）
- **浏览器**：Microsoft Edge（`playwright install msedge` 复用系统 Edge）
- **GPU（可选但推荐）**：NVIDIA + CUDA 11.8（目标环境 RTX 3060 Laptop 6GB）；无 GPU 自动降级 CPU
- **Ollama（可选）**：仅启用 VLM 时需 `http://localhost:11434`
- 现在deepseek上新了视觉推理api，正在开发api接口中，计划是可以按需要处理复杂样本以节省token。

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
#   https://ollama.com 下载安装后：（不建议直接使用此模型，测试发现推理效果不好）
ollama pull llava-phi3
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
| [testVLM.py](testVLM.py)                     | 单独测试 Ollama VLM 连通性与返回格式                                         |
| [test\_flow.py](test_flow.py)                 | 本地测试页全流程测试：自动起服务器 → 跑通 test\_page.html → 关服务器 |
| [test\_page.html](test_page.html)            | 本地测试页（模拟 7 页流程，配合 `python test_flow.py` 使用）                           |

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
| 域名 / 主页 URL / 详情页特征 / API 特征 | 本地 [config\_platform.py](config_platform.example.py) | 真实平台信息，**不进仓库**；改平台只需改这里                   |
| `TARGET_BUTTONS`             | [config.py](config.py)                               | 按钮关键词（start/next/submit），翻页词会变（下一页/继续/下一步） |
| `QUESTION_KEYWORDS`          | [config.py](config.py)                               | 题目触发词（单选/多选/判断/哪些…），勿放"选择"等宽泛词             |
| `END_TEXTS`                  | [config.py](config.py)                               | 课程完成判定文本                                   |
| `NEXT_BUTTON_CLASS_HINTS`    | [config.py](config.py)                               | 翻页按钮 class 特征（比 OCR 文字更稳）                  |
| `COURSE_DETAIL_URL_MARK`     | [config\_platform.py](config_platform.example.py)    | 详情页 URL 特征（用于"往回跳即结束"与列表页判断）               |
| `ALLOWED_DOMAINS`            | [config\_platform.py](config_platform.example.py)    | 域名白名单                                      |

详细踩坑与技术演进见 [DEVELOPMENT\_LOG.md](DEVELOPMENT_LOG.md)。

***

## 八、目录结构

```
browser_controller/
├── main.py                # 主入口：主循环、分级降级、need_human、视频检测
├── config.py              # 全局配置常量（平台信息从 config_platform 桥接读取）
├── config_platform.example.py  # 平台配置模板（占位符，可提交）
├── config_platform.py          # 本地平台配置（真实域名/API，勿提交）
├── setup_local.py              # 本地平台配置引导脚本（交互式，不上云）
├── browser_controller.py  # 浏览器控制：截图/iframe点击/DOM兜底/视频/API监听
├── ocr_engine.py          # PaddleOCR 封装
├── decision_engine.py     # 决策引擎 + VLM 双提示词
├── vlm_client.py          # Ollama VLM 客户端
├── safety_sandbox.py      # 安全沙箱
├── action_logger.py       # JSONL 日志
├── report.py              # 可视化台账生成
├── debug_ocr.py / debug_api_listen.py / testVLM.py / open_url.py  # 调试工具
├── test_page.html         # 本地测试页
├── test_flow.py           # 本地测试页全流程测试（自动起服务器）
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

