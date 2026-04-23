"""
工具注册表 — 供 ReAct Agent 使用

每个工具包含:
    name:        工具名（给 LLM function calling 用）
    description: 功能描述
    parameters:  JSON Schema 参数描述
    function:    实际执行函数
"""

import json
from typing import List, Dict, Callable, Any


class Tool:
    """单个工具定义"""

    def __init__(self, name: str, description: str,
                 parameters: dict, function: Callable):
        self.name = name
        self.description = description
        self.parameters = parameters
        self.function = function

    def to_openai_schema(self) -> dict:
        """转换为 OpenAI function calling 格式"""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            }
        }

    def execute(self, **kwargs) -> Any:
        return self.function(**kwargs)


class ToolRegistry:
    """工具注册中心"""

    def __init__(self):
        self.tools: Dict[str, Tool] = {}

    def register(self, tool: Tool):
        self.tools[tool.name] = tool

    def get(self, name: str) -> Tool:
        return self.tools.get(name)

    def get_openai_tools(self) -> List[dict]:
        return [t.to_openai_schema() for t in self.tools.values()]

    def list_names(self) -> List[str]:
        return list(self.tools.keys())


# ---------------------------------------------------------------------------
# 预定义工具 — 连接到具体的 Agent 实例
# ---------------------------------------------------------------------------

def build_tool_registry(arxiv_agent, s2_client, cr_client,
                        scorer, summarizer, db) -> ToolRegistry:
    """
    根据已有的 agent 实例构建工具注册表

    每个工具封装一个原子操作，供 ReAct Agent 调用。
    """
    registry = ToolRegistry()

    # 1. 搜索 arXiv 论文
    registry.register(Tool(
        name="search_arxiv",
        description="搜索最新 arXiv 论文。返回论文列表（标题、ID、摘要、作者）。",
        parameters={
            "type": "object",
            "properties": {
                "days": {
                    "type": "integer",
                    "description": "搜索最近 N 天的论文",
                    "default": 2,
                },
                "max_results": {
                    "type": "integer",
                    "description": "最多返回论文数",
                    "default": 200,
                },
            },
        },
        function=lambda days=2, max_results=200: arxiv_agent.fetch_recent_papers(
            days=days, max_results=max_results
        ),
    ))

    # 2. 批量获取引用信息
    registry.register(Tool(
        name="get_citations",
        description="从 Semantic Scholar 批量获取论文的引用数、作者机构、发表会议等信息。输入 arXiv ID 列表。",
        parameters={
            "type": "object",
            "properties": {
                "arxiv_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "arXiv ID 列表（如 ['2402.12345', '2402.12346']）",
                },
            },
            "required": ["arxiv_ids"],
        },
        function=lambda arxiv_ids: s2_client.batch_get_papers(arxiv_ids),
    ))

    # 3. 检查发表状态
    registry.register(Tool(
        name="check_published",
        description="通过 Crossref 检查一篇论文是否已在期刊/会议正式发表。输入论文标题。",
        parameters={
            "type": "object",
            "properties": {
                "title": {
                    "type": "string",
                    "description": "论文标题",
                },
            },
            "required": ["title"],
        },
        function=lambda title: cr_client.check_published(title),
    ))

    # 4. 评分排序
    registry.register(Tool(
        name="score_and_rank",
        description="对论文列表进行多维度评分（引用、机构、会议、新鲜度、关键词）并按分数排序。",
        parameters={
            "type": "object",
            "properties": {
                "paper_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "要评分的论文 arXiv ID 列表",
                },
            },
            "required": ["paper_ids"],
        },
        function=lambda paper_ids: _score_papers_by_ids(scorer, paper_ids),
    ))

    # 5. 生成摘要
    registry.register(Tool(
        name="summarize_paper",
        description="为一篇论文生成三段式中文摘要（问题→方法→结果）。",
        parameters={
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "论文标题"},
                "abstract": {"type": "string", "description": "论文摘要"},
            },
            "required": ["title", "abstract"],
        },
        function=lambda title, abstract: summarizer.summarize({
            "title": title, "summary": abstract,
        }),
    ))

    # 6. 查询数据库已有论文
    registry.register(Tool(
        name="check_known_papers",
        description="查询数据库中已经收录的论文 ID 列表，用于去重。",
        parameters={
            "type": "object",
            "properties": {
                "days": {
                    "type": "integer",
                    "description": "查最近 N 天的已知论文",
                    "default": 7,
                },
            },
        },
        function=lambda days=7: db.get_recent_ids(days=days),
    ))

    # 7. 获取论文详情
    registry.register(Tool(
        name="get_paper_detail",
        description="从数据库获取一篇已收录论文的完整信息。",
        parameters={
            "type": "object",
            "properties": {
                "arxiv_id": {"type": "string", "description": "arXiv ID"},
            },
            "required": ["arxiv_id"],
        },
        function=lambda arxiv_id: db.get_paper_by_arxiv_id(arxiv_id),
    ))

    return registry


def _score_papers_by_ids(scorer, paper_ids):
    """辅助函数：按 ID 列表返回评分结果（简化版）"""
    return {"message": f"请直接使用完整论文数据调用评分，共 {len(paper_ids)} 篇待评分"}
