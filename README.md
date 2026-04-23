# arXiv Research Agent

> 每天自动抓取最新 arXiv 论文，按研究兴趣筛选、补充引用与发表信息、评分排序、生成摘要，并推送到 Telegram。当前版本支持精确零漂移调度、ReAct 决策路径、Telegram 反馈闭环与本地缓存。

---

## 功能概览

- 自动抓取最近论文，支持按分类和时间窗口运行
- 两种筛选模式：默认 ReAct Agent / 可切换固定流水线
- Semantic Scholar 补充引用数、作者机构、会议信息
- Crossref 校验正式发表状态与 DOI
- 五维评分：引用、机构、Venue、新鲜度、关键词
- 两种摘要模式：`oneshot`（快、省）/ `threestage`（细）
- Telegram 推送支持反馈按钮：`⭐ 感兴趣` / `👎 不相关` / `📖 已读`
- 用户反馈写入数据库，用于后续自适应评分
- SQLite 缓存 S2 / Crossref 响应，减少重复请求
- 定时模式使用墙钟精确调度，避免长期运行后触发时间漂移

---

## 工作流程

### 默认流水线

```text
arXiv API            拉取最近论文
     |
     v
关键词 / GPT 筛选     根据研究兴趣做初筛
     |
     v
Semantic Scholar     补充引用量 / 机构 / 会议 / 作者信息
     |
     v
多维评分              Citation · Author · Venue · Freshness · Keyword
     |
     v
Crossref             仅对选中的论文校验正式发表状态
     |
     v
摘要生成              oneshot 或 threestage
     |
     v
Telegram 推送         摘要 + 元数据 + 反馈按钮
```

### ReAct 模式

默认启用 ReAct 时，LLM 不只负责“选哪些论文”，还会继续决定：

- 最终推送哪些论文
- 哪些论文值得调用 Crossref
- 哪些论文值得做深入分析

最终结果会额外生成 `ReAct 深入分析` 段落，写入日报报告。

---

## 项目结构

```text
.
├── main.py                      # CLI 入口
├── README.md
├── requirements.txt
│
├── agents/
│   ├── arxiv_agent.py           # arXiv 抓取
│   ├── semantic_agent.py        # Semantic Scholar 补充
│   ├── crossref_agent.py        # Crossref 发表验证
│   ├── aggregator.py            # 主流水线 + ReAct 后续动作规划
│   ├── react_agent.py           # 通用 ReAct tool-calling 循环
│   └── tools.py                 # ToolRegistry / Tool 定义
│
├── config/
│   ├── settings.py              # Settings 数据类 + .env 加载
│   └── sources.yaml             # 数据源配置
│
├── llm_client/
│   ├── client.py                # LLM 统一入口
│   ├── transport.py             # OpenAI-compatible HTTP transport
│   ├── retry.py                 # 重试 + 熔断
│   └── errors.py                # 错误类型
│
├── notifier/
│   └── telegram_bot.py          # Telegram 推送 + callback 监听 + 幂等反馈
│
├── scheduler/
│   └── daily_job.py             # 单次运行 / 零漂移定时调度
│
├── scoring/
│   ├── base_score.py            # BaseScorer / ScoringPipeline / Venue / Keyword
│   ├── citation_score.py        # 引用评分
│   ├── author_score.py          # 机构评分
│   └── freshness_score.py       # 新鲜度评分
│
├── summarizer/
│   ├── llm_summarizer.py        # oneshot / threestage 摘要器
│   └── prompt_templates.py      # Prompt 模板
│
├── utils/
│   ├── database.py              # SQLite 数据库 + 反馈 + 决策日志
│   ├── cache.py                 # SQLite TTL 缓存
│   ├── rate_limit.py            # 线程安全速率限制器
│   ├── retry.py                 # 通用重试装饰器
│   ├── logger.py                # 日志
│   └── text_clean.py            # 文本清洗
│
├── data/
│   ├── raw/
│   ├── processed/
│   └── cache/
│
├── tests/                       # 当前测试总数 32
└── .github/workflows/
    └── daily_arxiv.yml          # GitHub Actions 定时运行
```

