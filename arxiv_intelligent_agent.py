#!/usr/bin/env python3
"""
Intelligent arXiv Agent with OpenAI API
集成 OpenAI GPT 的智能论文 Agent
"""

import os
import json
from typing import List, Dict, Optional
from datetime import datetime
from arxiv_agent import ArxivAgent
from arxiv_advanced import ArxivDatabase


# ---------------------------------------------------------------------------
# OpenAI 客户端
# ---------------------------------------------------------------------------
class OpenAIClient:
    """OpenAI ChatCompletion 客户端"""

    def __init__(self, api_key: str = None, model: str = None):
        """
        Args:
            api_key: OpenAI API Key，不传则读 OPENAI_API_KEY 环境变量
            model:   默认模型，不传则使用 gpt-4o-mini（便宜且快）
        """
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        if not self.api_key:
            raise ValueError(
                "请设置 OPENAI_API_KEY 环境变量，或通过 api_key 参数传入"
            )

        self.default_model = model or os.getenv("OPENAI_MODEL", "gpt-4o-mini")

        try:
            from openai import OpenAI
            self.client = OpenAI(api_key=self.api_key)
        except ImportError:
            raise ImportError("请安装 openai 库: pip install openai")

    def chat(self, prompt: str, system: str = None, model: str = None) -> str:
        """
        发送 ChatCompletion 请求（带重试）

        Args:
            prompt: 用户消息
            system: 系统提示词（可选）
            model:  覆盖默认模型（可选）
        """
        import time

        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        for attempt in range(3):
            try:
                response = self.client.chat.completions.create(
                    model=model or self.default_model,
                    messages=messages,
                    max_tokens=2000,
                    temperature=0.3,
                )
                return response.choices[0].message.content
            except Exception as e:
                if attempt < 2:
                    wait = 2 ** (attempt + 1)  # 2s, 4s
                    print(f"    ⚠️  OpenAI 请求失败，{wait}s 后重试: {e}")
                    time.sleep(wait)
                else:
                    raise


