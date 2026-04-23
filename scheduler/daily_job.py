"""
每日定时任务 — 精确调度 Aggregator + Notifier

使用墙钟计算替代 schedule + sleep(60) 轮询，消除长期运行的时间漂移问题。

漂移根因分析：
    旧方案: schedule.run_pending() + time.sleep(60) 每分钟轮询
    - time.sleep(60) 精度受 OS 调度影响，在负载下单次可多睡数百毫秒
    - run_once() 执行期间（5~20 分钟）不检测，导致检测窗口错位
    - 数月累计：每天偏移 1~5 秒 → 半年后偏移 3~15 分钟

    新方案: 每次从系统墙钟重新计算到目标时间的精确差值
    - 不依赖 sleep 的累积精度，每次循环重新对齐
    - 分段 sleep：远离目标 → 60s 醒一次；接近目标 → 0.5s 醒一次
    - 理论精度 < 1 秒，无累积漂移
"""

import threading
from datetime import datetime, timedelta

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
            feedback_callback=self._on_feedback,
        )
        self._stop_event = threading.Event()

    def _on_feedback(self, arxiv_id: str, action: str,
                     source_id: str = None):
        """Telegram 反馈回调 → 写入数据库"""
        try:
            inserted = self.aggregator.db.add_feedback(arxiv_id, action, source_id)
            if inserted:
                print(f"  📝 反馈已记录: {action} → {arxiv_id}")
            else:
                print(f"  ↩️  重复回调已忽略: {action} → {arxiv_id}")
        except Exception as e:
            print(f"  ⚠️ 反馈记录失败: {e}")

    def run_once(self):
        """单次执行完整流水线"""
        print(f"\n{'=' * 80}")
        print(f"🤖 智能日报任务开始 - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"{'=' * 80}\n")

        try:
            result = self.aggregator.run_pipeline()
            status = result.get("status", "ok")

            if not result["relevant"]:
                if status == "no_new_papers":
                    print("ℹ️ 今日无新论文")
                    if self.notifier.configured:
                        self.notifier.send_message(
                            f"📭 arXiv 智能日报 {datetime.now().strftime('%Y-%m-%d')}\n\n今日没有新增论文。"
                        )
                else:
                    print("❌ 今日无相关论文")
                    self.notifier.send_daily_report([], {})
                return

            report = self.aggregator.generate_report(result)
            report_file = f"data/processed/report_{datetime.now().strftime('%Y%m%d')}.md"

            with open(report_file, "w", encoding="utf-8") as f:
                f.write(report)
            print(f"✅ 报告已保存: {report_file}")

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

    # ------------------------------------------------------------------
    # 精确定时 — 替代 schedule + sleep(60) 轮询
    # ------------------------------------------------------------------

    @staticmethod
    def _next_run_time(target_time_str: str) -> datetime:
        """计算下一次运行的精确时间点"""
        h, m = map(int, target_time_str.split(":"))
        now = datetime.now()
        target = now.replace(hour=h, minute=m, second=0, microsecond=0)
        if target <= now:
            target += timedelta(days=1)
        return target

    def _sleep_until(self, target_time_str: str):
        """
        精确等待到目标时间 — 零漂移

        每次循环从系统墙钟重新计算剩余时间，不依赖 sleep 的累积精度。
        分段策略：
          >5min  → 每 60s 醒来对齐一次
          >30s   → 每 5s 醒来
          ≤30s   → 每 0.5s 醒来（精确到秒级）
        """
        while not self._stop_event.is_set():
            target = self._next_run_time(target_time_str)
            remaining = (target - datetime.now()).total_seconds()

            if remaining <= 0:
                break

            if remaining > 300:
                sleep_time = 60.0
            elif remaining > 30:
                sleep_time = 5.0
            else:
                sleep_time = 0.5

            self._stop_event.wait(timeout=min(sleep_time, remaining))

    def run_scheduled(self, run_time: str = None):
        """
        定时调度（每天运行一次）

        使用精确墙钟等待，无 schedule 库依赖，无累积漂移。
        """
        run_time = run_time or self.settings.schedule_time

        print(f"🤖 智能定时任务已启动")
        print(f"⏰ 每天 {run_time} 精确执行（零漂移调度器）")
        print(f"📚 关注分类: {', '.join(self.settings.categories)}")
        print(f"📨 Telegram: {'✅ 已配置' if self.notifier.configured else '❌ 未配置'}")
        print("按 Ctrl+C 停止\n")

        # 启动 Telegram 反馈监听（后台线程）
        self.notifier.start_callback_listener()

        while not self._stop_event.is_set():
            next_time = self._next_run_time(run_time)
            print(f"⏳ 下次运行: {next_time.strftime('%Y-%m-%d %H:%M:%S')}")

            self._sleep_until(run_time)

            if not self._stop_event.is_set():
                actual = datetime.now().strftime('%H:%M:%S')
                print(f"⏰ 触发时间: {actual}（目标: {run_time}:00）")
                self.run_once()

    def stop(self):
        """停止调度"""
        self._stop_event.set()

    def close(self):
        self.stop()
        self.notifier.stop_callback_listener()
        self.aggregator.close()
