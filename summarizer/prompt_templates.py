"""
Summarizer Prompt 模板 — 集中管理，方便版本迭代
"""

# ---------------------------------------------------------------------------
# Stage 2: 结构化信息抽取
# ---------------------------------------------------------------------------

EXTRACT_SYSTEM = (
    "You are a precise academic information extractor. "
    "Output ONLY the requested structured fields, nothing else."
)

EXTRACT_PROMPT = """\
From the following key sentences of a research paper, extract exactly 3 fields.
Write each as ONE concise sentence (max 20 words). Be specific, not vague.

KEY SENTENCES:
{key_text}

PAPER TITLE (for context):
{title}

Output format (use exactly these labels):
- Problem: <what gap/challenge the paper addresses>
- Method: <core technical approach or framework>
- Result: <main quantitative or qualitative outcome>"""


# ---------------------------------------------------------------------------
# Stage 3: 语义压缩 — 中文
# ---------------------------------------------------------------------------

COMPRESS_SYSTEM_ZH = "你是学术论文压缩专家。你必须用自己的语言重写，严禁照搬原文措辞。"

COMPRESS_PROMPT_ZH = """\
将以下论文结构化信息改写为 3 条中文要点。

规则（必须全部遵守）：
1. 每条以 • 开头
2. 每条不超过 25 个中文字
3. 第一条说「解决什么问题」
4. 第二条说「用什么方法」
5. 第三条说「达到什么效果」
6. 禁止直接翻译原句，必须用你自己的概括语言
7. 使用中文学术术语

结构化信息：
{structured}

论文标题：
{title}"""


# ---------------------------------------------------------------------------
# Stage 3: 语义压缩 — 英文
# ---------------------------------------------------------------------------

COMPRESS_SYSTEM_EN = (
    "You are an academic paper compression expert. "
    "Rephrase everything in your own words — never copy original phrasing."
)

COMPRESS_PROMPT_EN = """\
Rewrite the following structured paper info into 3 concise bullet points.

Rules (must follow ALL):
1. Each bullet starts with •
2. Each bullet max 15 words
3. Bullet 1: what problem is addressed
4. Bullet 2: what method/approach is used
5. Bullet 3: what outcome/result is achieved
6. Do NOT reuse original phrases — rephrase everything
7. Be specific, not generic

Structured info:
{structured}

Paper title:
{title}"""


# ---------------------------------------------------------------------------
# GPT 筛选 prompt
# ---------------------------------------------------------------------------

FILTER_SYSTEM = "你是一个学术论文分析专家，擅长根据研究方向筛选相关论文。"

FILTER_PROMPT = """\
我的研究兴趣是：{research_interests}

以下是最近的 arXiv 论文列表：

{papers_text}

请分析哪些论文与我的研究兴趣最相关。

要求：
1. 返回最相关的 {top_k} 篇论文的 ID（格式如 2402.12345）
2. 每个 ID 占一行
3. 按相关性从高到低排序
4. 只返回 ID 列表，不要其他解释

格式示例：
2402.12345
2402.12346"""