---

## 快速开始

### 1. 安装

```bash
git clone <repo-url>
cd arXiv-agent
pip install -r requirements.txt
```

### 2. 配置

在项目根目录创建 `.env`：

```env
# OpenAI（可选；不填则回退到关键词筛选 + 规则摘要）
OPENAI_API_KEY=sk-...
OPENAI_MODEL=gpt-4o-mini
OPENAI_BASE_URL=

# Telegram（可选；不填则只生成本地报告，不推送）
TELEGRAM_BOT_TOKEN=123456:ABC-DEF...
TELEGRAM_CHAT_ID=-100...

# 外部数据源（可选）
S2_API_KEY=
CROSSREF_MAILTO=you@example.com
```

说明：

- `OPENAI_API_KEY` 为空时，项目仍可运行，但会回退到关键词预筛和规则摘要
- ReAct 默认启用；传入 `--no-react` 可切回固定流水线
- ReAct 需要 OpenAI 才有意义；未配置时会自动回退
- `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` 为空时，Telegram 推送会被跳过

### 3. 运行

```bash
python main.py --once
python main.py
python main.py --once --days 3 --top 10
python main.py --categories cs.AI cs.CL eess.AS
python main.py --time 21:00
python main.py --no-react
python main.py --summarizer threestage
python main.py --once --no-react --summarizer oneshot --top 8
```

### 参数说明

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `--once` | 单次运行，不进入定时循环 | 否 |
| `--days N` | 抓取最近 N 天论文 | `2` |
| `--top N` | 最终推送前 N 篇 | `5` |
| `--time HH:MM` | 每日定时执行时间 | `09:00` |
| `--categories X Y` | arXiv 分类列表 | `cs.AI cs.LG cs.CV cs.CL` |
| `--react` | 显式启用 ReAct Agent 模式 | 开启 |
| `--no-react` | 关闭 ReAct Agent 模式，切回固定流水线 | 关闭 |
| `--summarizer MODE` | 摘要模式：`oneshot` / `threestage` | `oneshot` |

---

## 调度说明

本地定时模式不再依赖 `schedule + sleep(60)` 轮询，而是使用墙钟精确计算下一次触发时间。

这样做的直接收益：

- 长期运行后不会越来越晚
- 触发精度更稳定
- 执行时间较长时也不会累计漂移

默认本地调度时间是每天 `09:00`。

---

## 评分系统

每篇论文由 5 个评分器独立打分，最终归一化到 `0 ~ 100`：

| 评分器 | 默认权重 | 数据来源 | 逻辑 |
|--------|----------|----------|------|
| `CitationScorer` | 30 | Semantic Scholar | 引用数 + 有影响力引用 |
| `AuthorScorer` | 20 | Semantic Scholar | 命中知名机构 |
| `VenueScorer` | 20 | S2 + Crossref | 顶会 / 顶刊 + 正式发表 |
| `FreshnessScorer` | 15 | arXiv 日期 | 越新分越高 |
| `KeywordScorer` | 15 | 标题 + 摘要 | 命中研究关键词越多分越高 |

系统还会根据 Telegram 用户反馈做自适应微调：

- 喜欢高引用论文时提高 `CitationScorer`
- 喜欢正式发表论文时提高 `VenueScorer`
- 偏好更新论文时提高 `FreshnessScorer`

---

## 摘要模式

### `oneshot`

默认模式。单次 LLM 调用直接输出 3 条要点：

- 延迟更低
- token 开销更小
- 适合日常推送

### `threestage`

传统三段式：

```text
Stage 1  关键句抽取    规则层                    0 token
Stage 2  结构化提取    LLM 提取 P/M/R            低温度
Stage 3  语义压缩      LLM 重写为 3 条要点        中温度
```

适合对摘要质量要求更高的场景。

