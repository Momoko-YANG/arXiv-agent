"""
三段式论文摘要器 — 抽取 → 结构化 → 压缩重写
当 LLM 不可用时自动降级为规则摘要
"""

import re
from typing import Dict, List

from .prompt_templates import (
    EXTRACT_SYSTEM, EXTRACT_PROMPT,
    COMPRESS_SYSTEM_ZH, COMPRESS_PROMPT_ZH,
    COMPRESS_SYSTEM_EN, COMPRESS_PROMPT_EN,
)


# ---------------------------------------------------------------------------
# Stage 1: 关键句抽取（规则层，0 token）
# ---------------------------------------------------------------------------

_METHOD_KW = {
    "propose", "present", "introduce", "develop", "design",
    "method", "approach", "framework", "architecture", "model",
    "algorithm", "technique", "mechanism", "strategy", "pipeline",
    "leverage", "employ", "utilize", "formulate", "novel",
}

_RESULT_KW = {
    "experiment", "result", "evaluation", "benchmark", "dataset",
    "outperform", "improve", "achieve", "surpass", "state-of-the-art",
    "sota", "accuracy", "performance", "f1", "bleu", "rouge",
    "demonstrate", "show", "significantly", "superior", "comparable",
    "reduce", "increase", "gain",
}

_PROBLEM_KW = {
    "challenge", "problem", "limitation", "issue", "gap",
    "lack", "suffer", "difficult", "bottleneck", "drawback",
    "however", "although", "despite", "remain", "existing",
    "struggle", "fail", "inadequate",
}

_ALL_KW = _METHOD_KW | _RESULT_KW | _PROBLEM_KW


def extract_key_sentences(abstract: str, max_sentences: int = 6) -> str:
    """规则层关键句抽取：关键词匹配 + 位置加权"""
    text = abstract.replace("et al.", "et al").replace("i.e.", "ie").replace("e.g.", "eg")
    sentences = re.split(r'(?<=[.!?])\s+', text.strip())

    if len(sentences) <= max_sentences:
        return abstract

    scored = []
    for i, sent in enumerate(sentences):
        lower = sent.lower()
        hits = sum(1 for kw in _ALL_KW if kw in lower)
        if i == 0:
            hits += 2
        elif i == len(sentences) - 1:
            hits += 1
        scored.append((i, hits, sent))

    scored.sort(key=lambda x: x[1], reverse=True)
    top = sorted(scored[:max_sentences], key=lambda x: x[0])

    return " ".join(item[2] for item in top) or abstract


# ---------------------------------------------------------------------------
# PaperSummarizer 主类
# ---------------------------------------------------------------------------

class PaperSummarizer:
    """
    三段式论文摘要器

    Pipeline:
        abstract → extract_key_sentences  [规则层，0 token]
                 → structured_extract     [LLM：提取 problem/method/result]
                 → compress_summary       [LLM：压缩重写为 3 个要点]

    当 LLM 调用失败时自动降级为规则摘要
    """

    def __init__(self, llm_client=None, language: str = "zh"):
        self.llm = llm_client
        self.language = language
        self._llm_failures = 0  # 连续失败计数

    def structured_extract(self, key_text: str, title: str) -> str:
        """Stage 2: 结构化信息抽取"""
        prompt = EXTRACT_PROMPT.format(key_text=key_text, title=title)
        try:
            result = self.llm.chat(prompt, system=EXTRACT_SYSTEM, temperature=0.2).strip()
            self._llm_failures = 0
            return result
        except Exception as e:
            self._llm_failures += 1
            return f"- Problem: extraction failed\n- Method: {title}\n- Result: see paper ({e})"

    def compress_summary(self, structured_text: str, title: str) -> str:
        """Stage 3: 语义压缩重写"""
        if self.language == "zh":
            prompt = COMPRESS_PROMPT_ZH.format(structured=structured_text, title=title)
            system = COMPRESS_SYSTEM_ZH
        else:
            prompt = COMPRESS_PROMPT_EN.format(structured=structured_text, title=title)
            system = COMPRESS_SYSTEM_EN
        try:
            result = self.llm.chat(prompt, system=system, temperature=0.6).strip()
            self._llm_failures = 0
            return result
        except Exception as e:
            self._llm_failures += 1
            return f"• 摘要压缩失败: {e}"

    def _rule_based_summary(self, paper: Dict) -> str:
        """纯规则降级摘要（0 token，即时完成）"""
        abstract = paper.get("summary", "")
        if not abstract:
            return "• 无摘要信息"
        key = extract_key_sentences(abstract, max_sentences=3)
        if len(key) > 250:
            key = key[:247] + "..."
        return f"• {key}"

    def summarize(self, paper: Dict) -> str:
        """完整三段式摘要，LLM 失败自动降级"""
        title = paper.get("title", "")
        abstract = paper.get("summary", "")
        if not abstract:
            return "• 无摘要信息"

        # 连续失败较多时再全局降级，避免过早放弃 LLM
        if self._llm_failures >= 6:
            return self._rule_based_summary(paper)

        key_text = extract_key_sentences(abstract)
        structured = self.structured_extract(key_text, title)

        # 如果结构化提取失败了，直接用规则摘要
        if "extraction failed" in structured:
            return self._rule_based_summary(paper)

        result = self.compress_summary(structured, title)
        if "摘要压缩失败" in result:
            return self._rule_based_summary(paper)

        return result

    def summarize_batch(self, papers: List[Dict],
                        delay: float = 0.5) -> Dict[str, str]:
        """
        批量摘要

        delay: 每篇之间的等待（秒），默认 0.5s（比之前的 1.0s 快一倍）
        """
        import time

        results = {}
        total = len(papers)

        for i, paper in enumerate(papers, 1):
            arxiv_id = paper.get("arxiv_id", f"unknown_{i}")
            title_short = paper.get('title', '')[:50]

            # 如果 LLM 连续失败很多次，后续走规则摘要
            if self._llm_failures >= 6:
                print(f"  📝 [{i}/{total}] 规则摘要(LLM 断连): {title_short}...")
                results[arxiv_id] = self._rule_based_summary(paper)
                continue

            print(f"  🧠 [{i}/{total}] 三段式摘要: {title_short}...")

            summary = self.summarize(paper)
            results[arxiv_id] = summary

            first_line = summary.split("\n")[0]
            if "摘要压缩失败" in summary or "extraction failed" in summary:
                print(f"       ⚠️  降级为规则摘要")
            else:
                print(f"       → {first_line[:60]}")

            if i < total and delay > 0 and self._llm_failures < 6:
                time.sleep(delay)

        return results
