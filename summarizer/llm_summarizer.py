"""
三段式论文摘要器 — 抽取 → 结构化 → 压缩重写
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
    """
    规则层关键句抽取：关键词匹配 + 位置加权
    """
    text = abstract.replace("et al.", "et al").replace("i.e.", "ie").replace("e.g.", "eg")
    sentences = re.split(r'(?<=[.!?])\s+', text.strip())

    if len(sentences) <= max_sentences:
        return abstract

    scored = []
    for i, sent in enumerate(sentences):
        lower = sent.lower()
        hits = sum(1 for kw in _ALL_KW if kw in lower)
        if i == 0:
            hits += 2  # 首句通常是问题陈述
        elif i == len(sentences) - 1:
            hits += 1  # 尾句通常是总结
        scored.append((i, hits, sent))

    scored.sort(key=lambda x: x[1], reverse=True)
    top = sorted(scored[:max_sentences], key=lambda x: x[0])  # 恢复原文顺序

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
    """

    def __init__(self, llm_client=None, language: str = "zh"):
        """
        Args:
            llm_client: utils.llm_client.OpenAIClient 实例
            language:   输出语言 'zh' 或 'en'
        """
        self.llm = llm_client
        self.language = language

    def structured_extract(self, key_text: str, title: str) -> str:
        """Stage 2: 结构化信息抽取（Problem / Method / Result）"""
        prompt = EXTRACT_PROMPT.format(key_text=key_text, title=title)
        try:
            return self.llm.chat(prompt, system=EXTRACT_SYSTEM, temperature=0.2).strip()
        except Exception as e:
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
            return self.llm.chat(prompt, system=system, temperature=0.6).strip()
        except Exception as e:
            return f"• 摘要压缩失败: {e}"

    def summarize(self, paper: Dict) -> str:
        """完整三段式摘要"""
        title = paper.get("title", "")
        abstract = paper.get("summary", "")
        if not abstract:
            return "• 无摘要信息"

        key_text = extract_key_sentences(abstract)
        structured = self.structured_extract(key_text, title)
        return self.compress_summary(structured, title)

    def summarize_batch(self, papers: List[Dict],
                        delay: float = 1.0) -> Dict[str, str]:
        """
        批量摘要

        Returns:
            {arxiv_id: summary_text}
        """
        import time

        results = {}
        total = len(papers)

        for i, paper in enumerate(papers, 1):
            arxiv_id = paper.get("arxiv_id", f"unknown_{i}")
            print(f"  🧠 [{i}/{total}] 三段式摘要: {paper.get('title', '')[:50]}...")

            summary = self.summarize(paper)
            if summary and not summary.startswith("• 摘要压缩失败"):
                results[arxiv_id] = summary
                first_line = summary.split("\n")[0]
                print(f"       → {first_line}")
            else:
                print(f"       ❌ {summary}")

            if i < total and delay > 0:
                time.sleep(delay)

        return results
