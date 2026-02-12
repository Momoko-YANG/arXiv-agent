# arXiv 智能论文 Agent

每天自动抓取 arXiv 论文 → OpenAI GPT 筛选 & 中文摘要 → 推送到 Telegram。

通过 **GitHub Actions** 免费自动运行，无需服务器。

## 快速开始

```bash
pip install -r requirements.txt
```

在 `.env` 中填入配置：

```
TELEGRAM_BOT_TOKEN=你的BotToken          # @BotFather → /newbot
TELEGRAM_CHAT_ID=你的ChatID              # bot私聊后访问 api.telegram.org/bot<token>/getUpdates
OPENAI_API_KEY=你的Key                   # platform.openai.com/api-keys
OPENAI_MODEL=gpt-4o-mini                 # 可选，默认 gpt-4o-mini
```

运行测试：

```bash
python3 arxiv_intelligent_scheduler.py --once
```

## 部署（GitHub Actions）

1. 推送代码到 GitHub（`.env` 不会被推送）
2. 仓库 **Settings → Secrets → Actions** 添加上述 4 个变量
3. 完成 — 每天 UTC 00:00（北京 08:00 / 东京 09:00）自动推送

手动触发：**Actions → Daily arXiv Agent → Run workflow**

## 自定义

**研究方向** — 编辑 `arxiv_intelligent_scheduler.py` 中的 `research_interests`，越详细筛选越准。

**推送时间** — 编辑 `.github/workflows/daily_arxiv.yml` 中的 cron：

```yaml
cron: '0 0 * * *'    # UTC 00:00 = 北京 08:00
```

**模型** — `.env` 中 `OPENAI_MODEL` 可选 `gpt-4o-mini`（默认/便宜）或 `gpt-4o`（更强）。

## 项目结构

```
arxiv_agent.py                 # arXiv API 抓取
arxiv_advanced.py              # SQLite 存储 / 去重
arxiv_intelligent_agent.py     # GPT 筛选 / 中文摘要 / 问答
arxiv_intelligent_scheduler.py # ★ 主入口：调度 + Telegram 推送
.github/workflows/daily_arxiv.yml  # GitHub Actions 定时任务
```

## License

MIT
