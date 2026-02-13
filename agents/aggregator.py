"""
Paper Aggregator — 聚合所有数据源 + 评分 + 筛选 + 摘要

优化后的流水线（比 v1 快 3-5x）：
    arXiv → S2 批量查（1次请求）→ 关键词预筛 or GPT筛选
    → 评分排序 → 截取 Top N → Crossref 只查 Top N → 摘要 → 入库
"""

from datetime import datetime
from typing import List, Dict

from agents.arxiv_agent import ArxivAgent
from agents.semantic_agent import SemanticScholarClient
from agents.crossref_agent import CrossrefClient
from scoring import (
    ScoringPipeline, CitationScorer, AuthorScorer,
    VenueScorer, FreshnessScorer, KeywordScorer,
)
from summarizer.llm_summarizer import PaperSummarizer, extract_key_sentences
from summarizer.prompt_templates import FILTER_SYSTEM, FILTER_PROMPT
from llm_client import LLMClient
from utils.database import ArxivDatabase


class PaperAggregator:
    """论文聚合 + 分析 Agent"""

    def __init__(self, settings):
        self.settings = settings

        # 各数据源
        self.arxiv = ArxivAgent(categories=settings.categories)
        self.s2 = SemanticScholarClient(api_key=settings.s2_api_key)
        self.cr = CrossrefClient(mailto=settings.crossref_mailto)

        # LLM（纯 HTTP 直连，无 SDK 依赖）
        self.llm = LLMClient(
            api_key=settings.openai_api_key,
            model=settings.openai_model,
        )

        # 评分
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
        s = self.settings
        print(f"\n{'=' * 80}")
        print(f"开始智能抓取与分析 - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"{'=' * 80}\n")

        # Step 1: arXiv 抓取
        print("📥 Step 1/6: arXiv 抓取...")
        papers = self.arxiv.fetch_recent_papers(days=s.days, max_results=s.max_results)
        if not papers:
            print("❌ 没有抓取到论文")
            return {"papers": [], "relevant": [], "summaries": {}}
        print(f"  ✅ 共 {len(papers)} 篇\n")

        # Step 2: 优先尝试 GPT 筛选（失败自动降级）
        print("🤖 Step 2/6: 论文筛选...")
        if s.research_interests:
            print("  使用 GPT 智能筛选...")
            relevant = self._filter_relevant(papers, s.research_interests)
        else:
            print("  未设置研究兴趣，使用关键词预筛选")
            relevant = self._keyword_prefilter(papers)
        print(f"  ✅ 筛选出 {len(relevant)} 篇\n")

        # Step 3: Semantic Scholar 批量查（一次请求）
        if relevant:
            print("📡 Step 3/6: Semantic Scholar 批量补充...")
            self.s2.enrich_papers(relevant)
            print()

        # Step 4: 评分排序 → 截取 Top N → 只对 Top N 查 Crossref
        if relevant:
            print("📊 Step 4/6: 评分排序...")
            self.scorer.rank_papers(relevant)
            self._print_ranking(relevant)

        top_papers = relevant[:s.top_n]

        # 只对最终推送的论文查 Crossref（省 50%+ 时间）
        if top_papers:
            print(f"📖 Crossref 验证 Top {len(top_papers)} 篇...")
            self.cr.enrich_papers(top_papers)
            # Crossref 数据回来后重新评分一次
            self.scorer.rank_papers(top_papers)
            print()

        # Step 5: 摘要
        summaries = {}
        if top_papers:
            n = len(top_papers)
            # 筛选阶段失败后，这里再给 LLM 一次机会（摘要优先）
            self.llm.reset_circuit()
            print(f"🧠 Step 5/6: 三段式摘要优先（{n} 篇）")
            summaries = self.summarizer.summarize_batch(top_papers, delay=0.5)
            if not summaries:
                print(f"  ⚠️  LLM 摘要全部失败，降级规则摘要")
                summaries = self._fallback_summaries(top_papers)
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
    # 筛选方法
    # ------------------------------------------------------------------

    def _filter_relevant(self, papers: List[Dict],
                         research_interests: str,
                         top_k: int = 10) -> List[Dict]:
        """GPT 智能筛选"""
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
            response = self.llm.generate(prompt, system=FILTER_SYSTEM)
            print("  🧪 [DEBUG] GPT 原始 response:")
            print(response[:1500] + ("..." if len(response) > 1500 else ""))
            relevant_ids = []
            for line in response.strip().split("\n"):
                line = line.strip()
                if len(line) >= 10 and "." in line:
                    relevant_ids.append(line)

            print(f"  🧪 [DEBUG] relevant_ids({len(relevant_ids)}): {relevant_ids}")

            id_to_paper = {p["arxiv_id"]: p for p in papers}
            sample_ids = list(id_to_paper.keys())[:10]
            print(f"  🧪 [DEBUG] papers arxiv_id 样例({len(sample_ids)}): {sample_ids}")
            result = [id_to_paper[aid] for aid in relevant_ids if aid in id_to_paper]
            if result:
                return result[:top_k]
        except Exception as e:
            print(f"  ⚠️  GPT 筛选失败: {e}")

        # GPT 失败时降级到关键词预筛
        print("  ⚠️  降级到关键词预筛选")
        return self._keyword_prefilter(papers, top_k)

    def _keyword_prefilter(self, papers: List[Dict],
                           top_k: int = 10) -> List[Dict]:
        """
        关键词预筛选（不需要 LLM，0 延迟）

        用 bonus_keywords 做文本匹配，按命中数排序
        """
        keywords = self.settings.bonus_keywords
        if not keywords:
            return papers[:top_k]

        scored = []
        for p in papers:
            text = (p.get("title", "") + " " + p.get("summary", "")).lower()
            hits = sum(1 for kw in keywords if kw.lower() in text)
            scored.append((hits, p))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [p for _, p in scored[:top_k]]

    # ------------------------------------------------------------------
    # 降级摘要
    # ------------------------------------------------------------------

    def _fallback_summaries(self, papers: List[Dict]) -> Dict[str, str]:
        """LLM 不可用时的规则摘要（用关键句抽取生成简版摘要）"""
        results = {}
        for p in papers:
            abstract = p.get("summary", "")
            if not abstract:
                continue
            key = extract_key_sentences(abstract, max_sentences=3)
            # 截取前 200 字符，格式化为要点
            if len(key) > 200:
                key = key[:197] + "..."
            results[p["arxiv_id"]] = f"• {key}"
        return results

    # ------------------------------------------------------------------
    # 报告生成
    # ------------------------------------------------------------------

    def generate_report(self, result: Dict) -> str:
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

            s2_authors = paper.get("s2_authors", [])
            valid_s2_authors = [a for a in s2_authors if (a.get("name") or "").strip()]
            if valid_s2_authors:
                parts = []
                for a in valid_s2_authors[:5]:
                    name = a.get("name", "")
                    affs = ", ".join(a.get("affiliations", []))
                    parts.append(f"{name} ({affs})" if affs else name)
                if len(valid_s2_authors) > 5:
                    parts.append("...")
                report.append(f"**作者**: {'; '.join(parts)}")
            else:
                authors_str = ", ".join(paper.get("authors", [])[:3])
                if len(paper.get("authors", [])) > 3:
                    authors_str += "..."
                report.append(f"**作者**: {authors_str}")

            report.append(f"**分类**: {', '.join(paper.get('categories', []))}")

            citations = paper.get("s2_citation_count", 0)
            influential = paper.get("s2_influential_citation_count", 0)
            report.append(f"**引用**: {citations} (有影响力: {influential})")

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

    def _print_ranking(self, papers: List[Dict]):
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
