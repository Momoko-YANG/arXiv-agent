# arXiv 智能论文 Agent

自动抓取 arXiv 每日论文，通过 **OpenAI GPT** 智能筛选 & 中文摘要，推送到 **Telegram**。

## 项目结构

```
arXiv-Agent/
├── .env                           # 环境变量（Token / API Key，不提交到 git）
├── .gitignore
├── config.yaml.template           # 配置模板
├── requirements.txt
├── README.md
│
├── arxiv_agent.py                 # 基础层：arXiv API 抓取 & XML 解析
├── arxiv_advanced.py              # 数据库层：SQLite 存储 / 去重 / 搜索
├── arxiv_intelligent_agent.py     # 智能层：OpenAI GPT 筛选 / 中文摘要 / 问答
├── arxiv_intelligent_scheduler.py # ★ 主入口：定时调度 + Telegram 推送
├── arxiv_scheduler.py             # 基础版定时调度（无 GPT / 无 Telegram）
└── test_agent.py                  # 测试脚本
```

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 配置 `.env`

在项目根目录创建（或编辑已有的）`.env` 文件：

```
TELEGRAM_BOT_TOKEN=你的BotToken
TELEGRAM_CHAT_ID=你的ChatID
OPENAI_API_KEY=你的OpenAI-API-Key
OPENAI_MODEL=gpt-4o-mini
```

**获取方式：**

| 变量 | 获取方法 |
|------|---------|
| `TELEGRAM_BOT_TOKEN` | Telegram 找 @BotFather → `/newbot` |
| `TELEGRAM_CHAT_ID` | 和 bot 私聊后访问 `https://api.telegram.org/bot<token>/getUpdates`，查看 `chat.id` |
| `OPENAI_API_KEY` | https://platform.openai.com/api-keys |
| `OPENAI_MODEL` | 可选，默认 `gpt-4o-mini`（便宜快速）；也可改为 `gpt-4o` 等 |

### 3. 运行

**单次运行（测试 / 手动触发）：**

```bash
python arxiv_intelligent_scheduler.py --once
```

**定时运行（每天 09:00 自动执行）：**

```bash
python arxiv_intelligent_scheduler.py
```

## 推送效果

Telegram 收到的消息：

```
🤖 arXiv 智能日报 2026-02-12
相关论文：8 篇

1. Chain-of-Thought Prompting Elicits Reasoning...
   https://arxiv.org/abs/2402.xxxxx
   📝 本文提出了思维链提示方法...

2. ...
```

同时还会收到一份 `intelligent_report_YYYYMMDD.md` 完整报告文件。

## 模型选择

在 `.env` 中通过 `OPENAI_MODEL` 指定模型：

| 模型 | 特点 | 推荐场景 |
|------|------|---------|
| `gpt-4o-mini` | 便宜、快速、效果不错 | **日常使用（默认）** |
| `gpt-4o` | 更强、稍贵 | 需要更精确的筛选 |
| `gpt-4-turbo` | 128k 上下文 | 一次处理大量论文 |

## 自定义研究方向

编辑 `arxiv_intelligent_scheduler.py` 中的 `research_interests`：

```python
research_interests = """
我关注以下方向：
1. 大语言模型的推理能力
2. 多模态模型
3. 你的其他兴趣...
"""
```

**越详细，GPT 筛选效果越好。**

## 部署（服务器）

### Linux / Mac (cron)

```bash
crontab -e

# 每天早上 9 点运行
0 9 * * * cd /path/to/arXiv-Agent && /usr/bin/python3 arxiv_intelligent_scheduler.py --once >> logs/agent.log 2>&1
```

### 后台持续运行

```bash
nohup python arxiv_intelligent_scheduler.py > logs/agent.log 2>&1 &
```

## arXiv 分类代码

| 代码 | 说明 |
|------|------|
| `cs.AI` | Artificial Intelligence |
| `cs.LG` | Machine Learning |
| `cs.CV` | Computer Vision |
| `cs.CL` | NLP |
| `cs.NE` | Neural and Evolutionary Computing |
| `stat.ML` | Machine Learning (Statistics) |

完整列表：https://arxiv.org/category_taxonomy

## 注意事项

1. **Token 安全**：`.env` 已在 `.gitignore` 中，永远不要把 Token 提交到 git
2. **OpenAI 费用**：`gpt-4o-mini` 非常便宜，每天跑一次约几美分
3. **Telegram 限流**：代码已内置重试逻辑，正常使用不会触发
4. **arXiv 速率**：API 有速率限制，请求间隔已设为 3 秒

## License

MIT
# arXiv-agent
