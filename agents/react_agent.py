"""
ReAct Agent — 工具调用 + 推理循环

替代固定流水线，让 LLM 自主决定下一步操作。
支持降级：当 LLM 不可用时回退到固定流水线。
"""

import json
from typing import Dict, List

from .tools import ToolRegistry
from llm_client import LLMClient


REACT_SYSTEM = """你是一个学术论文研究助手 Agent。你的任务是帮用户找到最相关、最高质量的最新论文。

你可以使用以下工具：

{tools_description}

工作策略：
1. 先搜索最新论文（search_arxiv）
2. 检查数据库避免重复推送（check_known_papers）
3. 获取论文的引用和机构信息（get_citations）
4. 根据信息判断哪些论文最值得关注
5. 为最优秀的论文生成摘要（summarize_paper）

你应该根据中间结果灵活调整策略，例如：
- 如果某篇论文引用量异常高，重点关注
- 如果初始结果太少，可以调整搜索参数
- 如果某个作者的多篇论文都出现，说明是活跃研究方向

每一步先思考（Thought），再决定行动（Action）。观察结果后再规划下一步。
当你收集到足够信息后，输出最终结论。"""


class ReactAgent:
    """ReAct 推理-行动循环 Agent"""

    MAX_STEPS = 15

    def __init__(self, llm: LLMClient, tools: ToolRegistry,
                 max_steps: int = None):
        self.llm = llm
        self.tools = tools
        self.max_steps = max_steps or self.MAX_STEPS
        self.history: List[Dict] = []

    def run(self, task: str) -> Dict:
        """
        执行 ReAct 循环

        Args:
            task: 任务描述（包含用户研究兴趣等）

        Returns:
            {"result": ..., "steps": [...], "tool_calls": [...]}
        """
        tools_desc = "\n".join(
            f"- {t.name}: {t.description}"
            for t in self.tools.tools.values()
        )
        system = REACT_SYSTEM.format(tools_description=tools_desc)

        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": task},
        ]

        steps = []
        tool_calls_log = []

        for step in range(self.max_steps):
            print(f"  🔄 ReAct Step {step + 1}/{self.max_steps}")

            try:
                response = self.llm.generate_with_tools(
                    messages=messages,
                    tools=self.tools.get_openai_tools(),
                )
            except Exception as e:
                print(f"  ❌ LLM 调用失败: {e}")
                break

            # LLM 想要调用工具
            if response.get("tool_calls"):
                for tc in response["tool_calls"]:
                    func_name = tc["function"]["name"]
                    try:
                        func_args = json.loads(tc["function"]["arguments"])
                    except json.JSONDecodeError:
                        func_args = {}

                    print(f"  🔧 调用工具: {func_name}({list(func_args.keys())})")

                    tool = self.tools.get(func_name)
                    if not tool:
                        result = f"错误: 工具 {func_name} 不存在"
                    else:
                        try:
                            result = tool.execute(**func_args)
                            if isinstance(result, (dict, list)):
                                # 截断过长的结果防止 context 溢出
                                result_str = json.dumps(
                                    result, ensure_ascii=False, default=str
                                )
                                if len(result_str) > 8000:
                                    result_str = result_str[:8000] + "...(已截断)"
                                result = result_str
                        except Exception as e:
                            result = f"工具执行失败: {e}"

                    tool_calls_log.append({
                        "step": step + 1,
                        "tool": func_name,
                        "args": func_args,
                        "result_preview": str(result)[:200],
                    })

                    # 添加 assistant 的工具调用消息
                    messages.append({
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [tc],
                    })
                    # 添加工具返回结果
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc["id"],
                        "content": str(result),
                    })
            else:
                # LLM 返回最终文本回复
                content = response.get("content", "")
                steps.append({
                    "step": step + 1, "type": "final", "content": content
                })
                print(f"  ✅ Agent 完成推理（共 {step + 1} 步）")
                return {
                    "result": content,
                    "steps": steps,
                    "tool_calls": tool_calls_log,
                }

            steps.append({
                "step": step + 1,
                "type": "tool_call",
                "tools_called": [
                    tc["function"]["name"]
                    for tc in response.get("tool_calls", [])
                ],
            })

        print(f"  ⚠️ 达到最大步数 {self.max_steps}")
        return {
            "result": "达到最大推理步数，请查看中间步骤获取已收集的信息。",
            "steps": steps,
            "tool_calls": tool_calls_log,
        }
