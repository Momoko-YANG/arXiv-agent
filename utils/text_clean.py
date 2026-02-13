"""
文本清洗工具
"""

import re


def clean_title(title: str) -> str:
    """清理论文标题（去除多余空白和换行）"""
    return re.sub(r'\s+', ' ', title).strip()


def clean_abstract(abstract: str) -> str:
    """清理摘要文本"""
    text = re.sub(r'\s+', ' ', abstract).strip()
    # 去除 LaTeX 命令残留
    text = re.sub(r'\\[a-zA-Z]+\{[^}]*\}', '', text)
    return text


def truncate(text: str, max_len: int = 200, suffix: str = "...") -> str:
    """安全截断文本"""
    if len(text) <= max_len:
        return text
    return text[:max_len - len(suffix)] + suffix
