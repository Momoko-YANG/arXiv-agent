#!/usr/bin/env python3
"""
arXiv Research Agent — 入口
每天自动抓取、筛选、评分、摘要、推送最新论文

用法:
    python main.py              # 定时模式（每天 09:00）
    python main.py --once       # 单次运行
    python main.py --help       # 帮助
"""

import sys
import argparse

from config.settings import load_settings
from scheduler.daily_job import DailyJob


def parse_args():
    parser = argparse.ArgumentParser(
        description="arXiv Research Agent — 智能论文推送系统",
    )
    parser.add_argument(
        "--once", action="store_true",
        help="单次运行（不进入定时模式）",
    )
    parser.add_argument(
        "--time", type=str, default=None,
        help="定时运行时间（默认 09:00），格式 HH:MM",
    )
    parser.add_argument(
        "--days", type=int, default=None,
        help="抓取最近 N 天的论文（默认 1）",
    )
    parser.add_argument(
        "--top", type=int, default=None,
        help="推送前 N 篇论文（默认 5）",
    )
    parser.add_argument(
        "--categories", nargs="+", default=None,
        help="arXiv 分类（如 cs.AI cs.LG cs.CV）",
    )
    react_group = parser.add_mutually_exclusive_group()
    react_group.add_argument(
        "--react", dest="react", action="store_true", default=True,
        help="显式启用 ReAct Agent 模式（默认）",
    )
    react_group.add_argument(
        "--no-react", dest="react", action="store_false",
        help="关闭 ReAct Agent 模式，使用固定流水线",
    )
    parser.add_argument(
        "--summarizer", choices=["oneshot", "threestage"],
        default=None,
        help="摘要模式: oneshot (快/省) 或 threestage (精细)",
    )
    return parser.parse_args()


def main():
    args = parse_args()

    # 构建 overrides
    overrides = {}
    if args.days is not None:
        overrides["days"] = args.days
    if args.top is not None:
        overrides["top_n"] = args.top
    if args.categories is not None:
        overrides["categories"] = args.categories
    if args.time is not None:
        overrides["schedule_time"] = args.time
    overrides["react_mode"] = args.react
    if args.summarizer is not None:
        overrides["summarizer_mode"] = args.summarizer

    # 默认研究兴趣（可在 config/sources.yaml 或 Settings 里修改）
    if "research_interests" not in overrides:
        overrides["research_interests"] = """
        我关注以下 AI 研究方向：
        1. 大语言模型（LLM）— 推理能力、对齐、安全
        2. 多模态模型 — 视觉语言、文生图
        3. 模型效率 — 量化、蒸馏、边缘部署
        4. Agent 系统 — 工具使用、多智能体协作
        """

    # 加载配置
    settings = load_settings(**overrides)

    print("🚀 arXiv Research Agent v3.0")
    print(f"   分类: {', '.join(settings.categories)}")
    print(f"   Top N: {settings.top_n}")
    print(f"   模式: {'ReAct Agent' if settings.react_mode else '流水线'}")
    print(f"   摘要: {settings.summarizer_mode}")
    print(f"   OpenAI: {'✅' if settings.openai_api_key else '❌'}")
    print(f"   Telegram: {'✅' if settings.telegram_bot_token else '❌'}")
    print(f"   S2 API Key: {'✅' if settings.s2_api_key else '⚪ 免费模式'}")
    print()

    job = DailyJob(settings)

    try:
        if args.once:
            print("🔄 单次运行模式\n")
            job.run_once()
        else:
            job.run_scheduled()
    except KeyboardInterrupt:
        print("\n\n👋 程序已停止")
    finally:
        job.close()


if __name__ == "__main__":
    main()
