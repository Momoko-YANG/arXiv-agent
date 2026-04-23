"""
三段式论文摘要器 — 抽取 → 结构化 → 压缩重写
当 LLM 不可用时自动降级为规则摘要

v3 新增:
  - 单次调用模式（oneshot）— 1 次 LLM 调用替代 2 次，省 50% token
  - ThreadPoolExecutor 并行摘要 — 5 篇从 ~25s 降到 ~8s
"""

import re
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, List

from .prompt_templates import (
    EXTRACT_SYSTEM, EXTRACT_PROMPT,
    COMPRESS_SYSTEM_ZH, COMPRESS_PROMPT_ZH,
    COMPRESS_SYSTEM_EN, COMPRESS_PROMPT_EN,
    ONESHOT_SYSTEM_ZH, ONESHOT_PROMPT_ZH,
    ONESHOT_SYSTEM_EN, ONESHOT_PROMPT_EN,
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

    def __init__(self, llm_client=None, language: str = "zh",
                 mode: str = "oneshot"):
        """
        Args:
            llm_client: LLM 客户端
            language:   "zh" / "en"
            mode:       "oneshot" (1 次 LLM) / "threestage" (2 次 LLM，更精细)
        """
        self.llm = llm_client
        self.language = language
        self.mode = mode
        self._llm_failures = 0
        self._lock = threading.RLock()

    def _failure_count(self) -> int:
        with self._lock:
            return self._llm_failures

    def _reset_failures(self):
        with self._lock:
            self._llm_failures = 0

    def _increment_failures(self):
        with self._lock:
            self._llm_failures += 1

    def structured_extract(self, key_text: str, title: str) -> str:
        """Stage 2: 结构化信息抽取"""
        prompt = EXTRACT_PROMPT.format(key_text=key_text, title=title)
        try:
            result = self.llm.generate(prompt, system=EXTRACT_SYSTEM, temperature=0.2).strip()
            self._reset_failures()
            return result
        except Exception as e:
            self._increment_failures()
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
            result = self.llm.generate(prompt, system=system, temperature=0.6).strip()
            self._reset_failures()
            return result
        except Exception as e:
            self._increment_failures()
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
        """完整摘要，LLM 失败自动降级"""
        title = paper.get("title", "")
        abstract = paper.get("summary", "")
        if not abstract:
            return "• 无摘要信息"

        if self._failure_count() >= 6:
            return self._rule_based_summary(paper)

        # v3: 优先使用 oneshot 模式（1 次调用）
        if self.mode == "oneshot":
            return self._summarize_oneshot(title, abstract)

        # threestage 模式（2 次调用，更精细）
        key_text = extract_key_sentences(abstract)
        structured = self.structured_extract(key_text, title)

        if "extraction failed" in structured:
            return self._rule_based_summary(paper)

        result = self.compress_summary(structured, title)
        if "摘要压缩失败" in result:
            return self._rule_based_summary(paper)

        return result

    def _summarize_oneshot(self, title: str, abstract: str) -> str:
        """
        单次 LLM 调用摘要（v3 新增）

        直接从原文生成 3 个要点，省去 extract → compress 两步。
        Token 消耗减少 ~50%，延迟减少 ~50%。
        """
        if self.language == "zh":
            prompt = ONESHOT_PROMPT_ZH.format(title=title, abstract=abstract)
            system = ONESHOT_SYSTEM_ZH
        else:
            prompt = ONESHOT_PROMPT_EN.format(title=title, abstract=abstract)
            system = ONESHOT_SYSTEM_EN

        try:
            result = self.llm.generate(
                prompt, system=system, temperature=0.5, max_tokens=300,
            ).strip()
            self._reset_failures()
            return result
        except Exception as e:
            self._increment_failures()
            return self._rule_based_summary(
                {"title": title, "summary": abstract}
            )

    def summarize_batch(self, papers: List[Dict],
                        delay: float = 0.5,
                        max_workers: int = 3) -> Dict[str, str]:
        """
        批量摘要（v3: 并行执行）

        v2 串行: 5 篇 × 2 次 LLM = 10 次调用 ≈ 25s
        v3 并行: 5 篇 × 1 次 LLM = 5 次调用，3 workers ≈ 8s
        """
        import time

        results = {}
        total = len(papers)

        def _summarize_one(i_paper):
            i, paper = i_paper
            arxiv_id = paper.get("arxiv_id", f"unknown_{i}")
            title_short = paper.get('title', '')[:50]

            if self._failure_count() >= 6:
                print(f"  📝 [{i}/{total}] 规则摘要(LLM 断连): {title_short}...")
                return arxiv_id, self._rule_based_summary(paper)

            print(f"  🧠 [{i}/{total}] 摘要: {title_short}...")
            summary = self.summarize(paper)

            first_line = summary.split("\n")[0]
            if "摘要压缩失败" in summary or "extraction failed" in summary:
                print(f"       ⚠️  降级为规则摘要")
            else:
                print(f"       → {first_line[:60]}")

            return arxiv_id, summary

        # oneshot 模式可并行（单次调用无依赖）
        if self.mode == "oneshot" and max_workers > 1:
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                futures = {
                    executor.submit(_summarize_one, (i, p)): i
                    for i, p in enumerate(papers, 1)
                }
                for future in as_completed(futures):
                    arxiv_id, summary = future.result()
                    results[arxiv_id] = summary
        else:
            # threestage 模式串行（两次 LLM 调用有依赖）
            for i, paper in enumerate(papers, 1):
                arxiv_id, summary = _summarize_one((i, paper))
                results[arxiv_id] = summary
                if i < total and delay > 0 and self._failure_count() < 6:
                    time.sleep(delay)

        return results
