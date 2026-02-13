"""
Telegram 通知器 — 推送日报消息 + 报告文件
"""

import time
import requests
from datetime import datetime
from typing import Dict, List


TELEGRAM_MAX_MSG_LEN = 4096


class TelegramNotifier:
    """Telegram Bot 通知器"""

    def __init__(self, token: str, chat_id: str):
        self.token = token
        self.chat_id = chat_id

    @property
    def configured(self) -> bool:
        return bool(self.token and self.chat_id)

    # ------------------------------------------------------------------
    # 底层 API
    # ------------------------------------------------------------------

    def _request(self, method: str, **kwargs):
        """带重试的 Telegram Bot API 请求"""
        url = f"https://api.telegram.org/bot{self.token}/{method}"
        for attempt in range(3):
            try:
                resp = requests.post(url, timeout=60, **kwargs)
                if resp.status_code == 429:
                    retry_after = resp.json().get("parameters", {}).get("retry_after", 5)
                    print(f"  ⏳ Telegram 限流，等待 {retry_after}s...")
                    time.sleep(retry_after)
                    continue
                resp.raise_for_status()
                return resp.json()
            except requests.RequestException as e:
                if attempt < 2:
                    wait = 2 ** (attempt + 1)
                    print(f"  ⚠️  Telegram 请求失败，{wait}s 后重试: {e}")
                    time.sleep(wait)
                else:
                    raise
        return None

    def send_message(self, text: str):
        """发送文本消息（自动分段）"""
        chunks = [text[i:i + TELEGRAM_MAX_MSG_LEN]
                  for i in range(0, len(text), TELEGRAM_MAX_MSG_LEN)]
        for chunk in chunks:
            self._request("sendMessage", json={
                "chat_id": self.chat_id,
                "text": chunk,
                "disable_web_page_preview": True,
            })
            if len(chunks) > 1:
                time.sleep(0.5)

    def send_document(self, file_path: str, caption: str = ""):
        """发送文件"""
        with open(file_path, "rb") as f:
            self._request(
                "sendDocument",
                data={"chat_id": self.chat_id, "caption": caption[:1024]},
                files={"document": f},
            )

    # ------------------------------------------------------------------
    # 高级方法：推送日报
    # ------------------------------------------------------------------

    def send_daily_report(self, papers: List[Dict],
                          summaries: Dict[str, str],
                          report_file: str = None):
        """
        推送完整日报：消息 + 文件

        Args:
            papers:      Top N 论文列表
            summaries:   {arxiv_id: summary} 摘要字典
            report_file: Markdown 报告文件路径（可选）
        """
        if not self.configured:
            print("  ⚠️  未配置 Telegram，跳过推送")
            return

        today = datetime.now().strftime("%Y-%m-%d")

        if not papers:
            self.send_message(f"📭 arXiv 智能日报 {today}\n\n今日无特别相关的论文。")
            return

        # ---- 1. 消息 ----
        lines = [
            f"🤖 arXiv 智能日报 {today}",
            f"相关论文：{len(papers)} 篇\n",
        ]

        for i, paper in enumerate(papers[:10], 1):
            title = paper["title"]
            if len(title) > 80:
                title = title[:77] + "..."
            arxiv_url = f"https://arxiv.org/abs/{paper['arxiv_id']}"

            # 元数据标签
            score = paper.get("quality_score", 0)
            score_tag = f"[{score:.0f}分]" if score > 0 else ""

            citations = paper.get("s2_citation_count", 0)
            cite_tag = f"引用:{citations}" if citations > 0 else ""

            if paper.get("cr_published"):
                venue = paper.get("cr_journal", "") or paper.get("s2_venue", "")
                pub_tag = f"✅{venue}" if venue else "✅已发表"
            elif paper.get("s2_venue"):
                pub_tag = f"📋{paper['s2_venue']}"
            else:
                pub_tag = "📝预印本"

            meta = " | ".join(p for p in [score_tag, cite_tag, pub_tag] if p)

            lines.append(f"{i}. {title}")
            lines.append(f"   {meta}")

            # 作者信息（优先 S2，缺失则回退 arXiv）
            s2_authors = paper.get("s2_authors", [])
            valid_s2_names = [
                (a.get("name") or "").strip()
                for a in s2_authors
                if (a.get("name") or "").strip()
            ]
            if valid_s2_names:
                author_text = ", ".join(valid_s2_names[:3])
                if len(valid_s2_names) > 3:
                    author_text += "..."
            else:
                arxiv_authors = paper.get("authors", []) or []
                author_text = ", ".join(arxiv_authors[:3]) if arxiv_authors else "未知作者"
                if len(arxiv_authors) > 3:
                    author_text += "..."
            lines.append(f"   作者: {author_text}")
            lines.append(f"   {arxiv_url}")

            # 三段式摘要（bullet-point 逐行展示）
            if paper["arxiv_id"] in summaries:
                for bullet in summaries[paper["arxiv_id"]].strip().split("\n"):
                    bullet = bullet.strip()
                    if bullet:
                        lines.append(f"   {bullet}")
            lines.append("")

        if len(papers) > 10:
            lines.append(f"... 还有 {len(papers) - 10} 篇，请查看完整报告附件")

        try:
            self.send_message("\n".join(lines))
            print("  📨 Telegram 消息已发送")
        except Exception as e:
            print(f"  ⚠️  Telegram 消息发送失败: {e}")

        # ---- 2. 报告文件 ----
        if report_file:
            try:
                self.send_document(
                    report_file,
                    caption=f"📊 arXiv 智能日报 {today}（{len(papers)} 篇）",
                )
                print("  📎 Telegram 报告文件已发送")
            except Exception as e:
                print(f"  ⚠️  Telegram 文件发送失败: {e}")
