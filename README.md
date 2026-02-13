# arXiv Research Agent

> 每天自动从 arXiv 抓取最新论文，交叉验证引用量与发表状态，评分筛选后生成三段式智能摘要，推送到 Telegram。

---

## 工作流程

```
arXiv API            拉取最新论文（按分类 + 日期）
     |
     v
GPT 筛选              根据研究兴趣智能匹配
     |
     v
Semantic Scholar     补充引用量 / 作者机构 / 顶会信息
     |
     v
Crossref             验证是否已正式发表 / DOI / 期刊
     |
     v
多维度评分            引用 · 机构 · 会议 · 新鲜度 · 关键词
     |
     v
三段式摘要            关键句抽取 → 结构化提取 → 语义压缩
     |
     v
Telegram 推送         评分 + 发表状态 + 摘要要点
```

---

## 项目结构

```
.
├── main.py                  # CLI 入口
│
├── config/
│   ├── settings.py          # Settings 数据类 + .env 加载
│   └── sources.yaml         # 数据源参数（分类、API 端点、间隔）
│
├── agents/
│   ├── arxiv_agent.py       # arXiv 抓取
│   ├── semantic_agent.py    # Semantic Scholar 补充
│   ├── crossref_agent.py    # Crossref 发表验证
│   └── aggregator.py        # 聚合编排（6 步流水线核心）
│
├── scoring/
│   ├── base_score.py        # BaseScorer 抽象基类 + ScoringPipeline
│   ├── citation_score.py    # 引用量 + 有影响力引用
│   ├── author_score.py      # 知名机构检测
│   └── freshness_score.py   # 发布时间衰减
│
├── summarizer/
│   ├── llm_summarizer.py    # 三段式摘要器
│   └── prompt_templates.py  # Prompt 模板集中管理
│
├── notifier/
│   └── telegram_bot.py      # Telegram 消息 + 文件推送
│
├── scheduler/
│   └── daily_job.py         # 定时 / 单次调度
│
├── utils/
│   ├── llm_client.py        # OpenAI ChatCompletion 客户端
│   ├── database.py          # SQLite 论文数据库
│   ├── retry.py             # 通用重试装饰器
│   ├── rate_limit.py        # 通用速率限制器
│   ├── logger.py            # 日志
│   └── text_clean.py        # 文本清洗
│
├── tests/                   # 24 个单元测试 + 端到端测试
├── data/                    # 运行时数据（raw / processed / cache）
└── .github/workflows/       # GitHub Actions 每日自动运行
```

---

## 快速开始

### 1. 安装

```bash
git clone <repo-url> && cd arXiv-agent
pip install -r requirements.txt
```

### 2. 配置

在项目根目录创建 `.env`：

```env
# 必填
OPENAI_API_KEY=sk-...
TELEGRAM_BOT_TOKEN=123456:ABC-DEF...
TELEGRAM_CHAT_ID=-100...

# 可选（不填也能跑，只是速率受限）
OPENAI_MODEL=gpt-4o-mini       # 默认模型
S2_API_KEY=                     # Semantic Scholar（有 key 速率更高）
CROSSREF_MAILTO=you@example.com # Crossref 邮箱（改善速率限制）
```

### 3. 运行

```bash
python main.py --once                              # 立即执行一次
python main.py                                     # 定时模式（默认每天 09:00）
python main.py --once --days 3 --top 10            # 抓 3 天，推 10 篇
python main.py --categories cs.AI cs.CL eess.AS    # 指定分类
python main.py --time 21:00                        # 改为每天 21:00
```

完整参数：

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `--once` | 单次运行，不进入定时循环 | 否 |
| `--days N` | 抓取最近 N 天的论文 | 1 |
| `--top N` | 推送前 N 篇高分论文 | 5 |
| `--time HH:MM` | 每日执行时间 | 09:00 |
| `--categories X Y` | arXiv 分类列表 | cs.AI cs.LG cs.CV cs.CL |

---

## 评分系统

每篇论文由 5 个可插拔评分器独立打分，加权合成 0\~100 分：

