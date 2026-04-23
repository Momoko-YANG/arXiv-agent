"""
Paper Aggregator — 聚合所有数据源 + 评分 + 筛选 + 摘要

v3 优化（比 v2 快 2-3x，功能更强）：
    1. 增量去重 — 已入库论文不再重复处理
    2. 缓存层 — S2/Crossref 结果 7 天缓存，避免重复 API 调用
    3. 并行 Crossref — ThreadPoolExecutor 3 workers
    4. 并行摘要 — oneshot 模式可并行（1 次 LLM/篇）
    5. 自适应评分 — 读取用户反馈自动调整评分权重
    6. ReAct 模式 — 可选的 LLM 驱动决策循环
    7. 决策日志 — 每次运行记录策略和结果
"""

from datetime import datetime
from typing import List, Dict
import json
import re

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
from utils.cache import DiskCache
from agents.tools import ToolRegistry, Tool
from agents.react_agent import ReactAgent


class PaperAggregator:
    """论文聚合 + 分析 Agent"""

    def __init__(self, settings):
        self.settings = settings

        # 缓存层（v3 新增）
        self._cache = DiskCache(db_path="data/cache/cache.db")

        # 各数据源（注入缓存）
        self.arxiv = ArxivAgent(categories=settings.categories)
        self.s2 = SemanticScholarClient(
            api_key=settings.s2_api_key, cache=self._cache,
        )
        self.cr = CrossrefClient(
            mailto=settings.crossref_mailto, cache=self._cache,
        )

        # LLM（纯 HTTP 直连，无 SDK 依赖）
        self.llm = None
        if settings.openai_api_key:
            self.llm = LLMClient(
                api_key=settings.openai_api_key,
                model=settings.openai_model,
            )

        # 评分（默认权重，后续可被 _adapt_weights 调整）
        self._default_weights = {
            "citation": 30, "author": 20, "venue": 20,
            "freshness": 15, "keyword": 15,
        }
        self.scorer = self._build_scorer(self._default_weights)

        # 摘要（v3: oneshot 模式，1 次 LLM 调用/篇）
        self.summarizer = PaperSummarizer(
            llm_client=self.llm,
            language="zh",
            mode=getattr(settings, "summarizer_mode", "oneshot"),
        )

        # 数据库
        self.db = ArxivDatabase(db_path=settings.db_path)

    def _build_scorer(self, weights: dict) -> ScoringPipeline:
        return ScoringPipeline([
            CitationScorer(weight=weights["citation"]),
            AuthorScorer(weight=weights["author"]),
            VenueScorer(weight=weights["venue"]),
            FreshnessScorer(weight=weights["freshness"]),
            KeywordScorer(
                keywords=self.settings.bonus_keywords,
                weight=weights["keyword"],
            ),
        ])

    # ------------------------------------------------------------------
    # 自适应评分（v3 新增）
    # ------------------------------------------------------------------

    def _adapt_weights(self) -> dict:
        """
        根据用户反馈历史自动调整评分权重

        策略：
        - 分析被 star 的论文有哪些共性（高引用？知名机构？特定关键词？）
        - 分析被 dismiss 的论文有哪些特征
        - 相应地增加/减少对应评分器的权重
        """
        weights = dict(self._default_weights)

        try:
            feedback = self.db.get_feedback_stats(days=30)
        except Exception:
            return weights

        if feedback["star_count"] < 3:
            # 反馈不足，使用默认权重
            return weights

        starred = feedback.get("starred_papers", [])
        if not starred:
            return weights

        # 分析 star 论文的共性
        avg_citations = sum(p.get("citation_count", 0) for p in starred) / len(starred)
        avg_score = sum(p.get("quality_score", 0) for p in starred) / len(starred)
        published_ratio = sum(1 for p in starred if p.get("published_status")) / len(starred)

        # 高引用偏好 → 提升引用权重
        if avg_citations > 20:
            weights["citation"] = min(45, weights["citation"] + 10)
            weights["freshness"] = max(5, weights["freshness"] - 5)

        # 喜欢已发表论文 → 提升 venue 权重
        if published_ratio > 0.7:
            weights["venue"] = min(35, weights["venue"] + 10)
            weights["keyword"] = max(5, weights["keyword"] - 5)

        # 低引用偏好（喜欢新论文）→ 提升新鲜度
        if avg_citations < 5:
            weights["freshness"] = min(30, weights["freshness"] + 10)
            weights["citation"] = max(10, weights["citation"] - 5)

        print(f"  📊 自适应权重: {weights}")
        return weights

    # ------------------------------------------------------------------
    # 完整流水线
    # ------------------------------------------------------------------

    def run_pipeline(self) -> Dict:
        s = self.settings
        print(f"\n{'=' * 80}")
        print(f"开始智能抓取与分析 - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"{'=' * 80}\n")

        # Step 0: 自适应评分权重（v3 新增）
        adapted_weights = self._adapt_weights()
        if adapted_weights != self._default_weights:
            self.scorer = self._build_scorer(adapted_weights)

        # Step 1: arXiv 抓取
        print("📥 Step 1/6: arXiv 抓取...")
        papers = self.arxiv.fetch_recent_papers(days=s.days, max_results=s.max_results)
        if not papers:
            print("❌ 没有抓取到论文")
            return {"status": "no_papers", "papers": [], "relevant": [], "summaries": {}}
        print(f"  ✅ 共 {len(papers)} 篇\n")

        # Step 1.5: 增量去重（v3 新增）
        known_ids = self.db.get_recent_ids(days=7)
        if known_ids:
            before = len(papers)
            papers = [p for p in papers if p["arxiv_id"] not in known_ids]
            deduped = before - len(papers)
            if deduped > 0:
                print(f"  🔄 去重: 跳过 {deduped} 篇已入库论文，剩余 {len(papers)} 篇\n")

        if not papers:
            print("  ✅ 所有论文已入库，无新论文")
            return {"status": "no_new_papers", "papers": [], "relevant": [], "summaries": {}}

        # Step 2: 优先尝试 GPT 筛选（失败自动降级）
        print("🤖 Step 2/6: 论文筛选...")
        if getattr(s, "react_mode", False):
            print("  使用 ReAct Agent 筛选...")
            relevant = self._react_filter_relevant(papers, s.research_interests or "")
        elif s.research_interests:
            print("  使用 GPT 智能筛选...")
            relevant = self._filter_relevant(papers, s.research_interests)
        else:
            print("  未设置研究兴趣，使用关键词预筛选")
            relevant = self._keyword_prefilter(papers)
        print(f"  ✅ 筛选出 {len(relevant)} 篇\n")

        if not relevant:
            print("  ⚠️ 未筛选出相关论文")
            self._persist_run(
                papers=papers,
                top_papers=[],
                adapted_weights=adapted_weights,
                known_ids=known_ids,
                strategy_note="no_relevant",
            )
            return {
                "status": "no_relevant",
                "papers": papers,
                "relevant": [],
                "summaries": {},
            }

        # Step 3: Semantic Scholar 批量查（一次请求 + 缓存）
        if relevant:
            print("📡 Step 3/6: Semantic Scholar 批量补充...")
            self.s2.enrich_papers(relevant)
            print()

        # Step 4: 评分排序 → 截取 Top N → 只对 Top N 查 Crossref
        if relevant:
            print("📊 Step 4/6: 评分排序...")
            self.scorer.rank_papers(relevant)
            self._print_ranking(relevant)

        react_plan = {}
        if getattr(s, "react_mode", False):
            print("🧭 Step 4.5/6: ReAct 后续动作决策...")
            react_plan = self._react_plan_followups(relevant, s.top_n)
            top_papers = self._select_papers_by_id(
                relevant,
                react_plan.get("final_ids"),
                default_limit=s.top_n,
            )
        else:
            top_papers = relevant[:s.top_n]

        crossref_targets = self._select_papers_by_id(
            top_papers,
            react_plan.get("crossref_ids"),
            default_limit=len(top_papers),
        )
        deep_dive_targets = self._select_papers_by_id(
            top_papers,
            react_plan.get("deep_dive_ids"),
            default_limit=0,
        )
        deep_dive_ids = {paper["arxiv_id"] for paper in deep_dive_targets}
        crossref_ids = {paper["arxiv_id"] for paper in crossref_targets}
        for paper in top_papers:
            paper["react_deep_dive"] = paper["arxiv_id"] in deep_dive_ids
            paper["react_crossref_selected"] = paper["arxiv_id"] in crossref_ids

        # Crossref 并行查询（v3: ThreadPoolExecutor）
        if crossref_targets:
            print(f"📖 Crossref 并行验证 {len(crossref_targets)} 篇...")
            self.cr.enrich_papers(crossref_targets, max_workers=3)
            # Crossref 数据回来后重新评分一次
            self.scorer.rank_papers(top_papers)
            print()

        # Step 5: 摘要（v3: oneshot + 并行）
        summaries = {}
        deep_dive_notes = {}
        if top_papers:
            n = len(top_papers)
            if self.llm:
                self.llm.reset_circuit()
            print(f"🧠 Step 5/6: 智能摘要（{n} 篇，并行模式）")
            summaries = self.summarizer.summarize_batch(
                top_papers, delay=0.3, max_workers=3,
            )
            if not summaries:
                print(f"  ⚠️  LLM 摘要全部失败，降级规则摘要")
                summaries = self._fallback_summaries(top_papers)
            print(f"  ✅ 生成 {len(summaries)}/{n} 篇摘要\n")

            if deep_dive_targets:
                print(f"🔎 Step 5.5/6: ReAct 深入分析（{len(deep_dive_targets)} 篇）")
                deep_dive_notes = self._generate_deep_dive_notes(deep_dive_targets)
                print(f"  ✅ 生成 {len(deep_dive_notes)}/{len(deep_dive_targets)} 篇深入分析\n")

        # Step 6: 入库 + 决策日志
        self._persist_run(
            papers=papers,
            top_papers=top_papers,
            adapted_weights=adapted_weights,
            known_ids=known_ids,
            strategy_note=(
                f"ok;crossref={len(crossref_targets)};deep={len(deep_dive_targets)}"
            ),
        )

        return {
            "status": "ok",
            "papers": papers,
            "relevant": top_papers,
            "summaries": summaries,
            "deep_dive_notes": deep_dive_notes,
            "react_plan": react_plan,
        }

    def _persist_run(self, papers: List[Dict], top_papers: List[Dict],
                     adapted_weights: dict, known_ids: set,
                     strategy_note: str = ""):
        print("💾 Step 6/6: 保存到数据库...")
        new_count = sum(1 for p in papers if self.db.insert_paper(p))
        print(f"  ✅ 新增 {new_count} 篇\n")

        avg_score = (
            sum(p.get("quality_score", 0) for p in top_papers) / len(top_papers)
            if top_papers else 0
        )
        self.db.log_decision(
            run_date=datetime.now().strftime("%Y-%m-%d"),
            total_fetched=len(papers),
            total_recommended=len(top_papers),
            avg_score=round(avg_score, 1),
            strategy_notes=(
                f"{strategy_note};deduped={len(known_ids)},"
                f"adapted={adapted_weights != self._default_weights},"
                f"react={getattr(self.settings, 'react_mode', False)}"
            ),
            scorer_weights=json.dumps(adapted_weights),
        )

        cleaned = self._cache.cleanup()
        if cleaned:
            print(f"  🗑️ 清理 {cleaned} 条过期缓存")

    # ------------------------------------------------------------------
    # 筛选方法
    # ------------------------------------------------------------------

    def _filter_relevant(self, papers: List[Dict],
                         research_interests: str,
                         top_k: int = 10) -> List[Dict]:
        """GPT 智能筛选"""
        if not self.llm or not research_interests.strip():
            return self._keyword_prefilter(papers, top_k)

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
            id_pattern = re.compile(r"(\d{4}\.\d{4,5})(v\d+)?")
            relevant_ids = []
            for line in response.strip().split("\n"):
                line = line.strip()
                m = id_pattern.search(line)
                if m:
                    # 统一用无版本号形式，兼容 2602.12345 / 2602.12345v1
                    relevant_ids.append(m.group(1))

            id_to_paper = {}
            for p in papers:
                pid = p["arxiv_id"].strip()
                id_to_paper[pid] = p
                base_id = re.sub(r"v\d+$", "", pid)
                id_to_paper.setdefault(base_id, p)
            result = [id_to_paper[aid] for aid in relevant_ids if aid in id_to_paper]
            if result:
                return result[:top_k]
        except Exception as e:
            print(f"  ⚠️  GPT 筛选失败: {e}")

        # GPT 失败时降级到关键词预筛
        print("  ⚠️  降级到关键词预筛选")
        return self._keyword_prefilter(papers, top_k)

    def _react_filter_relevant(self, papers: List[Dict],
                               research_interests: str,
                               top_k: int = 10) -> List[Dict]:
        """ReAct Agent 选择相关论文；失败时回退到普通 GPT/关键词筛选。"""
        if not self.llm:
            print("  ⚠️  未配置 OpenAI，ReAct 模式回退到关键词预筛")
            return self._keyword_prefilter(papers, top_k)

        paper_lookup = {p["arxiv_id"]: p for p in papers}
        registry = ToolRegistry()
        registry.register(Tool(
            name="list_candidate_papers",
            description="列出候选论文的精简信息。",
            parameters={
                "type": "object",
                "properties": {
                    "limit": {"type": "integer", "default": 30},
                },
            },
            function=lambda limit=30: [
                {
                    "arxiv_id": p["arxiv_id"],
                    "title": p["title"],
                    "summary_preview": p["summary"][:220],
                    "categories": p.get("categories", []),
                }
                for p in papers[:limit]
            ],
        ))
        registry.register(Tool(
            name="get_candidate_detail",
            description="获取某篇候选论文的完整标题、摘要和作者信息。",
            parameters={
                "type": "object",
                "properties": {
                    "arxiv_id": {"type": "string"},
                },
                "required": ["arxiv_id"],
            },
            function=lambda arxiv_id: paper_lookup.get(arxiv_id, {}),
        ))

        agent = ReactAgent(self.llm, registry, max_steps=6)
        task = (
            f"我的研究兴趣是：{research_interests or '未提供'}。"
            f"请从候选论文中选出最相关的 {top_k} 篇。"
            "先使用工具查看候选，再输出最终结果。"
            "最终输出必须包含一行 `SELECTED_IDS:`，后面接逗号分隔的 arXiv ID。"
        )

        try:
            result = agent.run(task)
            content = result.get("result", "")
            selected_ids = self._parse_react_id_line(
                content,
                label="SELECTED_IDS",
                allowed_ids=set(paper_lookup),
                max_items=top_k,
            )
            if not selected_ids:
                raise ValueError("ReAct 输出中缺少 SELECTED_IDS")

            if selected_ids:
                return [paper_lookup[paper_id] for paper_id in selected_ids[:top_k]]
        except Exception as e:
            print(f"  ⚠️  ReAct 筛选失败: {e}")

        print("  ⚠️  ReAct 回退到普通 GPT 筛选")
        return self._filter_relevant(papers, research_interests, top_k)

    def _react_plan_followups(self, ranked_papers: List[Dict],
                              top_k: int = 5) -> Dict[str, List[str]]:
        """让 ReAct 决定最终推送、Crossref 校验和深入分析对象。"""
        if not self.llm or not ranked_papers:
            return {}

        paper_lookup = {paper["arxiv_id"]: paper for paper in ranked_papers}
        registry = ToolRegistry()
        registry.register(Tool(
            name="list_ranked_papers",
            description="列出已完成初步评分的论文摘要信息。",
            parameters={
                "type": "object",
                "properties": {
                    "limit": {"type": "integer", "default": 10},
                },
            },
            function=lambda limit=10: [
                {
                    "arxiv_id": paper["arxiv_id"],
                    "title": paper["title"],
                    "quality_score": paper.get("quality_score", 0),
                    "citations": paper.get("s2_citation_count", 0),
                    "venue": paper.get("s2_venue", ""),
                    "authors": [
                        author.get("name", "")
                        for author in paper.get("s2_authors", [])[:3]
                    ] or paper.get("authors", [])[:3],
                    "summary_preview": paper.get("summary", "")[:220],
                }
                for paper in ranked_papers[:limit]
            ],
        ))
        registry.register(Tool(
            name="get_ranked_paper_detail",
            description="获取某篇已评分论文的完整信息，便于决定是否做 Crossref 或深入分析。",
            parameters={
                "type": "object",
                "properties": {
                    "arxiv_id": {"type": "string"},
                },
                "required": ["arxiv_id"],
            },
            function=lambda arxiv_id: paper_lookup.get(arxiv_id, {}),
        ))

        agent = ReactAgent(self.llm, registry, max_steps=8)
        task = (
            "你已经拿到一批论文的初步评分结果。"
            f"请决定最终推送的 {top_k} 篇论文、哪些需要调用 Crossref 验证正式发表状态，"
            "以及哪些最值得做深入分析。"
            "先使用工具查看候选，再给出最终结论。"
            "最终输出必须包含以下 3 行：\n"
            f"FINAL_IDS: <逗号分隔的 arXiv ID，最多 {top_k} 个>\n"
            "CROSSREF_IDS: <FINAL_IDS 的子集，可为空>\n"
            "DEEP_DIVE_IDS: <FINAL_IDS 的子集，最多 2 个，可为空>\n"
            "优先策略：高分、高引用、作者机构强、题目和摘要与研究兴趣高度相关的论文优先；"
            "对于已明显是预印本且收益不高的论文，可以不做 Crossref。"
        )

        try:
            result = agent.run(task)
            content = result.get("result", "")
            allowed_ids = set(paper_lookup)
            final_ids = self._parse_react_id_line(
                content, "FINAL_IDS", allowed_ids, top_k,
            )
            if not final_ids:
                return {}

            final_set = set(final_ids)
            crossref_ids = self._parse_react_id_line(
                content, "CROSSREF_IDS", final_set, len(final_ids),
            )
            deep_dive_ids = self._parse_react_id_line(
                content, "DEEP_DIVE_IDS", final_set, 2,
            )
            return {
                "final_ids": final_ids,
                "crossref_ids": crossref_ids,
                "deep_dive_ids": deep_dive_ids,
            }
        except Exception as e:
            print(f"  ⚠️  ReAct 后续动作决策失败: {e}")
            return {}

    @staticmethod
    def _parse_react_id_line(content: str, label: str,
                             allowed_ids: set,
                             max_items: int) -> List[str]:
        """解析 ReAct 输出中的 ID 列表行。"""
        if not content:
            return []
        match = re.search(rf"{label}\s*:\s*([^\n]*)", content)
        if not match:
            return []

        selected_ids = []
        raw = match.group(1).strip()
        if not raw or raw.upper() in {"NONE", "N/A", "EMPTY"}:
            return []

        for token in re.split(r"[,\s]+", raw):
            if token and token in allowed_ids and token not in selected_ids:
                selected_ids.append(token)
            if len(selected_ids) >= max_items:
                break
        return selected_ids

    @staticmethod
    def _select_papers_by_id(papers: List[Dict], selected_ids: List[str],
                             default_limit: int) -> List[Dict]:
        """按 ID 和给定顺序选取论文；若为空则使用默认前 N 篇。"""
        if not selected_ids:
            return papers[:default_limit] if default_limit > 0 else []

        lookup = {paper["arxiv_id"]: paper for paper in papers}
        result = []
        for paper_id in selected_ids:
            paper = lookup.get(paper_id)
            if paper and paper not in result:
                result.append(paper)
        return result

    def _generate_deep_dive_notes(self, papers: List[Dict]) -> Dict[str, str]:
        """为 ReAct 选中的重点论文生成简短深入分析。"""
        results = {}
        for paper in papers:
            arxiv_id = paper.get("arxiv_id", "")
            title = paper.get("title", "")
            abstract = paper.get("summary", "")
            if not arxiv_id or not abstract:
                continue

            if not self.llm:
                key = extract_key_sentences(abstract, max_sentences=2)
                results[arxiv_id] = f"• 值得关注：{title}\n• 阅读重点：{key[:180]}"
                continue

            prompt = (
                "请对下面这篇论文做简短深入分析，输出 4 条中文要点。\n"
                "规则：\n"
                "1. 每条以 • 开头\n"
                "2. 每条不超过 28 个中文字\n"
                "3. 四条依次说明：为什么值得读、核心创新、最该关注的结果、可能的限制\n"
                "4. 只输出 4 条要点，不要额外解释\n\n"
                f"论文标题：{title}\n\n"
                f"摘要：{abstract}"
            )
            try:
                results[arxiv_id] = self.llm.generate(
                    prompt,
                    system="你是严谨的学术研究分析助手。",
                    temperature=0.4,
                    max_tokens=350,
                ).strip()
            except Exception:
                key = extract_key_sentences(abstract, max_sentences=2)
                results[arxiv_id] = f"• 值得关注：{title}\n• 阅读重点：{key[:180]}"
        return results

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
        deep_dive_notes = result.get("deep_dive_notes", {})

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

            if paper["arxiv_id"] in deep_dive_notes:
                report.append("")
                report.append("**ReAct 深入分析**:")
                report.append(deep_dive_notes[paper["arxiv_id"]])

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
        self._cache.close()
