"""
全局配置 — 从 .env 和 config/sources.yaml 加载
"""

import os
from dataclasses import dataclass, field
from typing import List


# ---------------------------------------------------------------------------
# .env 加载（不依赖 python-dotenv）
# ---------------------------------------------------------------------------

def load_dotenv(path: str = None):
    """从 .env 文件加载环境变量（已有的不覆盖）"""
    if path is None:
        # 项目根目录下的 .env
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        path = os.path.join(root, '.env')
    if not os.path.exists(path):
        return
    with open(path, encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#') or '=' not in line:
                continue
            key, _, value = line.partition('=')
            key, value = key.strip(), value.strip()
            if key and key not in os.environ:
                os.environ[key] = value


# ---------------------------------------------------------------------------
# Settings 数据类
# ---------------------------------------------------------------------------

@dataclass
class Settings:
    """项目配置（集中管理所有参数）"""

    # ---- arXiv ----
    categories: List[str] = field(default_factory=lambda: [
        "cs.AI", "cs.LG", "cs.CV", "cs.CL",
    ])

    # ---- 抓取 ----
    days: int = 2          # 查最近 2 天（实际查询 +1 天缓冲 = 3 天覆盖周末）
    max_results: int = 200
    top_n: int = 5
    schedule_time: str = "09:00"

    # ---- 研究兴趣（GPT 筛选用）----
    research_interests: str = ""

    # ---- 加分关键词 ----
    bonus_keywords: List[str] = field(default_factory=lambda: [
        "LLM", "large language model",
        "GPT", "reasoning", "chain-of-thought",
        "multimodal", "vision-language",
        "agent", "tool use",
        "quantization", "efficient",
        "diffusion", "transformer",
    ])

    # ---- API Keys（从环境变量读取）----
    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""
    s2_api_key: str = ""
    crossref_mailto: str = ""

    # ---- 数据库 ----
    db_path: str = "data/processed/arxiv_papers.db"

    def __post_init__(self):
        """从环境变量填充 API Keys"""
        self.openai_api_key = self.openai_api_key or os.getenv("OPENAI_API_KEY", "")
        self.openai_model = self.openai_model or os.getenv("OPENAI_MODEL", "gpt-4o-mini")
        self.telegram_bot_token = self.telegram_bot_token or os.getenv("TELEGRAM_BOT_TOKEN", "")
        self.telegram_chat_id = self.telegram_chat_id or os.getenv("TELEGRAM_CHAT_ID", "")
        self.s2_api_key = self.s2_api_key or os.getenv("S2_API_KEY", "")
        self.crossref_mailto = self.crossref_mailto or os.getenv("CROSSREF_MAILTO", "")


def load_settings(**overrides) -> Settings:
    """
    加载配置：.env → 默认值 → overrides

    用法:
        settings = load_settings(top_n=10, days=3)
    """
    load_dotenv()
    return Settings(**overrides)
