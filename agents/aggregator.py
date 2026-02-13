"""
Paper Aggregator — 聚合所有数据源 + 评分 + 筛选 + 摘要

这是 Agent 系统的核心编排层：
    arXiv → GPT 筛选 → Semantic Scholar → Crossref → 评分排序 → 三段式摘要 → 入库
"""

from datetime import datetime
from typing import List, Dict, Optional

from agents.arxiv_agent import ArxivAgent
from agents.semantic_agent import SemanticScholarClient
from agents.crossref_agent import CrossrefClient
from scoring import (
    ScoringPipeline, CitationScorer, AuthorScorer,
    VenueScorer, FreshnessScorer, KeywordScorer,
)
from summarizer.llm_summarizer import PaperSummarizer
from summarizer.prompt_templates import FILTER_SYSTEM, FILTER_PROMPT
from utils.llm_client import OpenAIClient
from utils.database import ArxivDatabase


class PaperAggregator:
    """
    论文聚合 + 分析 Agent

    用法:
        agg = PaperAggregator(settings)
        result = agg.run_pipeline()
        report = agg.generate_report(result)
    """

    def __init__(self, settings):
        """
        Args:
            settings: config.settings.Settings 实例
        """
        self.settings = settings

        # 各数据源 Agent
        self.arxiv = ArxivAgent(categories=settings.categories)
        self.s2 = SemanticScholarClient(api_key=settings.s2_api_key)
        self.cr = CrossrefClient(mailto=settings.crossref_mailto)

        # LLM
        self.llm = OpenAIClient(
            api_key=settings.openai_api_key,
            model=settings.openai_model,
        )

        # 评分流水线（可插拔）
        self.scorer = ScoringPipeline([
            CitationScorer(weight=30),
            AuthorScorer(weight=20),
            VenueScorer(weight=20),
            FreshnessScorer(weight=15),
            KeywordScorer(keywords=settings.bonus_keywords, weight=15),
        ])

        # 三段式摘要
        self.summarizer = PaperSummarizer(llm_client=self.llm, language="zh")

        # 数据库
        self.db = ArxivDatabase(db_path=settings.db_path)

    # ------------------------------------------------------------------
    # 完整流水线
    # ------------------------------------------------------------------

    def run_pipeline(self) -> Dict:
        """
        完整六步流水线

        Returns:
            {
                "papers":    所有论文,
                "relevant":  Top N 论文,
                "summaries": {arxiv_id: summary},
            }
        """
        s = self.settings
        print(f"\n{'=' * 80}")
        print(f"开始智能抓取与分析 - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"{'=' * 80}\n")

        # Step 1: arXiv
        print("📥 Step 1/6: 从 arXiv 抓取论文...")
        papers = self.arxiv.fetch_recent_papers(days=s.days, max_results=s.max_results)
        if not papers:
            print("❌ 没有抓取到论文")
            return {"papers": [], "relevant": [], "summaries": {}}
        print(f"  ✅ 共 {len(papers)} 篇\n")

        # Step 2: GPT 筛选
        relevant = papers
        if s.research_interests:
            print("🤖 Step 2/6: GPT 智能筛选...")
            relevant = self._filter_relevant(papers, s.research_interests)
            print(f"  ✅ 筛选出 {len(relevant)} 篇相关论文\n")
        else:
            print("⏩ Step 2/6: 跳过（未设置研究兴趣）\n")

        # Step 3: Semantic Scholar
        if relevant:
            print("📡 Step 3/6: Semantic Scholar 补充...")
            self.s2.enrich_papers(relevant)
            print()

        # Step 4: Crossref
        if relevant:
            print("📖 Step 4/6: Crossref 发表状态...")
            self.cr.enrich_papers(relevant)
            print()

        # 评分排序
        if relevant:
            print("📊 评分排序...")
            self.scorer.rank_papers(relevant)
            self._print_ranking(relevant)

        # 截取 Top N
        top_papers = relevant[:s.top_n]

        # Step 5: 三段式摘要
        summaries = {}
        if top_papers:
            n = len(top_papers)
            print(f"🧠 Step 5/6: 三段式摘要（{n} 篇）")
            print(f"   关键句抽取 → 结构化提取 → 语义压缩重写")
            summaries = self.summarizer.summarize_batch(top_papers, delay=1.0)
            print(f"  ✅ 生成 {len(summaries)}/{n} 篇摘要\n")

        # Step 6: 入库
        print("💾 Step 6/6: 保存到数据库...")
        new_count = sum(1 for p in papers if self.db.insert_paper(p))
        print(f"  ✅ 新增 {new_count} 篇\n")

        return {
            "papers": papers,
            "relevant": top_papers,
            "summaries": summaries,
        }

    # ------------------------------------------------------------------
    # GPT 筛选
    # ------------------------------------------------------------------

    def _filter_relevant(self, papers: List[Dict],
                         research_interests: str,
                         top_k: int = 10) -> List[Dict]:
        """使用 GPT 筛选最相关的论文"""
        papers_text = ""
        for i, p in enumerate(papers):
            papers_text += (
                f"{i+1}. ID: {p['arxiv_id']}\n"
                f"   标题: {p['title']}\n"
                f"   摘要: {p['summary'][:300]}...\n\n"
            )

        prompt = FILTER_PROMPT.format(
            research_interests=research_interests,
            papers_text=papers_text,
            top_k=top_k,
        )

        try:
            response = self.llm.chat(prompt, system=FILTER_SYSTEM)
            relevant_ids = []
            for line in response.strip().split("\n"):
                line = line.strip()
                if len(line) >= 10 and "." in line:
                    relevant_ids.append(line)

            id_to_paper = {p["arxiv_id"]: p for p in papers}
            return [id_to_paper[aid] for aid in relevant_ids if aid in id_to_paper][:top_k]

        except Exception as e:
            print(f"  ⚠️  GPT 筛选失败: {e}")
            return papers[:top_k]

    # ------------------------------------------------------------------
    # 报告生成
    # ------------------------------------------------------------------

    def generate_report(self, result: Dict) -> str:
        """生成 Markdown 日报"""
        papers = result.get("relevant", [])
        summaries = result.get("summaries", {})

        report = []
        report.append("=" * 80)
        report.append(f"arXiv 智能日报 - {datetime.now().strftime('%Y年%m月%d日')}")
        report.append("=" * 80)
        report.append("")

        if not papers:
            report.append("今日无特别相关的论文。")
            return "\n".join(report)

        report.append(f"📊 今日共发现 {len(papers)} 篇相关论文")
        report.append("")

        for i, paper in enumerate(papers, 1):
            score = paper.get("quality_score", 0)
            report.append(f"## {i}. {paper['title']}")
            report.append(f"**质量评分**: {score}/100")
            report.append(f"**arXiv ID**: {paper['arxiv_id']}")

            # 作者（优先 S2 机构信息）
            s2_authors = paper.get("s2_authors", [])
            if s2_authors:
                parts = []
                for a in s2_authors[:5]:
                    name = a.get("name", "")
                    affs = ", ".join(a.get("affiliations", []))
                    parts.append(f"{name} ({affs})" if affs else name)
                if len(s2_authors) > 5:
                    parts.append("...")
                report.append(f"**作者**: {'; '.join(parts)}")
            else:
                authors_str = ", ".join(paper.get("authors", [])[:3])
                if len(paper.get("authors", [])) > 3:
                    authors_str += "..."
                report.append(f"**作者**: {authors_str}")

            report.append(f"**分类**: {', '.join(paper.get('categories', []))}")

            # 引用
            citations = paper.get("s2_citation_count", 0)
            influential = paper.get("s2_influential_citation_count", 0)
            report.append(f"**引用**: {citations} (有影响力: {influential})")

            # 发表状态
            venue = paper.get("s2_venue", "")
            if paper.get("cr_published"):
                journal = paper.get("cr_journal", "") or venue
                doi = paper.get("cr_doi", "")
                pub_info = f"✅ 已发表 — {journal}"
                if doi:
                    pub_info += f" (DOI: {doi})"
                report.append(f"**发表状态**: {pub_info}")
            elif venue:
                report.append(f"**发表状态**: 📋 {venue}")
            else:
                report.append(f"**发表状态**: 📝 预印本")

            report.append(f"**链接**: https://arxiv.org/abs/{paper['arxiv_id']}")
            report.append("")

            # 摘要
            if paper["arxiv_id"] in summaries:
                report.append("**智能摘要**:")
                report.append(summaries[paper["arxiv_id"]])
            else:
                report.append("**原文摘要**:")
                report.append(paper["summary"][:300] + "...")

            report.append("")
            report.append("-" * 80)
            report.append("")

        return "\n".join(report)

    # ------------------------------------------------------------------
    # 辅助
    # ------------------------------------------------------------------

    def _print_ranking(self, papers: List[Dict]):
        """打印评分排名"""
        print("-" * 70)
        for i, p in enumerate(papers[:10], 1):
            citations = p.get("s2_citation_count", 0)
            venue = p.get("s2_venue", "") or p.get("cr_journal", "") or "—"
            status = "📄" if p.get("cr_published") else "📝"
            score = p.get("quality_score", 0)
            print(f"  {i:>2}. [{score:>5.1f}分] {status} 引用:{citations:>4} "
                  f"| {venue[:20]:20s} | {p['title'][:45]}")
        print("-" * 70)
        print()

    def close(self):
        self.db.close()
