#!/usr/bin/env python3
"""
Scheduled Intelligent arXiv Agent with Telegram Push
定时运行的智能 Agent，每天自动分析并推送到 Telegram
"""

import os
import sys
import time
import schedule
import requests
from datetime import datetime
from arxiv_intelligent_agent import IntelligentArxivAgent


# ---------------------------------------------------------------------------
# .env 加载（不依赖 python-dotenv，手动解析即可）
# ---------------------------------------------------------------------------
def load_dotenv(path: str = None):
    """从 .env 文件加载环境变量（已有的不覆盖）"""
    if path is None:
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env')
    if not os.path.exists(path):
        return
    with open(path, encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#') or '=' not in line:
                continue
            key, _, value = line.partition('=')
            key, value = key.strip(), value.strip()
            # 不覆盖已经存在的环境变量
            if key and key not in os.environ:
                os.environ[key] = value


# ---------------------------------------------------------------------------
# Telegram 推送
# ---------------------------------------------------------------------------
TELEGRAM_MAX_MSG_LEN = 4096


def _tg_request(method: str, token: str, **kwargs):
    """带重试的 Telegram Bot API 请求"""
    url = f"https://api.telegram.org/bot{token}/{method}"
    for attempt in range(3):
        try:
            resp = requests.post(url, timeout=60, **kwargs)
            if resp.status_code == 429:
                retry_after = resp.json().get('parameters', {}).get('retry_after', 5)
                print(f"⚠️  Telegram 限流，等待 {retry_after}s...")
                time.sleep(retry_after)
                continue
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as e:
            if attempt < 2:
                wait = 2 ** (attempt + 1)
                print(f"⚠️  Telegram 请求失败，{wait}s 后重试: {e}")
                time.sleep(wait)
            else:
                raise
    return None


def telegram_send_message(text: str, token: str, chat_id: str):
    """发送文本消息（自动分段）"""
    chunks = [text[i:i + TELEGRAM_MAX_MSG_LEN]
              for i in range(0, len(text), TELEGRAM_MAX_MSG_LEN)]
    for chunk in chunks:
        _tg_request("sendMessage", token, json={
            "chat_id": chat_id,
            "text": chunk,
            "disable_web_page_preview": True,
        })
        if len(chunks) > 1:
            time.sleep(0.5)


def telegram_send_document(file_path: str, caption: str, token: str, chat_id: str):
    """发送文件（报告 .md）"""
    with open(file_path, "rb") as f:
        _tg_request("sendDocument", token,
                     data={"chat_id": chat_id, "caption": caption[:1024]},
                     files={"document": f})


# ---------------------------------------------------------------------------
# 定时智能 Agent
# ---------------------------------------------------------------------------
class ScheduledIntelligentAgent:
    """定时智能 Agent，集成 Telegram 推送"""

    def __init__(self,
                 categories: list,
                 research_interests: str,
                 api_key: str = None,
                 telegram_token: str = None,
                 telegram_chat_id: str = None):
        self.agent = IntelligentArxivAgent(
            categories=categories,
            api_key=api_key,
        )
        self.research_interests = research_interests
        self.tg_token = telegram_token or os.getenv("TELEGRAM_BOT_TOKEN")
        self.tg_chat_id = telegram_chat_id or os.getenv("TELEGRAM_CHAT_ID")

    # ---------- 每日任务 ----------
    def daily_job(self):
        """每日执行的智能任务"""
        print(f"\n{'=' * 80}")
        print(f"🤖 智能日报任务开始 - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"{'=' * 80}\n")

        try:
            # 1. 抓取 + 智能分析
            result = self.agent.fetch_and_analyze(
                days=1,
                research_interests=self.research_interests,
                auto_summarize=True,
            )

            if not result['relevant']:
                print("❌ 今日无相关论文")
                self._tg_notify_no_papers()
                return

            # 2. 生成报告
            report = self.agent.generate_daily_report(
                summaries=result['summaries'],
                relevant_papers=result['relevant'],
            )

            # 3. 保存报告
            report_file = f"intelligent_report_{datetime.now().strftime('%Y%m%d')}.md"
            with open(report_file, 'w', encoding='utf-8') as f:
                f.write(report)
            print(f"✅ 报告已保存: {report_file}")

            # 4. 推送到 Telegram
            self._send_telegram_notification(result['relevant'],
                                             result.get('summaries', {}),
                                             report_file)

            print(f"\n✅ 任务完成！发现 {len(result['relevant'])} 篇相关论文")

        except Exception as e:
            print(f"❌ 任务执行失败: {e}")
            import traceback
            traceback.print_exc()

    # ---------- Telegram 推送 ----------
    def _check_telegram_config(self) -> bool:
        if not self.tg_token or not self.tg_chat_id:
            print("⚠️  未配置 Telegram（缺少 TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID），跳过推送")
            return False
        return True

    def _tg_notify_no_papers(self):
        if not self._check_telegram_config():
            return
        today = datetime.now().strftime('%Y-%m-%d')
        telegram_send_message(
            f"📭 arXiv 智能日报 {today}\n\n今日无特别相关的论文。",
            self.tg_token, self.tg_chat_id,
        )

    def _send_telegram_notification(self, papers: list, summaries: dict, report_file: str):
        """推送消息 + 报告文件到 Telegram"""
        if not self._check_telegram_config():
            return

        today = datetime.now().strftime('%Y-%m-%d')

        # —— 1. 短消息：标题 + Top N 论文链接 ——
        lines = [f"🤖 arXiv 智能日报 {today}",
                 f"相关论文：{len(papers)} 篇\n"]

        for i, paper in enumerate(papers[:10], 1):
            title = paper['title']
            if len(title) > 80:
                title = title[:77] + "..."
            arxiv_url = f"https://arxiv.org/abs/{paper['arxiv_id']}"
            lines.append(f"{i}. {title}\n   {arxiv_url}")

            # 附带中文摘要（如果有，截取前 150 字）
            if paper['arxiv_id'] in summaries:
                summary_text = summaries[paper['arxiv_id']]
                if len(summary_text) > 150:
                    summary_text = summary_text[:147] + "..."
                lines.append(f"   📝 {summary_text}")
            lines.append("")

        if len(papers) > 10:
            lines.append(f"... 还有 {len(papers) - 10} 篇，请查看完整报告附件")

        try:
            telegram_send_message('\n'.join(lines), self.tg_token, self.tg_chat_id)
            print("📨 Telegram 消息已发送")
        except Exception as e:
            print(f"⚠️  Telegram 消息发送失败: {e}")

        # —— 2. 完整报告文件 ——
        try:
            telegram_send_document(
                report_file,
                caption=f"📊 arXiv 智能日报 {today}（{len(papers)} 篇）",
                token=self.tg_token,
                chat_id=self.tg_chat_id,
            )
            print("📎 Telegram 报告文件已发送")
        except Exception as e:
            print(f"⚠️  Telegram 文件发送失败: {e}")

    # ---------- 定时调度 ----------
    def run_scheduler(self, run_time: str = "09:00"):
        """每天定时运行"""
        print(f"🤖 智能定时任务已启动")
        print(f"⏰ 将在每天 {run_time} 执行")
        print(f"📚 关注分类: {', '.join(self.agent.categories)}")
        print(f"🎯 研究方向: {self.research_interests[:100]}...")
        tg_status = "✅ 已配置" if (self.tg_token and self.tg_chat_id) else "❌ 未配置"
        print(f"📨 Telegram: {tg_status}")
        print("按 Ctrl+C 停止\n")

        schedule.every().day.at(run_time).do(self.daily_job)

        while True:
            schedule.run_pending()
            time.sleep(60)

    def close(self):
        self.agent.close()


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------
def main():
    # 加载 .env
    load_dotenv()

    # ===== 配置区（可按需修改） =====

    # 关注的分类
    categories = [
        'cs.AI',   # Artificial Intelligence
        'cs.LG',   # Machine Learning
        'cs.CV',   # Computer Vision
        'cs.CL',   # NLP
    ]

    # 研究兴趣（越详细，筛选效果越好）
    research_interests = """
    我关注以下 AI 研究方向：

    1. 大语言模型（LLM）
       - 推理能力提升（reasoning, chain-of-thought）
       - 上下文学习和少样本学习
       - 模型对齐和安全性

    2. 多模态模型
       - 视觉-语言模型（VLM）
       - 文生图/图生文
       - 多模态理解和生成

    3. 模型效率
       - 量化和压缩
       - 高效训练和推理
       - 边缘部署

    4. Agent 系统
       - 工具使用
       - 多智能体协作
       - 长期记忆和规划
    """

    # ===== 运行 =====
    agent = ScheduledIntelligentAgent(
        categories=categories,
        research_interests=research_interests,
    )

    try:
        if len(sys.argv) > 1 and sys.argv[1] == '--once':
            print("🔄 单次运行模式\n")
            agent.daily_job()
        else:
            agent.run_scheduler(run_time="09:00")
    except KeyboardInterrupt:
        print("\n\n👋 程序已停止")
    finally:
        agent.close()


if __name__ == '__main__':
    main()
