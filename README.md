# arXiv Research Agent v2.0

每天自动抓取、筛选、评分、摘要最新 arXiv 论文，推送到 Telegram。

## 架构

```
arXiv (最新论文)
    ↓
Semantic Scholar (引用量 + 作者机构 + 会议)
    ↓
Crossref (正式发表状态验证)
    ↓
评分排序 (可插拔多维度评分)
    ↓
三段式摘要 (抽取→结构化→压缩重写)
    ↓
Telegram 推送
```

## 项目结构

```
├── config/              # 配置（settings, 数据源参数）
├── agents/              # 数据源 Agent（arXiv, S2, Crossref, 聚合器）
├── scoring/             # 可插拔评分系统（引用、作者、会议、新鲜度、关键词）
├── summarizer/          # 三段式摘要（规则抽取 → LLM 提取 → LLM 压缩）
├── notifier/            # 通知推送（Telegram）
├── scheduler/           # 定时任务调度
├── utils/               # 通用工具（LLM客户端, 数据库, 重试, 限速, 日志）
├── tests/               # 单元测试 + 端到端测试
├── data/                # 运行时数据（原始/处理后/缓存）
└── main.py              # 入口
```

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 配置环境变量

创建 `.env` 文件：

```env
OPENAI_API_KEY=sk-...
OPENAI_MODEL=gpt-4o-mini
TELEGRAM_BOT_TOKEN=123456:ABC...
TELEGRAM_CHAT_ID=-100...

# 可选
S2_API_KEY=              # Semantic Scholar API Key（有 key 速率更高）
CROSSREF_MAILTO=you@xx   # Crossref 邮箱（改善速率限制）
```

### 3. 运行

```bash
# 单次运行
python main.py --once

# 定时模式（每天 09:00）
python main.py

# 自定义参数
python main.py --once --days 3 --top 10 --categories cs.AI cs.LG
```

## 评分系统

每篇论文 0-100 分，5 个维度可插拔：

| 维度 | 权重 | 数据源 |
|------|------|--------|
| 引用量 | 30 | Semantic Scholar |
| 作者机构 | 20 | Semantic Scholar |
| 顶会/发表 | 20 | S2 + Crossref |
| 新鲜度 | 15 | arXiv 日期 |
| 关键词 | 15 | 标题+摘要 |

## 三段式摘要

```
abstract → 关键句抽取(规则层, 0 token) → 结构化提取(LLM) → 语义压缩(LLM)
```

输出示例：
```
• 解决含噪环境下音频特征表达能力不足的问题
• 提出对比式多尺度音频嵌入模型
• 语音识别准确率显著提升
```

## 测试

```bash
python -m pytest tests/ -v
```

## GitHub Actions

推送代码并在 Secrets 配置 API keys 后，每天 UTC 00:00（北京 08:00）自动运行。

## 扩展

- **新数据源**: 在 `agents/` 新增 agent 文件，实现 `enrich_papers()` 方法
- **新评分维度**: 在 `scoring/` 新增 scorer，继承 `BaseScorer`
- **新通知方式**: 在 `notifier/` 新增通知器