| 评分器 | 权重 | 数据来源 | 逻辑 |
|--------|------|----------|------|
| `CitationScorer` | 30 | Semantic Scholar | 引用数分档 + 有影响力引用加成 |
| `AuthorScorer` | 20 | Semantic Scholar | 命中 Google/OpenAI/Stanford 等 30+ 知名机构 |
| `VenueScorer` | 20 | S2 + Crossref | NeurIPS/ICML/ACL 等顶会 + 正式发表状态 |
| `FreshnessScorer` | 15 | arXiv 日期 | 1天内=满分，按周/月线性衰减 |
| `KeywordScorer` | 15 | 标题 + 摘要 | 命中配置的加分关键词越多分越高 |

所有评分器继承自 `BaseScorer`，通过 `ScoringPipeline` 组合。新增评分维度只需：

```python
# scoring/trend_score.py
class TrendScorer(BaseScorer):
    name = "trend"
    def score(self, paper: dict) -> float:
        ...  # 返回 0.0 ~ 1.0
```

然后注册到 `aggregator.py` 的 pipeline 中即可。

---

## 三段式摘要

传统做法（abstract → LLM → 复述）90% 是复读。本项目采用三段式流水线：

```
Stage 1  关键句抽取    规则层，60+ 学术关键词匹配 + 位置加权    0 token
Stage 2  结构化提取    LLM 提取 Problem / Method / Result       低温度 0.2
Stage 3  语义压缩      LLM 用自己的语言重写为 3 条要点           温度 0.6
```

输出示例：

```
• 解决含噪环境下音频特征表达能力不足的问题
• 提出对比式多尺度音频嵌入模型
• 语音识别准确率显著提升
```

Prompt 模板在 `summarizer/prompt_templates.py` 集中管理，方便迭代。

---

## Telegram 推送效果

每篇论文展示：评分 | 引用数 | 发表状态 + 三段式摘要要点。

```
🤖 arXiv 智能日报 2025-02-13
相关论文：5 篇

1. ReasonNet: Decompose-and-Verify for Complex Reasoning
   [85分] | 引用:42 | ✅NeurIPS
   https://arxiv.org/abs/2402.12345
   • 解决多步推理中的错误累积问题
   • 提出分解验证框架逐步检查中间结果
   • 复杂推理任务上超越 GPT-4 达 12%

2. Efficient LoRA for Edge Deployment
   [62分] | 引用:5 | 📝预印本
   https://arxiv.org/abs/2402.12346
   • 针对边缘设备资源受限的微调难题
   • 设计轻量级低秩适配方案
   • 模型体积缩小 8 倍性能仅降 2%
```

---

## 测试

```bash
python -m unittest discover tests -v    # 24 个测试，覆盖评分/数据库/抽取/流水线
```

---

## GitHub Actions

配置 Repository Secrets 后，自动每天 UTC 00:00（北京 08:00）运行：

| Secret | 必填 | 说明 |
|--------|------|------|
| `OPENAI_API_KEY` | 是 | OpenAI API Key |
| `TELEGRAM_BOT_TOKEN` | 是 | Telegram Bot Token |
| `TELEGRAM_CHAT_ID` | 是 | 目标聊天 ID |
| `OPENAI_MODEL` | 否 | 模型名（默认 gpt-4o-mini） |
| `S2_API_KEY` | 否 | Semantic Scholar API Key |
| `CROSSREF_MAILTO` | 否 | Crossref 联系邮箱 |

也可手动触发：Actions → Daily arXiv Agent → Run workflow。

---

## 扩展指南

| 需求 | 做法 |
|------|------|
| 新增数据源（PubMed、GitHub Papers） | `agents/` 下新增 agent，实现 `enrich_papers()` |
| 新增评分维度（趋势预测、热点聚类） | `scoring/` 下新增 scorer，继承 `BaseScorer` |
| 新增通知渠道（邮件、Slack、飞书） | `notifier/` 下新增通知器 |
| 修改 Prompt / 摘要风格 | 编辑 `summarizer/prompt_templates.py` |
| 修改评分权重 | 编辑 `agents/aggregator.py` 中的 `ScoringPipeline` 参数 |
| 修改关注分类 / 关键词 | 编辑 `config/sources.yaml` 或 CLI `--categories` |

---

## 技术栈

Python 3.10+ / OpenAI API / Semantic Scholar API / Crossref API / Telegram Bot API / SQLite / GitHub Actions
