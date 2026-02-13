"""
每日定时任务 — 调度 Aggregator + Notifier
"""

import time
import schedule
from datetime import datetime

from config.settings import Settings
from agents.aggregator import PaperAggregator
from notifier.telegram_bot import TelegramNotifier


class DailyJob:
    """每日智能论文推送任务"""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.aggregator = PaperAggregator(settings)
        self.notifier = TelegramNotifier(
            token=settings.telegram_bot_token,
            chat_id=settings.telegram_chat_id,
        )

    def run_once(self):
        """单次执行完整流水线"""
        print(f"\n{'=' * 80}")
        print(f"🤖 智能日报任务开始 - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"{'=' * 80}\n")

        try:
            # 1. 运行完整流水线
            result = self.aggregator.run_pipeline()

            if not result["relevant"]:
                print("❌ 今日无相关论文")
                self.notifier.send_daily_report([], {})
                return

            # 2. 生成报告
            report = self.aggregator.generate_report(result)
            report_file = f"data/processed/report_{datetime.now().strftime('%Y%m%d')}.md"

            with open(report_file, "w", encoding="utf-8") as f:
                f.write(report)
            print(f"✅ 报告已保存: {report_file}")

            # 3. 推送 Telegram
            self.notifier.send_daily_report(
                papers=result["relevant"],
                summaries=result.get("summaries", {}),
                report_file=report_file,
            )

            print(f"\n✅ 任务完成！发现 {len(result['relevant'])} 篇相关论文")

        except Exception as e:
            print(f"❌ 任务执行失败: {e}")
            import traceback
            traceback.print_exc()

    def run_scheduled(self, run_time: str = None):
        """定时调度（每天运行一次）"""
        run_time = run_time or self.settings.schedule_time

        print(f"🤖 智能定时任务已启动")
        print(f"⏰ 每天 {run_time} 执行")
        print(f"📚 关注分类: {', '.join(self.settings.categories)}")
        print(f"📨 Telegram: {'✅ 已配置' if self.notifier.configured else '❌ 未配置'}")
        print("按 Ctrl+C 停止\n")

        schedule.every().day.at(run_time).do(self.run_once)

        while True:
            schedule.run_pending()
            time.sleep(60)

    def close(self):
        self.aggregator.close()