# ---------------------------------------------------------------------------
# 智能 arXiv Agent
# ---------------------------------------------------------------------------
class IntelligentArxivAgent:
    """智能 arXiv Agent（使用 OpenAI GPT 做筛选 / 摘要 / 问答）"""

    def __init__(self,
                 categories: List[str],
                 api_key: str = None,
                 model: str = None,
                 db_path: str = "arxiv_intelligent.db"):
        """
        Args:
            categories: 关注的 arXiv 分类
            api_key:    OpenAI API Key
            model:      GPT 模型名称（默认 gpt-4o-mini）
            db_path:    SQLite 数据库路径
        """
        self.arxiv_agent = ArxivAgent(categories=categories)
        self.db = ArxivDatabase(db_path=db_path)
        self.llm = OpenAIClient(api_key=api_key, model=model)
        self.categories = categories

    # ---------- 主流程 ----------

    def fetch_and_analyze(self,
                          days: int = 1,
                          research_interests: str = None,
                          auto_summarize: bool = True) -> Dict:
        """抓取并智能分析论文"""
        print(f"\n{'=' * 80}")
        print(f"开始智能抓取与分析 - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"{'=' * 80}\n")

        # 1. 抓取论文
        print("📥 正在从 arXiv 抓取论文...")
        papers = self.arxiv_agent.fetch_recent_papers(days=days, max_results=100)

        if not papers:
            print("❌ 没有抓取到论文")
            return {"papers": [], "relevant": [], "summaries": {}}

        print(f"✅ 成功抓取 {len(papers)} 篇论文\n")

        # 2. 智能筛选
        relevant_papers = papers
        if research_interests:
            print("🤖 正在使用 GPT 智能筛选相关论文...")
            relevant_papers = self.filter_relevant_papers(papers, research_interests)
            print(f"✅ 筛选出 {len(relevant_papers)} 篇相关论文\n")

        # 3. 生成中文摘要
        summaries = {}
        if auto_summarize and relevant_papers:
            import time
            n = min(len(relevant_papers), 5)
            print(f"📝 正在为 {n} 篇论文生成中文摘要...")
            for i, paper in enumerate(relevant_papers[:5], 1):
                print(f"  处理 {i}/{n}: {paper['title'][:50]}...")
                summary = self.summarize_paper(paper)
                if not summary.startswith("摘要生成失败"):
                    summaries[paper['arxiv_id']] = summary
                else:
                    print(f"    ❌ {summary}")
                # 每次请求间隔 1 秒，避免触发速率限制
                if i < n:
                    time.sleep(1)
            print(f"  ✅ 成功生成 {len(summaries)}/{n} 篇摘要")
            print()

        # 4. 保存到数据库
        print("💾 保存到数据库...")
        new_count = sum(1 for p in papers if self.db.insert_paper(p))
        print(f"✅ 新增 {new_count} 篇论文到数据库\n")

        return {
            "papers": papers,
            "relevant": relevant_papers,
            "summaries": summaries,
        }

    # ---------- 筛选 ----------

    def filter_relevant_papers(self,
                               papers: List[Dict],
                               research_interests: str,
                               top_k: int = 10) -> List[Dict]:
        """使用 GPT 筛选与研究方向最相关的论文"""
        papers_text = []
        for i, paper in enumerate(papers):
            papers_text.append(
                f"{i+1}. ID: {paper['arxiv_id']}\n"
                f"   标题: {paper['title']}\n"
                f"   摘要: {paper['summary'][:300]}...\n"
            )

        prompt = f"""我的研究兴趣是：{research_interests}

以下是最近的 arXiv 论文列表：

{''.join(papers_text)}

请分析哪些论文与我的研究兴趣最相关。

要求：
1. 返回最相关的 {top_k} 篇论文的 ID（格式如 2402.12345）
2. 每个 ID 占一行
3. 按相关性从高到低排序
4. 只返回 ID 列表，不要其他解释

格式示例：
2402.12345
2402.12346
"""
        system = "你是一个学术论文分析专家，擅长根据研究方向筛选相关论文。"

        try:
            response = self.llm.chat(prompt, system=system)

            relevant_ids = []
            for line in response.strip().split('\n'):
                line = line.strip()
                if len(line) >= 10 and '.' in line:
                    relevant_ids.append(line)

            id_to_paper = {p['arxiv_id']: p for p in papers}
            relevant_papers = [id_to_paper[aid] for aid in relevant_ids if aid in id_to_paper]
            return relevant_papers[:top_k]

        except Exception as e:
            print(f"⚠️  筛选失败: {e}")
            return papers[:top_k]

    # ---------- 摘要 ----------

    def summarize_paper(self, paper: Dict, language: str = 'zh') -> str:
        """生成论文中文/英文摘要"""
        lang_name = "中文" if language == 'zh' else "English"

        prompt = f"""请用{lang_name}总结这篇论文：

标题: {paper['title']}

摘要: {paper['summary']}

要求：
1. 用 2-3 句话概括核心内容
2. 突出创新点和主要贡献
3. 使用简洁的学术语言
4. 如果是中文，使用中文专业术语
"""
        system = f"你是一个学术论文总结专家，擅长用{lang_name}清晰简洁地总结论文核心内容。"

        try:
            return self.llm.chat(prompt, system=system).strip()
        except Exception as e:
            return f"摘要生成失败: {e}"

    # ---------- 问答 ----------

    def ask_question(self, question: str, context_days: int = 7) -> str:
        """对话式检索论文"""
        papers = self.db.get_recent_papers(days=context_days, limit=50)
        if not papers:
            return "数据库中没有找到相关论文。"

        context = []
        for paper in papers:
            context.append(
                f"- {paper['title']}\n"
                f"  ID: {paper['arxiv_id']}, 发布: {paper['published']}\n"
            )

        prompt = f"""基于以下最近 {context_days} 天的 arXiv 论文：

{''.join(context)}

请回答：{question}

要求：
1. 基于提供的论文列表回答
2. 引用具体的论文（标题和 ID）
3. 如果没有相关论文，请说明
4. 用中文回答
"""
        system = "你是一个学术论文助手，帮助用户从论文库中找到相关信息。"

        try:
            return self.llm.chat(prompt, system=system)
        except Exception as e:
            return f"查询失败: {e}"

    # ---------- 报告 ----------

    def generate_daily_report(self, summaries: Dict, relevant_papers: List[Dict]) -> str:
        """生成每日智能报告"""
        report = []
        report.append("=" * 80)
        report.append(f"arXiv 智能日报 - {datetime.now().strftime('%Y年%m月%d日')}")
        report.append("=" * 80)
        report.append("")

        if not relevant_papers:
            report.append("今日无特别相关的论文。")
            return '\n'.join(report)

        report.append(f"📊 今日共发现 {len(relevant_papers)} 篇相关论文")
        report.append("")

        for i, paper in enumerate(relevant_papers, 1):
            report.append(f"## {i}. {paper['title']}")
            report.append(f"**arXiv ID**: {paper['arxiv_id']}")
            authors_str = ', '.join(paper['authors'][:3])
            if len(paper['authors']) > 3:
                authors_str += '...'
            report.append(f"**作者**: {authors_str}")
            report.append(f"**分类**: {', '.join(paper['categories'])}")
            report.append(f"**链接**: https://arxiv.org/abs/{paper['arxiv_id']}")
            report.append("")

            if paper['arxiv_id'] in summaries:
                report.append("**中文摘要**:")
                report.append(summaries[paper['arxiv_id']])
            else:
                report.append("**原文摘要**:")
                report.append(paper['summary'][:300] + "...")

            report.append("")
            report.append("-" * 80)
            report.append("")

        return '\n'.join(report)

    def close(self):
        """关闭数据库"""
        self.db.close()


# ---------------------------------------------------------------------------
# 独立运行演示
# ---------------------------------------------------------------------------
if __name__ == '__main__':
    categories = ['cs.AI', 'cs.LG', 'cs.CV', 'cs.CL']
    research_interests = """
    我关注大语言模型（LLM）的以下方向：
    1. 推理能力提升（reasoning, chain-of-thought）
    2. 多模态大模型（vision-language models）
    3. 模型压缩和效率优化
    4. 提示工程和上下文学习
    """

    agent = IntelligentArxivAgent(categories=categories)

    try:
        print("=" * 80)
        print("🤖 智能 arXiv Agent 演示")
        print("=" * 80)

        result = agent.fetch_and_analyze(
            days=1,
            research_interests=research_interests,
            auto_summarize=True,
        )

        report = agent.generate_daily_report(
            summaries=result['summaries'],
            relevant_papers=result['relevant'],
        )

        report_file = f"intelligent_report_{datetime.now().strftime('%Y%m%d')}.md"
        with open(report_file, 'w', encoding='utf-8') as f:
            f.write(report)
        print(f"✅ 报告已保存: {report_file}\n")

    finally:
        agent.close()
        print("\n✅ 完成！")