---

## ReAct 模式

默认情况下，系统会用工具调用循环而不是只做一次静态筛选；传入 `--no-react` 后会切回固定流水线。当前 ReAct 路径会参与：

- 候选论文选择
- 最终推送列表确定
- 是否调用 Crossref 的决策
- 哪些论文值得生成 `深入分析`

当前 ReAct 输出会被解析成三组 ID：

- `FINAL_IDS`
- `CROSSREF_IDS`
- `DEEP_DIVE_IDS`

如果 ReAct 输出无效或 LLM 不可用，会自动回退到普通 GPT / 关键词流水线。

---

## Telegram 推送与反馈闭环

Telegram 推送内容包括：

- 标题
- 评分
- 引用数
- 发表状态 / 会议期刊
- 摘要要点
- ReAct 深入分析（若有）

每篇论文下方会带 3 个反馈按钮：

- `⭐ 感兴趣`
- `👎 不相关`
- `📖 已读`

反馈处理特性：

- callback 监听后台运行
- 启动时自动跳过历史 update，避免重启后重复消费
- 使用 `source_id` 保证同一个 callback 只写入一次
- 反馈写入 SQLite，供后续自适应评分使用

---

## 缓存与性能

当前版本做了几类性能优化：

- `Semantic Scholar` 结果缓存到 `data/cache/cache.db`
- `Crossref` 查询结果缓存到 `data/cache/cache.db`
- Crossref 只查最终选中的子集
- 摘要在 `oneshot` 模式下支持并行执行
- 最近 7 天已入库论文会先去重，不重复处理

---

## 测试

当前仓库测试总数为 `32`，推荐直接用 `pytest`：

```bash
python -m pytest tests -q
python -m pytest tests/test_runtime_fixes.py -q
```

测试覆盖包括：

- 数据库 CRUD / 反馈幂等
- 评分与排序
- 关键句抽取
- ReAct 路径关键控制流
- Telegram listener offset / callback 行为
- 端到端流水线关键分支

---

## GitHub Actions

仓库内置工作流 `daily_arxiv.yml`：

- 定时：每天 `UTC 00:00` 运行
- 北京时间：每天 `08:00`
- 也支持手动触发 `workflow_dispatch`

工作流默认执行：

```bash
python main.py --once
```

可用 Secrets：

| Secret | 必填 | 说明 |
|--------|------|------|
| `OPENAI_API_KEY` | 否 | OpenAI API Key |
| `OPENAI_BASE_URL` | 否 | 兼容 OpenAI 的自定义网关 |
| `OPENAI_MODEL` | 否 | 模型名，默认 `gpt-4o-mini` |
| `TELEGRAM_BOT_TOKEN` | 否 | Telegram Bot Token |
| `TELEGRAM_CHAT_ID` | 否 | 目标聊天 ID |
| `S2_API_KEY` | 否 | Semantic Scholar API Key |
| `CROSSREF_MAILTO` | 否 | Crossref 联系邮箱 |

---

## 扩展指南

| 需求 | 做法 |
|------|------|
| 新增数据源（PubMed、GitHub Papers） | 在 `agents/` 下新增 client，并接入 `agents/aggregator.py` |
| 新增评分维度 | 在 `scoring/` 下新增 scorer，继承 `BaseScorer` |
| 新增摘要模式 | 修改 `summarizer/llm_summarizer.py` 和 `summarizer/prompt_templates.py` |
| 新增通知渠道 | 在 `notifier/` 下新增通知器 |
| 调整 ReAct 工具 | 修改 `agents/tools.py` 或 `agents/aggregator.py` |
| 调整调度策略 | 修改 `scheduler/daily_job.py` |
| 调整默认关注分类 / 关键词 | 修改 `config/settings.py` 或 `config/sources.yaml` |

---

## 技术栈

Python 3.10+ / OpenAI-compatible API / Semantic Scholar API / Crossref API / Telegram Bot API / SQLite / GitHub Actions
